import modal
import os

app = modal.App("avatar-pipeline")

volume = modal.Volume.from_name("avatar-models", create_if_missing=True)

# ─────────────────────────────────────────────────────────────────────────────
# IMAGE 1: Hallo2 — frozen 2023-era deps, no modern diffusers allowed here
# ─────────────────────────────────────────────────────────────────────────────
hallo2_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git", "ffmpeg", "libgl1", "libglib2.0-0")
    .run_commands("git clone https://github.com/fudan-generative-vision/hallo2.git /hallo2")
    .run_commands("pip install -r /hallo2/requirements.txt")
    # Upgrade only torch/cuda — leave transformers/diffusers at hallo2-pinned versions
    .run_commands("pip install -U torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121")
)

# ─────────────────────────────────────────────────────────────────────────────
# IMAGE 2: Wan 2.1 — modern stack, no hallo2 baggage at all
# ─────────────────────────────────────────────────────────────────────────────
wan_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg")
    .pip_install(
        "torch", "torchvision", "torchaudio",
        "transformers", "huggingface_hub", "accelerate", "sentencepiece",
        "imageio-ffmpeg", "imageio[ffmpeg]",
    )
    .run_commands("pip install git+https://github.com/huggingface/diffusers.git")
)


# ─────────────────────────────────────────────────────────────────────────────
# MODEL DOWNLOADER — runs on wan_image (has huggingface_hub modern)
# ─────────────────────────────────────────────────────────────────────────────
@app.function(
    image=wan_image,
    timeout=3600,
    volumes={"/models": volume}
)
def download_models():
    import huggingface_hub
    import os

    print("Checking if models are already downloaded...")
    hallo2_ready = os.path.exists("/models/hallo2/net_g.pth") or os.path.exists("/models/hallo2/config.json")
    wan_ready = os.path.exists("/models/wan/model_index.json")

    if hallo2_ready and wan_ready:
        print("Both model sets already cached on volume.")
        return

    if not hallo2_ready:
        print("Downloading Hallo2 model weights...")
        huggingface_hub.snapshot_download("fudan-generative-ai/hallo2", local_dir="/models/hallo2")

    if not wan_ready:
        print("Downloading Wan 2.1 model weights...")
        huggingface_hub.snapshot_download("Wan-AI/Wan2.1-T2V-1.3B-Diffusers", local_dir="/models/wan")

    volume.commit()
    print("Download complete and cached to volume.")


# ─────────────────────────────────────────────────────────────────────────────
# GENERATE AVATAR — uses hallo2_image (isolated old deps)
# ─────────────────────────────────────────────────────────────────────────────
@app.function(
    image=hallo2_image,
    gpu="a100-80gb",
    timeout=3600,
    retries=3,
    volumes={"/models": volume}
)
def generate_avatar(audio_bytes: bytes, photo_bytes: bytes) -> bytes:
    import tempfile
    import subprocess
    import os

    print("Generating avatar clip using Hallo2...")

    with tempfile.TemporaryDirectory() as td:
        audio_path = os.path.join(td, "audio.wav")
        photo_path = os.path.join(td, "photo.jpg")
        output_path = os.path.join(td, "output.mp4")

        with open(audio_path, "wb") as f:
            f.write(audio_bytes)
        with open(photo_path, "wb") as f:
            f.write(photo_bytes)

        config_path = os.path.join(td, "config.yaml")
        yaml_content = f"""source_image: "{photo_path}"
driving_audio: "{audio_path}"
save_path: "{output_path}"
model_path: "/models/hallo2"
"""
        with open(config_path, "w") as f:
            f.write(yaml_content)

        cmd = ["python", "/hallo2/scripts/inference_long.py", "--config", config_path]

        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            if os.path.exists(output_path):
                with open(output_path, "rb") as f:
                    return f.read()
            else:
                raise RuntimeError(
                    f"Hallo2 finished without error but output.mp4 not found.\nstdout:\n{result.stdout}"
                )
        except subprocess.CalledProcessError as e:
            err_msg = e.stderr if e.stderr else e.stdout
            raise RuntimeError(f"Hallo2 crashed!\nSTDERR:\n{err_msg}") from e


# ─────────────────────────────────────────────────────────────────────────────
# GENERATE B-ROLL — uses wan_image (modern stack, no hallo2 baggage)
# ─────────────────────────────────────────────────────────────────────────────
@app.function(
    image=wan_image,
    gpu="a100-80gb",
    timeout=3600,
    volumes={"/models": volume}
)
def generate_broll(prompt: str, duration_seconds: int) -> bytes:
    import tempfile
    import os
    import torch
    from diffusers import WanPipeline
    from diffusers.utils import export_to_video

    print(f"Generating B-roll: '{prompt}' ({duration_seconds}s) with Wan 2.1...")

    model_dir = "/models/wan"
    pipe = WanPipeline.from_pretrained(model_dir, torch_dtype=torch.bfloat16)
    pipe.to("cuda")

    # 16 fps; cap at 81 frames (~5s) to avoid A100 OOM
    num_frames = min(int(duration_seconds * 16), 81)
    video = pipe(prompt, num_frames=num_frames, num_inference_steps=50).frames[0]

    with tempfile.TemporaryDirectory() as td:
        output_path = os.path.join(td, "output.mp4")
        export_to_video(video, output_path, fps=16)
        with open(output_path, "rb") as f:
            return f.read()
