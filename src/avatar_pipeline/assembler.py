import subprocess
import os

def assemble(clip_paths: list[str], broll_paths: list[str], output_path: str):
    """
    Assemble the avatar clips and broll clips using FFmpeg.
    """
    if not clip_paths:
        return
        
    list_file = "concat_list.txt"
    with open(list_file, "w") as f:
        for i, clip in enumerate(clip_paths):
            f.write(f"file '{os.path.abspath(clip)}'\n")
            if i < len(broll_paths):
                f.write(f"file '{os.path.abspath(broll_paths[i])}'\n")
            elif broll_paths: # fallback to repeating broll
                f.write(f"file '{os.path.abspath(broll_paths[i % len(broll_paths)])}'\n")

    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-c:v", "libx264", "-c:a", "aac",
        output_path
    ]
    
    subprocess.run(cmd, check=True)
    if os.path.exists(list_file):
        os.remove(list_file)
