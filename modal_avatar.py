import modal
import os
import subprocess

app = modal.App("avatar-pipeline")

volume = modal.Volume.from_name("avatar-models", create_if_missing=True)


# --- VOICEOVER (Fish Speech 1.5) ---
fish_speech_image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("git", "ffmpeg", "curl", "wget", "build-essential", "portaudio19-dev")
    .run_commands(
        "pip install uv",
        "uv pip install --system torch==2.5.1 torchaudio==2.5.1 torchvision==0.20.1 --extra-index-url https://download.pytorch.org/whl/cu121",
        "git clone -b v1.5.1 https://github.com/fishaudio/fish-speech.git /workspace/fish-speech",
        "cd /workspace/fish-speech && uv pip install --system -e . --extra-index-url https://download.pytorch.org/whl/cu121",
        "uv pip install --system -U 'huggingface_hub[cli]' hf requests pydantic",
        "uv pip install --system -U protobuf tensorboard"
    )
)

@app.function(image=fish_speech_image, gpu="l4", timeout=3600, volumes={"/models": volume})
def generate_voiceover(text: str) -> bytes:
    import os
    import subprocess
    import time
    import requests
    
    os.environ["HF_HOME"] = "/models/huggingface"
    base_model_dir = "/models/fish-speech-1.5"
    if not os.path.exists(os.path.join(base_model_dir, "config.json")):
        from huggingface_hub import snapshot_download
        print("Downloading Fish Speech 1.5 weights...")
        snapshot_download(repo_id="fishaudio/fish-speech-1.5", local_dir=base_model_dir)
        
    os.chdir("/workspace/fish-speech")
    
    server_cmd = [
        "python", "tools/api_server.py",
        "--llama-checkpoint-path", base_model_dir,
        "--decoder-checkpoint-path", f"{base_model_dir}/firefly-gan-vq-fsq-8x1024-21hz-generator.pth",
        "--listen", "127.0.0.1:8080"
    ]
    
    print("Starting Fish Speech API server...")
    proc = subprocess.Popen(server_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    
    ready = False
    for i in range(300):
        try:
            r = requests.get("http://127.0.0.1:8080/v1/health", timeout=2)
            if r.status_code == 200:
                ready = True
                break
        except Exception:
            pass
            
        if proc.poll() is not None:
            out, _ = proc.communicate()
            raise RuntimeError(f"Fish Speech API server crashed during boot:\n{out.decode('utf-8', errors='ignore')}")
            
        time.sleep(1)
        
    if not ready:
        proc.kill()
        out, _ = proc.communicate()
        raise RuntimeError(f"Fish Speech API server failed to start within 300s. Log:\n{out.decode('utf-8', errors='ignore')}")
        
    print("Generating TTS...")
    req_data = {
        "text": text,
        "format": "wav"
    }
    resp = requests.post("http://127.0.0.1:8080/v1/tts", json=req_data)
    
    proc.kill()
    proc.wait()
    
    if resp.status_code != 200:
        raise RuntimeError(f"TTS API failed: {resp.text}")
        
    return resp.content


# --- AVATAR (LongCat-Video-Avatar-1.5) ---
longcat_image = (
    modal.Image.debian_slim(python_version="3.10")
    .apt_install("git", "ffmpeg", "wget", "libsndfile1")
    .run_commands(
        "pip install uv",
        "uv pip install --system torch==2.5.1 torchaudio==2.5.1 torchvision==0.20.1 --extra-index-url https://download.pytorch.org/whl/cu121"
    )
    .run_commands(
        "git clone https://github.com/meituan-longcat/LongCat-Video.git /workspace/LongCat-Video",
        "sed -i '/libsndfile1/d' /workspace/LongCat-Video/requirements_avatar.txt",
        "sed -i '/tritonserverclient/d' /workspace/LongCat-Video/requirements_avatar.txt",
        "cd /workspace/LongCat-Video && uv pip install --system -r requirements_avatar.txt",
        "uv pip install --system -U 'huggingface_hub[cli]' hf",
        "uv pip install --system transformers accelerate diffusers sentencepiece einops loguru ftfy regex imageio imageio-ffmpeg",
        "uv pip install --system https://github.com/Dao-AILab/flash-attention/releases/download/v2.8.3.post1/flash_attn-2.8.3.post1+cu12torch2.5cxx11abiFALSE-cp310-cp310-linux_x86_64.whl"
    )
)

@app.function(image=longcat_image, gpu="a100-80gb", timeout=3600, volumes={"/models": volume}, retries=3)
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
        
    base_model_dir = "/models/LongCat-Video"
    if not os.path.exists(os.path.join(base_model_dir, "model_index.json")):
        from huggingface_hub import snapshot_download
        print("Downloading LongCat Base model...")
        snapshot_download(repo_id="meituan-longcat/LongCat-Video", local_dir=base_model_dir)

    model_dir = "/models/LongCat-Video-Avatar-1.5"
    if not os.path.exists(os.path.join(model_dir, "config.json")):
        from huggingface_hub import snapshot_download
        print("Downloading LongCat Avatar model...")
        snapshot_download(repo_id="meituan-longcat/LongCat-Video-Avatar-1.5", local_dir=model_dir)
        
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


@app.function(image=longcat_image, timeout=3600, volumes={"/models": volume})
def _download_longcat():
    """Pre-download LongCat-Video-Avatar weights."""
    import os
    from huggingface_hub import snapshot_download
    os.environ["HF_HOME"] = "/models/huggingface"
    
    # Base model (Tokenizer, VAE, etc.)
    base_model_dir = "/models/LongCat-Video"
    if not os.path.exists(os.path.join(base_model_dir, "model_index.json")):
        print("Downloading LongCat Base model weights...")
        snapshot_download(repo_id="meituan-longcat/LongCat-Video", local_dir=base_model_dir)
        
    # Avatar model (DiT weights)
    model_dir = "/models/LongCat-Video-Avatar-1.5"
    if not os.path.exists(os.path.join(model_dir, "config.json")):
        print("Downloading LongCat Avatar model weights...")
        snapshot_download(repo_id="meituan-longcat/LongCat-Video-Avatar-1.5", local_dir=model_dir)
        
    volume.commit()
    print("LongCat weights cached.")


@app.function(image=fish_speech_image, timeout=3600, volumes={"/models": volume})
def _download_fish_speech():
    """Pre-download Fish Speech 1.5 weights into the persistent volume."""
    import os
    from huggingface_hub import snapshot_download
    os.environ["HF_HOME"] = "/models/huggingface"
    base_model_dir = "/models/fish-speech-1.5"
    if not os.path.exists(os.path.join(base_model_dir, "config.json")):
        print("Downloading Fish Speech 1.5 weights...")
        snapshot_download(repo_id="fishaudio/fish-speech-1.5", local_dir=base_model_dir)
    volume.commit()
    print("Fish Speech weights cached.")

@app.local_entrypoint()
def download_models():
    """Pre-download all model weights to the persistent volume. Run with: modal run modal_avatar.py"""
    print("Pre-downloading model weights...")
    _download_longcat.remote()
    _download_fish_speech.remote()
    print("All model weights downloaded and cached successfully.")

