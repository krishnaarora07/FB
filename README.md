# Football Trend Video Pipeline

This repo is a starter pipeline for making short, trend-reactive football videos:

1. Collects YouTube sports/trending metadata plus recent uploads from the official FIFA handle.
2. Uses Gemini Flash to choose a World Cup-related angle and write a quirky voiceover script.
3. Uses ElevenLabs to generate the voiceover.
4. Finds portrait B-roll from Pexels.
5. Builds and submits a Shotstack edit.
6. Optionally downloads the rendered video and uploads it to YouTube.

The pipeline uses YouTube videos as discovery signals only. It does not download or reuse YouTube footage in the final edit; the rendered video is assembled from generated narration and Pexels footage.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
Copy-Item .env.example .env
```

Fill in `.env` with API keys.

## Quick Dry Run

Dry run collects YouTube signals and asks Gemini for a topic/script, then stops before ElevenLabs, Pexels, Shotstack, or upload:

```powershell
football-pipeline run --dry-run
```

Outputs are written under `runs/<timestamp>/`.

## Build Assets Without Rendering

This collects signals, writes a script, fetches B-roll metadata, generates a local ElevenLabs MP3, and writes a Shotstack edit JSON. It does not submit the render:

```powershell
football-pipeline run
```

## Render With Shotstack

Shotstack needs remote/public URLs. The pipeline requests a Shotstack signed upload URL, uploads the generated MP3, then uses that URL in the edit:

```powershell
football-pipeline run --render
```

## Upload To YouTube

The YouTube upload step uses OAuth, so you need a Google Cloud OAuth client JSON at `YOUTUBE_CLIENT_SECRETS_FILE`.

```powershell
football-pipeline run --render --upload
```

Videos upload as private by default. Change `YOUTUBE_UPLOAD_PRIVACY_STATUS` when you are ready.

## Useful Commands

Collect only:

```powershell
football-pipeline collect --out runs/manual/signals.json
```

Create topic/script from saved signals:

```powershell
football-pipeline ideate --signals runs/manual/signals.json --out runs/manual/topic.json
```

Fetch B-roll:

```powershell
football-pipeline broll --topic runs/manual/topic.json --out runs/manual/broll.json
```

Generate voiceover:

```powershell
football-pipeline voiceover --topic runs/manual/topic.json --out runs/manual/voiceover.mp3
```

Render from prepared files:

```powershell
football-pipeline render --topic runs/manual/topic.json --broll runs/manual/broll.json --voiceover runs/manual/voiceover.mp3 --out runs/manual
```

## Notes

- Keep the upload privacy as `private` while testing.
- Review every script before publishing. Trend automation can overstate facts if source metadata is thin.
- Check Pexels attribution and license requirements for your channel workflow.
- YouTube Data API quotas vary by endpoint; collection is intentionally metadata-first to keep cost and rights risk low.

