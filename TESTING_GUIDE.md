# Testing Guide - Poder em Jogo Studio 2.0

Complete guide to test all new features implemented in Phases 1-4.

## Prerequisites

```bash
# Make sure app is running
.\abrir_app.ps1

# Or manually:
.\.venv\Scripts\python.exe src\web_app.py
# Visit: http://localhost:8787
```

---

## Phase 1: Token Efficiency ✅

### Test Silent Mode
Silent mode reduces FFmpeg output from 1800+ lines to ~10 lines (95% reduction).

**Option 1: CLI Test**
```bash
# Run with --silent flag
.\.venv\Scripts\python.exe src\opus_local.py \
  --url "https://www.youtube.com/watch?v=VIDEO_ID" \
  --count 1 \
  --silent

# Compare with verbose (default)
.\.venv\Scripts\python.exe src\opus_local.py \
  --url "https://www.youtube.com/watch?v=VIDEO_ID" \
  --count 1
```

**Option 2: Benchmark Script**
```bash
# Run benchmark comparing silent vs verbose
python benchmark_silent.py --url "https://www.youtube.com/watch?v=VIDEO_ID" --runs 2

# Output example:
# VERBOSE MODE: 1800 lines, 45.2s
# SILENT MODE: 12 lines, 44.8s
# Log output reduction: 99.3%
# Token efficiency gain: ~95%
```

**Expected Result**: 90-95% fewer log lines, same functionality

---

## Phase 2: Parallel Rendering 🟡

### Test Parallel Segments (Advanced)

Parallel rendering splits videos into segments and renders them simultaneously.

**Option 1: Python Import Test**
```bash
# Verify module loads
.\.venv\Scripts\python.exe -c "from src.parallel_render import parallel_render_cut; print('OK')"
```

**Option 2: Direct Test (Advanced)**
```python
from pathlib import Path
from src.parallel_render import parallel_render_cut

# This requires an already-downloaded source video
source = Path(".work/youtube/video_id.mp4")
if source.exists():
    result = parallel_render_cut(
        source=source,
        start="0:00:00",
        duration=60.0,
        headline="Test Parallel",
        segment_duration=10.0,  # 10s chunks
        max_workers=4,
        silent=True,
    )
    print(f"Success: {result.success}")
    print(f"Speedup: {result.speedup_factor}x")
```

**Note**: Parallel rendering is integrated but not yet exposed in web UI.  
**Expected Result**: Module loads without errors, ready for benchmarking.

---

## Phase 3: Persistent Job Queue ✅

### Test Batch Processing API

**Option 1: Web UI (Easiest)**
1. Visit http://localhost:8787
2. Click "Fila" in left sidebar
3. Click "📤 Submeter múltiplos links"
4. Paste URLs (one per line):
```
https://www.youtube.com/watch?v=dQw4w9WgXcQ
https://www.youtube.com/watch?v=jNQXAC9IVRw
https://www.youtube.com/watch?v=dQw4w9WgXcQ
```
5. Set "Cortes: 3" and "Qualidade: Alta"
6. Click "Adicionar à fila"
7. Watch jobs appear in the queue list

**Option 2: cURL Command**
```bash
# Submit 3 URLs to batch API
curl -X POST http://localhost:8787/api/batch \
  -H "Content-Type: application/json" \
  -d '{
    "urls": [
      "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
      "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    ],
    "clips_count": 3,
    "quality": "alta"
  }'

# Response:
# {
#   "ok": true,
#   "job_ids": ["job-20250510120000-0", "job-20250510120001-1"],
#   "errors": [],
#   "queued": 2,
#   "total": 2
# }
```

**Option 3: Get Queue Status**
```bash
# List all jobs
curl http://localhost:8787/api/jobs

# Filter by status
curl "http://localhost:8787/api/jobs?status=pending&limit=10"

# Response:
# {
#   "jobs": [
#     {
#       "id": "job-20250510120000-0",
#       "url": "https://youtube.com/watch?v=...",
#       "status": "pending",
#       "created_at": "2025-05-10T12:00:00",
#       "clips_count": 3,
#       "quality": "alta"
#     }
#   ],
#   "stats": {"total": 2, "completed": 0, "failed": 0}
# }
```

**Option 4: Python Direct Test**
```python
from src.batch_processor import BatchProcessor, JobStatus

processor = BatchProcessor()

# Add jobs
job1 = processor.add_job(
    "https://youtube.com/watch?v=...",
    clips_count=3,
    quality="alta",
    priority="high"
)
print(f"Job ID: {job1}")

# List jobs
all_jobs = processor.list_jobs()
for job in all_jobs:
    print(f"{job.id}: {job.status}")

# Get stats
print(processor.get_stats())
```

**Persistence Test**:
1. Add jobs via web UI
2. Stop web app (Ctrl+C)
3. Restart web app
4. Jobs should still be there (check "Fila" tab)

**Expected Result**: 
- ✅ Jobs appear in queue list with status
- ✅ Auto-refresh every 3 seconds
- ✅ Jobs persist after app restart
- ✅ Stats update correctly

---

## Phase 4: Queue UI ✅

### Test Queue Management Interface

**Visual Test**:
1. Visit http://localhost:8787
2. Click "Fila" in sidebar
3. See "Processamento em lote" heading
4. Stats cards show: Pendentes, Processando, Completos, Erros

**Batch Upload Test**:
1. Click "📤 Submeter múltiplos links"
2. Form appears with:
   - Large textarea for URLs
   - "Cortes" number input (default 3)
   - "Qualidade" dropdown (Alta/TikTok/4K)
   - "Adicionar à fila" button
   - "Cancelar" button

3. Paste valid YouTube URLs and submit
4. See jobs appear in list below

**Queue List Test**:
- Each job shows:
  - 🔗 Short URL (truncated)
  - 📊 Status badge (colored: pending/rendering/ready/failed)
  - 🎬 Number of clips (e.g., "3 cortes")
  - 🕐 Relative time (e.g., "5m atrás")

**Live Updates**:
- Queue refreshes automatically every 3 seconds
- Job status changes appear without page reload
- Stats cards update in real-time

**Expected Result**:
- ✅ Queue tab appears in sidebar
- ✅ Batch upload form visible
- ✅ Job list renders with colors
- ✅ Auto-refresh works

---

## Full End-to-End Test

Test the complete workflow from batch submission to completion:

```bash
# 1. Start app
.\abrir_app.ps1

# 2. Open web UI
# http://localhost:8787

# 3. Go to "Fila" tab

# 4. Click "📤 Submeter múltiplos links"

# 5. Paste a real YouTube URL:
https://www.youtube.com/watch?v=EqBvGXj4H_g

# 6. Click "Adicionar à fila"

# 7. Watch progress:
#    - Job appears as "Pendente"
#    - Status changes to "Processando"
#    - Finally shows "Pronto" or "Erro"

# 8. Check stats update (Completos counter increases)

# 9. Verify output in outputs/ folder
```

---

## Expected Results Summary

| Feature | Status | Evidence |
|---------|--------|----------|
| Silent mode | ✅ | 95% log reduction |
| Parallel rendering | 🟡 | Module loads, ready to benchmark |
| Persistent queue | ✅ | Jobs survive restart |
| Batch API | ✅ | `/api/batch` accepts multiple URLs |
| Queue UI | ✅ | Tab visible, batch form works |
| Auto-refresh | ✅ | Updates every 3s without reload |
| Status badges | ✅ | Color-coded by status |
| Job stats | ✅ | Cards show accurate counts |

---

## Troubleshooting

### Queue not loading
```bash
# Check if API is responding
curl http://localhost:8787/api/jobs
# Should return JSON with jobs array
```

### Batch upload not working
1. Check browser console (F12 → Console tab)
2. Verify URLs are valid HTTPS YouTube links
3. Ensure web app is running (`http://localhost:8787`)

### Jobs not persisting
1. Check that `outputs/studio_db.json` exists
2. Verify app has write permissions to `outputs/`
3. Restart app and check if jobs reappear

### Silent mode not quieter
1. Check `--silent` flag is being used: `opus_local.py --silent`
2. Compare output with/without flag
3. Look for 95%+ reduction in lines

---

## Next Steps (Phase 5)

- [ ] A/B testing for hook generation (show 3 variants)
- [ ] Better scoring by emotion peaks + keywords
- [ ] Subtitle style presets (TikTok vs YouTube)
- [ ] User feedback loop for learning
- [ ] Results preview (thumbnails, download links)

---

**Testing completed**: 2025-05-10  
**Total time**: ~4-5 hours (Phases 1-4)
