import modal
import os
import subprocess

app = modal.App("avatar-pipeline")

volume = modal.Volume.from_name("avatar-models", create_if_missing=True)

# --- B-ROLL (LTX-Video 2.3 Pro) ---
ltx_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git")
    .pip_install(
        "torch==2.5.1", "torchvision==0.20.1", "torchaudio==2.5.1",
        extra_index_url="https://download.pytorch.org/whl/cu121",
    )
    .run_commands(
        "pip install 'git+https://github.com/huggingface/diffusers.git'"
    )
    .pip_install("transformers", "accelerate", "imageio", "imageio-ffmpeg", "sentencepiece")
)

@app.function(image=ltx_image, gpu="a100", timeout=3600, volumes={"/models": volume})
def generate_broll(prompt: str, duration_seconds: int) -> bytes:
    import torch
    from diffusers import LTXPipeline
    from diffusers.utils import export_to_video
    
    os.environ["HF_HOME"] = "/models/huggingface"
    
    pipe = LTXPipeline.from_pretrained("Lightricks/LTX-Video", torch_dtype=torch.bfloat16)
    pipe.to("cuda")
    
    # Enforce standard prompt to avoid NFL
    enhanced_prompt = f"European soccer, photorealistic, 4k, cinematic, detailed. {prompt}. no american football, no NFL."
    
    num_frames = 121  # Approx 5 seconds at 24fps
    
    video = pipe(
        prompt=enhanced_prompt,
        width=704,
        height=480,
        num_frames=num_frames,
        num_inference_steps=50,
    ).frames[0]
    
    out_path = "/tmp/out.mp4"
    export_to_video(video, out_path, fps=24)
    with open(out_path, "rb") as f:
        return f.read()


# --- AVATAR (LongCat-Video-Avatar-1.5) ---
longcat_image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("git", "ffmpeg", "wget", "libsndfile1")
    .pip_install("torch==2.3.0", "torchvision", "torchaudio")
    .run_commands(
        "git clone https://github.com/meituan-longcat/LongCat-Video.git /workspace/LongCat-Video",
        "sed -i '/libsndfile1/d' /workspace/LongCat-Video/requirements_avatar.txt",
        "sed -i '/tritonserverclient/d' /workspace/LongCat-Video/requirements_avatar.txt",
        "cd /workspace/LongCat-Video && pip install -r requirements_avatar.txt",
        "pip install -U 'huggingface_hub[cli]' hf",
    )
)

@app.function(image=longcat_image, gpu="a100", timeout=3600, volumes={"/models": volume}, retries=3)
def generate_avatar(audio_bytes: bytes, photo_bytes: bytes) -> bytes:
    import json
    import math
    import shutil
    import wave
    
    os.environ["HF_HOME"] = "/models/huggingface"
    
    audio_path = "/tmp/input.wav"
    photo_path = "/tmp/input.jpg"
    with open(audio_path, "wb") as f: f.write(audio_bytes)
    with open(photo_path, "wb") as f: f.write(photo_bytes)
        
    model_dir = "/models/LongCat-Video-Avatar-1.5"
    if not os.path.exists(os.path.join(model_dir, "config.json")):
        print("Downloading LongCat model...")
        subprocess.run(["hf", "download", "meituan-longcat/LongCat-Video-Avatar-1.5", "--local-dir", model_dir], check=True)
        
    input_json_path = "/tmp/input.json"
    input_data = {
        "prompt": "a person speaking naturally, upper body, cinematic lighting",
        "cond_audio": {
            "person1": audio_path
        },
        "cond_image": photo_path
    }
    with open(input_json_path, "w") as f:
        json.dump(input_data, f)
        
    # Calculate audio duration
    with wave.open(audio_path, "r") as f:
        frames = f.getnframes()
        rate = f.getframerate()
        duration = frames / float(rate)
        
    # LongCat 1.5 calculates num_segments as:
    # duration = 3.72 + (num_segments - 1) * 3.2
    if duration <= 3.72:
        num_segments = 1
    else:
        num_segments = math.ceil((duration - 3.72) / 3.2) + 1

    os.chdir("/workspace/LongCat-Video")
    cmd = [
        "torchrun", "--nproc_per_node=1",
        "run_demo_avatar_single_audio_to_video.py",
        "--input_json", input_json_path,
        "--checkpoint_dir", model_dir,
        "--output_dir", "/tmp/output",
        "--model_type", "avatar-v1.5",
        "--use_distill",
        "--num_segments", str(num_segments)
    ]
    
    print(f"Running LongCat with {num_segments} segments for {duration:.2f}s audio...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("LongCat Error:", result.stderr)
        raise Exception(f"LongCat failed: {result.stderr}")
        
    out_dir = "/tmp/output"
    files = [f for f in os.listdir(out_dir) if f.endswith(".mp4")]
    if not files:
        raise Exception(f"No output generated. Log: {result.stderr}")
        
    out_video = os.path.join(out_dir, files[0])
    with open(out_video, "rb") as f:
        return f.read()


# --- MODEL PRE-DOWNLOAD FUNCTIONS ---

@app.function(image=ltx_image, gpu="a100", timeout=3600, volumes={"/models": volume})
def _download_ltx():
    """Pre-download LTX-Video weights into the persistent volume."""
    import torch
    from diffusers import LTXPipeline
    os.environ["HF_HOME"] = "/models/huggingface"
    print("Downloading LTX-Video weights...")
    LTXPipeline.from_pretrained("Lightricks/LTX-Video", torch_dtype=torch.bfloat16)
    volume.commit()
    print("LTX-Video weights cached.")


@app.function(image=longcat_image, timeout=3600, volumes={"/models": volume})
def _download_longcat():
    """Pre-download LongCat-Video-Avatar-1.5 weights into the persistent volume."""
    os.environ["HF_HOME"] = "/models/huggingface"
    model_dir = "/models/LongCat-Video-Avatar-1.5"
    if not os.path.exists(os.path.join(model_dir, "config.json")):
        print("Downloading LongCat model weights...")
        subprocess.run(
            ["hf", "download", "meituan-longcat/LongCat-Video-Avatar-1.5", "--local-dir", model_dir],
            check=True
        )
        volume.commit()
        print("LongCat weights cached.")
    else:
        print("LongCat weights already cached, skipping.")


@app.local_entrypoint()
def download_models():
    """Pre-download all model weights to the persistent volume. Run with: modal run modal_avatar.py"""
    print("Pre-downloading LTX-Video and LongCat model weights...")
    _download_ltx.remote()
    _download_longcat.remote()
    print("All model weights downloaded and cached successfully.")

