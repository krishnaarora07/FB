# ⚽ Fully Autonomous Football Shorts Pipeline: The Ultimate AI Creator

A fully automated, end-to-end AI pipeline that acts as a 10M-subscriber YouTube creator. It autonomously researches trending football topics, writes high-retention scripts, generates highly expressive human voiceovers, creates 3D Parallax visuals, syncs MrBeast-style subtitles, and uploads the final video to YouTube—all automatically scheduled via GitHub Actions.

---

## 🏗️ The Final Architecture

This pipeline is powered by a chain of advanced AI models working together seamlessly in the cloud:

1. **AI Scriptwriting & Topic Selection (Google Gemini 2.5 Flash)**
   - Scrapes the latest football trends and selects highly controversial, engaging, or viral topics.
   - Specifically prompted to write high-energy, hook-driven scripts optimized for YouTube Shorts retention.

2. **Expressive Voiceover Generation (Chatterbox TTS / Resemble AI)**
   - Uses `chatterbox-tts`, a massive, locally-run PyTorch AI model.
   - Generates highly expressive, emotional, and human-sounding narration entirely on the GitHub Actions CPU.

3. **Intelligent Asset Sourcing**
   - **Google Custom Search API:** Dynamically searches the web for high-resolution images of specific football players and managers mentioned in the script.
   - **Pexels API Fallback:** If the script calls for generic footage or Google ratelimits/fails, it seamlessly falls back to downloading 4K stock images from Pexels.

4. **3D Parallax Visual Engine (`rembg` / U2-Net)**
   - Implements a "Ken Burns 2.0" documentary-style visual effect.
   - Uses `rembg` (an AI background remover) to instantly cut out the foreground subject (e.g., Lionel Messi) from the background.
   - Applies a heavy Gaussian blur to the background and animates it zooming backwards, while the sharp cutout player zooms forwards, creating a powerful illusion of 3D depth.

5. **Perfect Subtitle Synchronization (OpenAI Whisper)**
   - Uses OpenAI's `whisper-timestamped` model as a forced-aligner.
   - Listens to the generated Chatterbox audio and mathematically extracts the exact start and end millisecond of every spoken word.
   - Feeds this microsecond data into the subtitle engine to generate perfectly synced, "MrBeast-style" pop-in word animations.

6. **100% Cloud Automated CI/CD (GitHub Actions)**
   - Runs on a CRON schedule (twice a day).
   - Implements aggressive caching (`~/.u2net`, `~/.cache/huggingface/hub` and `~/.cache/whisper`) so gigabytes of AI models are only downloaded once. This keeps the pipeline executing incredibly fast and completely free.

---

## 📖 The Evolution: From Basic Bot to AI Powerhouse

This repository did not start this advanced. It evolved through several massive architectural overhauls to reach its current state as a "Real Creator" pipeline.

### Phase 1: The Basic Automation Bot
Initially, this was a simple Python script using `moviepy`. It used **Microsoft Edge-TTS** (a fast but highly robotic voice), downloaded generic video clips, and slapped basic text on top. It worked, but it felt like a soulless AI spam bot.

### Phase 2: The "Real Creator" Update
To fix the soulless feeling, the entire **Gemini AI** prompt was overhauled. Instead of just "summarizing news", Gemini was instructed to take on the persona of a veteran YouTuber with 10M subscribers. It was taught to prioritize hyper-engaging hooks, controversial opinions, and fast-paced storytelling to maximize audience retention. 

### Phase 3: The 3D Parallax Visual Engine
Using generic stock footage was boring. To make the videos feel premium, we built a dynamic visual engine. We integrated `rembg` (a U2-Net neural network) directly into the rendering pipeline. Now, when the AI downloads a photo of a player, it slices the player out of the background. It blurs the background and scales the two layers in opposite directions, creating a high-end **3D Parallax effect** dynamically on the fly.

### Phase 4: The Voice Overhaul (Chatterbox TTS)
The Edge-TTS voice was still too robotic for a "Real Creator" vibe. We ripped out Edge-TTS and installed the heavy-duty **Chatterbox TTS** model. Because this is a massive PyTorch model, we had to configure the pipeline to load it directly into GitHub Actions' CPU memory. The result was a dramatic increase in voice quality, emotion, and realism.

### Phase 5: Subtitle Sync Restoration (Whisper AI)
Upgrading to Chatterbox created a massive problem: unlike Edge-TTS, Chatterbox did not provide a "cheat sheet" of timestamps for when each word was spoken. This completely broke our MrBeast-style pop-in subtitles. 
To fix this without downgrading the voice, we integrated **OpenAI's Whisper AI** (`whisper-timestamped`). We chained the models together: after Chatterbox generates the `.wav` audio, Whisper immediately listens to it and acts as an ultra-precise stopwatch, mapping out the exact millisecond every word is spoken. The subtitles were perfectly synced once again.

### Phase 6: The API Resilience Update
As the AI got smarter, it started searching DuckDuckGo for photos of specific players (e.g., "Cristiano Ronaldo frustrated"). However, DuckDuckGo's anti-bot protection started throwing `403 Ratelimit` errors, crashing the pipeline on GitHub Actions.
We ripped out the DuckDuckGo scraper and integrated the official **Google Custom Search API**. To ensure the pipeline would *never* fail, we kept the **Pexels API** integration as a hardcoded fail-safe. If Google ever runs out of free searches, the script instantly abandons the search and pulls stock imagery from Pexels instead.

### Phase 7: CI/CD & Storage Optimization
Because we strapped three massive AI models (Chatterbox, Whisper, and Rembg) into the pipeline, downloading them every run would take hours and waste bandwidth. We engineered the GitHub Actions `daily_pipeline.yml` to utilize GitHub's internal cache servers. The gigabytes of AI models are stored permanently in the cache, allowing the heavy AI pipeline to run 100% for free inside the standard GitHub Actions limits.

---

## 🚀 Setup & Deployment Guide

Because this runs entirely on GitHub Actions, you do not need to install anything on your local computer or pay for expensive GPU servers. 

However, you must provide the following API keys as **Repository Secrets** in GitHub (`Settings > Secrets and variables > Actions`):

| Secret Name | Description |
| :--- | :--- |
| `GEMINI_API_KEY` | (Required) Used by Google GenAI to write the video scripts. |
| `YOUTUBE_API_KEY` | (Required) Used to query YouTube for trending football topics. |
| `GOOGLE_SEARCH_API_KEY` | (Required) Used to bypass bot-blocks and download high-res player photos. |
| `GOOGLE_SEARCH_ENGINE_ID` | (Required) Tied to the Search API; must be configured to "Search entire web" with Image Search ON. |
| `PEXELS_API_KEY` | (Required) Used as an unbreakable fail-safe if Google Search fails. |
| `YOUTUBE_CLIENT_SECRETS_JSON` | (Required) The OAuth client secret for the YouTube channel you are uploading to. |
| `YOUTUBE_TOKEN_JSON` | (Required) The OAuth authorization token so the bot can upload videos automatically. |

Once these secrets are saved, simply navigate to the **Actions** tab in your repository and trigger the workflow, or wait for the automated CRON schedule to post your next viral hit!
