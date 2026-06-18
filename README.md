# ⚽ Fully Autonomous Football Shorts Pipeline

A fully automated, AI-driven pipeline that generates, edits, and uploads high-quality Football YouTube Shorts every single day via GitHub Actions.

## ✨ Features & Architecture

This pipeline is powered by a chain of advanced AI models working together seamlessly:

1. **AI Scriptwriting & Topic Selection (Gemini)**
   - Uses the `google-genai` SDK and the `gemini-2.5-flash` model.
   - Specifically prompted to act like a 10M-subscriber YouTuber to find the most viral, trending football topics of the day.

2. **Expressive Voiceover Generation (Chatterbox TTS)**
   - Replaced legacy robotic voices with `chatterbox-tts`, a massive, locally-run PyTorch AI model developed by Resemble AI.
   - Generates highly expressive, human-sounding narration directly on the GitHub Actions CPU.

3. **Intelligent Asset Sourcing**
   - **Google Custom Search API:** Dynamically searches the web for high-resolution images of specific football players mentioned in the script.
   - **Pexels API Fallback:** If the script calls for generic footage or Google ratelimits/fails, it automatically falls back to downloading 4K stock video/images from Pexels.

4. **3D Parallax Visual Engine (`rembg`)**
   - Implements a "Ken Burns 2.0" documentary-style effect.
   - Uses `rembg` (U2-Net) to instantly cut out the foreground subject (e.g., Lionel Messi) from the background.
   - Applies a Gaussian blur to the background, zooming it backwards, while zooming the sharp cutout player forwards to create a powerful illusion of 3D depth.

5. **Perfect Subtitle Synchronization (Whisper AI)**
   - Uses OpenAI's `whisper-timestamped` model as a forced-aligner.
   - Listens to the generated Chatterbox audio and extracts the exact start and end millisecond of every spoken word.
   - Feeds this data into `moviepy` to generate perfectly synced, "MrBeast-style" pop-in animations.

6. **100% Cloud Automated CI/CD**
   - Runs on a CRON schedule inside **GitHub Actions**.
   - Implements aggressive caching (`~/.cache/huggingface/hub` and `~/.cache/whisper`) so massive AI models are only downloaded once, keeping the pipeline completely free and bypassing bandwidth limits.

---

## 🚀 Setup Instructions

Because this runs entirely on GitHub Actions, you do not need to install anything on your local computer. However, you must provide the following API keys as **Repository Secrets** (`Settings > Secrets and variables > Actions`):

* `YOUTUBE_API_KEY` - To query YouTube trending data.
* `GEMINI_API_KEY` - To write the script.
* `PEXELS_API_KEY` - For the stock footage fallback.
* `GOOGLE_SEARCH_API_KEY` - For specific image sourcing.
* `GOOGLE_SEARCH_ENGINE_ID` - The custom search engine (set to search the entire web, Image Search ON).
* `YOUTUBE_CLIENT_SECRETS_FILE` - (OAuth) For uploading the final video.
* `YOUTUBE_TOKEN_FILE` - (OAuth) For uploading the final video.

---

## 📅 Development Timeline & Changelog

* **Initial Setup:** Built the core MoviePy pipeline using Microsoft `edge-tts` and generic stock footage.
* **The "Real Creator" Update:** Altered the Gemini prompt to aggressively target viral topics and speak with higher energy.
* **The 3D Parallax Update:** Replaced static stock videos with dynamic 3D scenes. Integrated `rembg` AI to slice foreground subjects from backgrounds and animate them independently.
* **The Chatterbox Upgrade:** Ripped out the robotic `edge-tts` engine and installed the massive `chatterbox-tts` PyTorch model for ultra-realistic voice generation.
* **The Whisper Alignment Update:** Added OpenAI's `whisper-timestamped` to act as a stopwatch, perfectly mapping word boundaries to restore the MrBeast-style pop-in subtitles that broke when Edge TTS was removed.
* **The Google Search Migration:** Replaced the unstable DuckDuckGo scraper (which was throwing `403 Ratelimits` on GitHub Actions) with the official Google Custom Search API to guarantee high-quality player images.
