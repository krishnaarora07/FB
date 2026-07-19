import modal

print("Connecting to Modal to test Fish Speech Open Source...")
generate_voiceover = modal.Function.from_name("avatar-pipeline", "generate_voiceover")
audio_bytes = generate_voiceover.remote("Hello! I am a fully open source text to speech engine running on an L4 GPU.")

with open("test_fish.wav", "wb") as f:
    f.write(audio_bytes)

print("Saved to test_fish.wav! It works!")
