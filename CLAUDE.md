# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

**Poder em Jogo Studio** — a local OpusClip-style automation tool that downloads YouTube podcasts, finds viral moments using transcript + media signals, renders vertical 9:16 TikTok clips, and manages posting. Everything runs on the local machine; no cloud infra required (OpenAI API is optional).

## Running the App

```powershell
# First-time setup
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# Start the web studio (port 8787)
.\abrir_app.ps1
# or directly:
.\.venv\Scripts\python.exe src\web_app.py

# Generate cuts from CLI (bypasses UI)
.\.venv\Scripts\python.exe src\opus_local.py --url "https://youtube.com/watch?v=..." --count 3 --quality alta

# Preview candidates without rendering
.\.venv\Scripts\python.exe src\opus_local.py --url "..." --preview-only --no-media-score

# Render a specific candidate by rank
.\.venv\Scripts\python.exe src\render_candidate.py --url "..." --rank 1

# Batch from topics.txt
.\run_batch.ps1
```

The studio UI runs at `http://localhost:8787`.

## SaaS / Mobile Migration

There is now a separate SaaS/mobile prototype that should be treated as the path toward a web app and future App Store product.

Run it with:

```powershell
.\Abrir Poder em Jogo API.bat
# or:
.\.venv\Scripts\python.exe -m saas.app.server
```

Local URLs:

- Mobile web app: `http://127.0.0.1:8790/`
- API health: `http://127.0.0.1:8790/health`
- Cuts API: `http://127.0.0.1:8790/v1/cortes`

Important paths:

| Path | Purpose |
|---|---|
| `saas/app/server.py` | Dependency-free HTTP API for the SaaS/mobile prototype |
| `saas/app/db.py` | SQLite processing persistence |
| `saas/app/worker.py` | Background worker that calls `src/opus_local.py` |
| `saas/mobile/` | Mobile-first web UI consuming the SaaS API |
| `outputs/saas/studio.db` | Local SaaS processing database |
| `APP_STORE_MIGRATION.md` | Migration plan toward cloud/App Store |

Design rule: do not make the iPhone render video. Mobile/iOS should be the interface; rendering stays in backend/worker.
User-facing wording rule: use "corte" or "processamento", not "job". `/v1/jobs` remains only as a backward-compatible technical alias; new UI should use `/v1/cortes`.

## Architecture

### Request Flow (UI → Server → Pipeline)

```
Browser (web/) → ThreadingHTTPServer :8787 (src/web_app.py)
    POST /api/run  → enqueues payload → worker thread → opus_local.py (subprocess)
    POST /api/render → render_candidate.py (subprocess)
    GET  /api/state → returns live {running, progress, stage, log[]}
```

`web_app.py` runs a background worker thread (`process_queue`) that pops jobs from `state["queue"]` and calls `run_command()` which pipes stdout line-by-line through `progress_from_line()` to update the shared `state` dict (protected by `state_lock`). The UI polls `/api/state` every ~2 seconds.

### Pipeline Stages (opus_local.py)

```
1/5  Download source video         → youtube_to_cut.download_youtube()
                                     stores in .work/youtube/
2/5  Download transcription        → yt-dlp subtitles or Whisper
3/5  Score candidates              → find_viral_moments.find_candidates()
     (optional) 3.5/5 AI editorial → editorial_judge.py (OpenAI GPT)
4/5  Render chosen clips           → create_cut_from_source.create_cut()
                                     + face_focus.py (OpenCV tracking)
                                     + silence_cutter.py
                                     + quality_control.py (validation)
5/5  Save index + posting package  → outputs/_postar_agora/
```

Progress is communicated entirely via stdout keywords (`"1/5"`, `"2/5"`, `"[download] X%"`, `"frame="` from FFmpeg) parsed in `progress_from_line()`.

### Section Download Fallback

`youtube_to_cut.download_youtube_section()` tries 4 yt-dlp strategies to download only the clip section. If all fail (rate-limit, throttle), it falls back to cutting from the already-downloaded full video in `.work/youtube/` using FFmpeg `-ss` + `-t`. This avoids re-download errors after large podcast downloads.

### Key Paths

| Path | Purpose |
|---|---|
| `.work/youtube/` | Full downloaded source videos (reused by fallback) |
| `.work/youtube_sections/` | Downloaded section clips pre-render |
| `outputs/_postar_agora/` | Latest approved clip + `publicacao.txt` |
| `outputs/relatorios/pre-aprovacao/` | JSON + frames for UI preview |
| `config/perfil_canal.json` | Channel branding, editorial angle, preferred topics |
| `config/radar_sources.json` | YouTube channels monitored for auto-cut |
| `outputs/studio_db.json` | Job history |
| `outputs/tiktok-analytics/` | Performance metrics (analytics.csv feeds learning) |

### Campaign System (web/app.js)

The UI has a campaign mode selector. `activeCampaign` drives which Keoto monetization campaign is active. Each campaign in `CAMPAIGNS` has `tags[]` and `keotoUrl`. Currently configured:
- `poderemjogo` — own channel, no Keoto
- `fernando` — Keoto campaign "Fernando e Eduardo" (R$3/1k views, `#keotoclipes`)

### Scoring Logic

`find_viral_moments.py` scores transcript segments using:
- Hook strength (opening words)
- Emotion/conflict density
- Duration fit (configurable min/max seconds)
- Channel history learning (from `tiktok_learning.py`)
- Optional media signals: motion, silence gaps, face presence

Score ≥ `--min-score` (default 70) required. Candidates are ranked; top N are rendered.

## HTTP API Reference

All endpoints on `http://127.0.0.1:8787`.

**GET:** `/api/state`, `/api/candidates`, `/api/videos`, `/api/posting-plan`, `/api/learning`, `/api/history`, `/api/radar?kind=podcast|shorts`, `/api/tiktok-status`, `/api/asset?path=...`, `/api/open?path=...`

**POST:** `/api/run` (enqueue job), `/api/render` (render candidate by rank), `/api/candidate-preview`, `/api/save-publication`, `/api/analytics` (log metrics), `/api/tiktok` (open TikTok Studio), `/api/tiktok-setup`, `/api/upload-tiktok`, `/api/radar/source` (add channel), `/api/radar/scan`, `/api/radar/process`, `/api/radar/analyze`

## SaaS / Mobile Prototype

Run with `.\abrir_saas_dev.ps1` or `.\.venv\Scripts\python.exe -m saas.app.server`.

Base URL: `http://127.0.0.1:8790`.

Current routes:

- `GET /`: mobile-first app.
- `GET /health`: API health.
- `POST /v1/cortes`: start a cut processing request.
- `GET /v1/cortes`: list processing requests.
- `GET /v1/cortes/{id}`: get one processing request.
- `POST /v1/cortes/{id}/cancelar`: cancel a queued or running processing request.
- `GET /v1/cortes-prontos`: list rendered MP4s from `outputs`.
- `GET /v1/arquivo?path=...`: serve safe MP4/TXT/JSON files under `outputs`; MP4 supports Range playback.

User-facing text in this app should say `corte` or `processamento`, not `job`.

When a SaaS processing request completes, `saas/app/worker.py` stores `result.posting_pack`, `result.index`, and `result.videos`. `saas/app/server.py` enriches `/v1/cortes` and `/v1/cortes/{id}` with `ready_cuts` when the posting package is available.

## Environment

Optional `.env` keys:
- `OPENAI_API_KEY` — enables GPT editorial judging (`--editorial-ai auto|required`)

If absent, editorial scoring falls back to heuristic-only mode.

## FFmpeg / Quality

Three render profiles (`--quality`):
- `tiktok` — 1080x1920, fast
- `alta` — 1440x2560 (default)
- `4k` — 2160x3840, slow

FFmpeg is bundled via `imageio-ffmpeg`; no system install needed.

## Important Behaviors

- **Section download threshold** — accepts clips ≥80% of expected duration (YouTube keyframe imprecision). See `youtube_to_cut.py:185`.
- **Progress parsing** — all pipeline progress is inferred from stdout. If a subprocess emits nothing for 30+ seconds, the UI shows a hint message instead of the stale stage label.
- **State is in-memory** — restarting `web_app.py` resets all running state. Job history persists in `studio_db.json`.
- **Thread safety** — all writes to `state` dict must use `state_lock`. `append_log()` is the safe helper.
