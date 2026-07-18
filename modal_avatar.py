import modal
import os

app = modal.App("avatar-pipeline")

volume = modal.Volume.from_name("avatar-models", create_if_missing=True)

# ─────────────────────────────────────────────────────────────────────────────
# IMAGE 1: LatentSync 1.6 (ByteDance 2025) — modern, clean Stable Diffusion
#          based lip sync. No ancient dependency baggage.
# ─────────────────────────────────────────────────────────────────────────────
latentsync_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git", "ffmpeg", "libgl1", "libglib2.0-0", "libsm6", "libxrender1", "libxext6")
    .run_commands("git clone https://github.com/bytedance/LatentSync.git /latentsync")
    .run_commands("pip install -r /latentsync/requirements.txt")
)

# ─────────────────────────────────────────────────────────────────────────────
# IMAGE 2: Wan 2.1 — modern text-to-video, completely isolated deps
# ─────────────────────────────────────────────────────────────────────────────
wan_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git", "ffmpeg")
    .pip_install(
        "torch", "torchvision", "torchaudio",
        "transformers", "huggingface_hub", "accelerate", "sentencepiece",
        "imageio-ffmpeg", "imageio[ffmpeg]",
    )
    .run_commands("pip install git+https://github.com/huggingface/diffusers.git")
)


# ─────────────────────────────────────────────────────────────────────────────
# MODEL DOWNLOADER — downloads both model sets to the shared volume
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
    latentsync_ready = os.path.exists("/models/latentsync/latentsync_unet.pt")
    whisper_ready = os.path.exists("/models/latentsync/whisper/tiny.pt")
    wan_ready = os.path.exists("/models/wan/model_index.json")

    if latentsync_ready and whisper_ready and wan_ready:
        print("All model sets already cached on volume.")
        return

    if not latentsync_ready:
        print("Downloading LatentSync 1.6 model weights...")
        huggingface_hub.snapshot_download("ByteDance/LatentSync-1.6", local_dir="/models/latentsync")

    if not whisper_ready:
        import urllib.request
        print("Downloading Whisper tiny model for LatentSync audio encoder...")
        os.makedirs("/models/latentsync/whisper", exist_ok=True)
        # OpenAI Whisper tiny model weights
        whisper_url = "https://openaipublic.azureedge.net/main/whisper/models/65147644a518d12f04e32d6f3b26facc3f8dd46e5390956a9424a650c0ce22b9/tiny.pt"
        urllib.request.urlretrieve(whisper_url, "/models/latentsync/whisper/tiny.pt")
        print("Whisper tiny.pt downloaded.")

    if not wan_ready:
        print("Downloading Wan 2.1 model weights...")
        huggingface_hub.snapshot_download("Wan-AI/Wan2.1-T2V-1.3B-Diffusers", local_dir="/models/wan")

    volume.commit()
    print("Download complete and cached to volume.")


# ─────────────────────────────────────────────────────────────────────────────
# GENERATE AVATAR — LatentSync 1.6 lip sync
#   Input:  WAV audio bytes + JPEG photo bytes
#   Output: MP4 bytes of the face animating to the audio
# ─────────────────────────────────────────────────────────────────────────────
@app.function(
    image=latentsync_image,
    gpu="a100-80gb",
    timeout=3600,
    retries=1,
    volumes={"/models": volume}
)
def generate_avatar(audio_bytes: bytes, photo_bytes: bytes) -> bytes:
    import tempfile
    import subprocess
    import os

    print("Generating avatar clip using LatentSync 1.6...")

    with tempfile.TemporaryDirectory() as td:
        audio_path = os.path.join(td, "audio.wav")
        photo_path = os.path.join(td, "photo.jpg")
        ref_video_path = os.path.join(td, "ref_video.mp4")
        output_path = os.path.join(td, "output.mp4")

        with open(audio_path, "wb") as f:
            f.write(audio_bytes)
        with open(photo_path, "wb") as f:
            f.write(photo_bytes)

        # LatentSync needs a video as input, not a static photo.
        # Convert the photo into a short looping video at 25fps.
        ffmpeg_cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", photo_path,
            "-t", "5", "-r", "25", "-vf", "scale=512:512",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            ref_video_path
        ]
        subprocess.run(ffmpeg_cmd, check=True, capture_output=True)

        # LatentSync expects a 'checkpoints/' dir relative to its CWD.
        # Symlink the volume model directory so all paths resolve correctly.
        import shutil
        checkpoints_link = "/latentsync/checkpoints"
        if os.path.islink(checkpoints_link) or os.path.exists(checkpoints_link):
            if os.path.islink(checkpoints_link):
                os.unlink(checkpoints_link)
            else:
                shutil.rmtree(checkpoints_link)
        os.symlink("/models/latentsync", checkpoints_link)
        print("Symlinked /latentsync/checkpoints -> /models/latentsync")

        # LatentSync: python -m scripts.inference
        cmd = [
            "python", "-m", "scripts.inference",
            "--unet_config_path", "/latentsync/configs/unet/stage2_512.yaml",
            "--inference_ckpt_path", "/models/latentsync/latentsync_unet.pt",
            "--inference_steps", "20",
            "--guidance_scale", "1.0",
            "--video_path", ref_video_path,
            "--audio_path", audio_path,
            "--video_out_path", output_path,
            "--seed", "42",
        ]

        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True, cwd="/latentsync")
            if os.path.exists(output_path):
                with open(output_path, "rb") as f:
                    return f.read()
            else:
                raise RuntimeError(
                    f"LatentSync finished but output.mp4 not found.\nSTDOUT:\n{result.stdout}"
                )
        except subprocess.CalledProcessError as e:
            err_msg = e.stderr if e.stderr else e.stdout
            raise RuntimeError(f"LatentSync crashed!\nSTDERR:\n{err_msg}") from e


# ─────────────────────────────────────────────────────────────────────────────
# GENERATE B-ROLL — Wan 2.1 text-to-video, isolated modern stack
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
