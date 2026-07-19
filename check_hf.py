import requests
resp = requests.get("https://huggingface.co/api/models/fishaudio/fish-speech-1.5/tree/main")
if resp.status_code == 200:
    for item in resp.json():
        print(item["path"])
else:
    print("Failed to fetch.")
