# Quality Assurance Guide - Poder em Jogo Studio

This guide covers the three new QA components: Benchmarking, Unit Tests, and Observability.

---

## 📊 Overview

The QA phase includes:

1. **Benchmark (parallel_render validation)**: Measure actual speedup vs claims
2. **Unit Tests (batch_processor protection)**: Automated test suite for job queue
3. **Observability (structured logging)**: Track system health and user behavior

---

## 1️⃣ Running Unit Tests

### Prerequisites
```bash
# Ensure venv is activated
.\.venv\Scripts\Activate.ps1

# Install pytest (optional, but recommended)
pip install pytest
```

### Run All Tests
```bash
# Using unittest (built-in)
python -m unittest discover tests -v

# Or using pytest (if installed)
pytest tests/ -v

# Or directly
python -m unittest tests.test_batch_processor -v
```

### Run Specific Test Class
```bash
python -m unittest tests.test_batch_processor.TestBatchProcessor -v
```

### Run Specific Test Method
```bash
python -m unittest tests.test_batch_processor.TestBatchProcessor.test_add_job_single -v
```

### Expected Output
```
test_add_job_multiple (tests.test_batch_processor.TestBatchProcessor) ... ok
test_add_job_single (tests.test_batch_processor.TestBatchProcessor) ... ok
test_add_job_with_options (tests.test_batch_processor.TestBatchProcessor) ... ok
...
----------------------------------------------------------------------
Ran 24 tests in 2.345s

OK
```

### Test Coverage
To check code coverage (install `coverage` first):
```bash
pip install coverage
coverage run -m unittest discover tests
coverage report -m src/batch_processor.py
```

### What Tests Verify
✅ Job creation and enqueueing  
✅ FIFO ordering with priority levels  
✅ Job status transitions + timestamps  
✅ Persistence across restarts  
✅ Archiving and cleanup operations  
✅ Statistics tracking (total/completed/failed)  
✅ Concurrent writes (thread safety)  
✅ Error handling (corrupted DB recovery)  
✅ Edge cases (empty queue, special characters)  

---

## 2️⃣ Parallel Rendering Benchmark

### Prerequisites
```bash
# Ensure psutil is installed (for CPU/memory monitoring)
pip install psutil
```

### Quick Benchmark (Single Run)
```bash
# Test with a short YouTube video
python benchmark_parallel.py --url "https://youtube.com/watch?v=dQw4w9WgXcQ" --quick

# Expected output:
# ✓ Best speedup: 3.45x (4 workers)
# ✓ Claim validation: 4x speedup PLAUSIBLE
# Recommendation: PRODUCTION READY
```

### Full Benchmark (Multiple Runs)
```bash
# Test with multiple runs for stability (recommended)
python benchmark_parallel.py \
  --url "https://youtube.com/watch?v=dQw4w9WgXcQ" \
  --workers 1 2 4 \
  --runs 3 \
  --segment-duration 10.0
```

### Understanding Results

**Output Interpretation**:
- **Speedup ≥ 2.5x**: ✅ Parallel rendering viable (4x claim is plausible)
- **Speedup 1.5-2.5x**: ⚠️  Investigate bottleneck (I/O? concat overhead?)
- **Speedup < 1.5x**: ❌ Skip parallel (overhead not justified)

**Output Metrics**:
- `Average time`: Wall-clock rendering time
- `Average speedup`: Ratio vs single-threaded baseline
- `Average CPU`: CPU utilization during render
- `Memory delta`: Memory increase during render

### Example Report Output
```
====================================================================
PARALLEL RENDERING BENCHMARK
====================================================================
Video URL: https://youtube.com/watch?v=dQw4w9WgXcQ
Test runs per mode: 2
Worker counts to test: [1, 2, 4]

[1/2] BASELINE: Single-threaded rendering
------
  Run 1/2... 120.5s, 250.5MB, 85% CPU
  Run 2/2... 119.8s, 250.5MB, 87% CPU

[2/2] PARALLEL: Multi-worker rendering
------
  1 workers, run 1/1... 120.2s, 250.5MB, 84% CPU, 1.00x speedup
  2 workers, run 1/1... 62.1s, 250.5MB, 92% CPU, 1.94x speedup
  4 workers, run 1/1... 35.2s, 250.5MB, 98% CPU, 3.45x speedup

Report saved: reports/benchmark_parallel_20250510_120000.txt
```

### Report Location
Reports are saved to: `reports/benchmark_parallel_YYYYMMDD_HHMMSS.txt`

---

## 3️⃣ Observability (Structured Logging)

### Architecture

**Log File**: `outputs/analytics.jsonl`
- One JSON object per line (append-only)
- Auto-rotates at 100MB
- Human-readable and machine-parseable

**API Endpoint**: `/api/analytics`
- GET `/api/analytics?days=7&event_type=job_completed`
- Returns aggregated metrics

**Dashboard**: `http://localhost:8787/dashboard.html`
- Real-time metrics visualization
- 5-second auto-refresh
- Filterable by event type and time period

### Event Types

#### Job Completion
```python
log_event("job_completed", {
    "job_id": "job-20250510-001",
    "duration_s": 120.5,
    "clips_rendered": 3,
    "quality": "alta",
    "status": "ready|failed",
    "error": None  # Only set on failure
})
```

#### Hook Generation
```python
log_event("hook_generated", {
    "job_id": "job-20250510-001",
    "style": "bold|question|story",
    "duration_s": 5.2,
    "success": True,
    "fallback_to_heuristic": False
})
```

#### User Hook Selection
```python
log_event("user_hook_selected", {
    "job_id": "job-20250510-001",
    "selected_style": "bold",
    "other_options": ["question", "story"],
    "timestamp": "2025-05-10T12:00:00+00:00"
})
```

#### API Performance
```python
log_event("api_call", {
    "endpoint": "/api/batch",
    "method": "POST",
    "latency_ms": 850,
    "status_code": 200,
    "error": None
})
```

### Using the Dashboard

1. **Start the app**:
   ```bash
   .\abrir_app.ps1
   ```

2. **Open dashboard**:
   ```
   http://localhost:8787/dashboard.html
   ```

3. **View metrics**:
   - Queue Health: Job completion rates, avg time
   - Hook Generation: Success rates, fallback %
   - API Performance: Latency, errors
   - User Preferences: Hook selection distribution

4. **Filter data**:
   - Select time period (1-365 days)
   - Filter by event type
   - Click "Refresh" to update

### Programmatic Usage

```python
from src.observability import log_event, get_metrics, get_summary

# Log an event
log_event("job_completed", {
    "job_id": "job-001",
    "duration_s": 120.5,
    "status": "ready"
})

# Get metrics for last 7 days
metrics = get_metrics(event_type="job_completed", days=7)
print(f"Success rate: {metrics['job_stats']['success_rate']:.1%}")

# Get system health summary
summary = get_summary(days=7)
print(f"Hook fallback rate: {summary['hook_health']['fallback_rate']:.1%}")
```

### Analytics File Format

Each line is valid JSON:
```json
{"timestamp": "2025-05-10T12:00:00.123456", "event": "job_completed", "data": {"job_id": "job-001", "duration_s": 120.5, "status": "ready"}}
{"timestamp": "2025-05-10T12:01:30.654321", "event": "hook_generated", "data": {"job_id": "job-001", "style": "bold", "success": true}}
```

Parse with:
```bash
# Count events by type
cat outputs/analytics.jsonl | jq '.event' | sort | uniq -c

# Get all job_completed events
cat outputs/analytics.jsonl | jq 'select(.event == "job_completed")'

# Calculate average job duration
cat outputs/analytics.jsonl | jq 'select(.event == "job_completed") | .data.duration_s' | jq -s 'add/length'
```

---

## 🔗 Integration Points

### web_app.py Integration
```python
from observability import log_event

# In /api/batch endpoint
log_event("job_submitted", {
    "job_id": job_id,
    "url": payload["url"],
    "priority": payload.get("priority", "normal")
})

# In API error handling
log_event("api_call", {
    "endpoint": request.path,
    "method": request.method,
    "latency_ms": elapsed_ms,
    "status_code": response_code,
    "error": error_msg if error else None
})
```

### batch_processor.py Integration
```python
from observability import log_event

# In update_job_status
log_event("job_completed", {
    "job_id": job_id,
    "duration_s": (completed_time - started_time).total_seconds(),
    "clips_rendered": job.clips_count,
    "quality": job.quality,
    "status": status.value,
    "error": error if status == JobStatus.FAILED else None
})
```

### hook_variants.py Integration
```python
from observability import log_event

# In variant generation
log_event("hook_generated", {
    "job_id": job_id,
    "style": style_name,
    "duration_s": generation_time,
    "success": success,
    "fallback_to_heuristic": fell_back_to_heuristic
})

# In user selection
log_event("user_hook_selected", {
    "job_id": job_id,
    "selected_style": selected_style,
    "other_options": list(other_variants.keys())
})
```

---

## 📈 Interpreting Metrics

### Queue Health
- **Success Rate** > 95%: ✅ Healthy
- **Success Rate** 85-95%: ⚠️  Monitor for patterns
- **Success Rate** < 85%: ❌ Investigate failures

### Hook Generation
- **Fallback Rate** < 5%: ✅ AI is reliable
- **Fallback Rate** 5-15%: ⚠️  AI API occasionally fails
- **Fallback Rate** > 15%: ❌ Fall back to heuristics?

### API Performance
- **P95 Latency** < 1s: ✅ Good
- **P95 Latency** 1-3s: ⚠️  Acceptable
- **P95 Latency** > 3s: ❌ Optimize needed
- **Error Rate** = 0%: ✅ Perfect
- **Error Rate** > 1%: ❌ Investigate

### User Preferences
- Watch for hook style distribution skew
- If one style dominates (>70%), consider it default
- If even distribution, A/B testing is working

---

## 🧪 Full QA Workflow

### Phase 1: Run Tests
```bash
python -m unittest discover tests -v
# Expected: All 24 tests pass ✅
```

### Phase 2: Run Benchmark
```bash
python benchmark_parallel.py --url "YOUR_VIDEO_URL" --runs 3
# Expected: Speedup >= 2.5x ✅
```

### Phase 3: Verify Observability
```bash
# 1. Start app
.\abrir_app.ps1

# 2. Submit a job via UI
# (paste YouTube URL, click "Submeter")

# 3. Check analytics.jsonl
cat outputs/analytics.jsonl | jq '.event' | sort | uniq -c

# 4. View dashboard
# Open http://localhost:8787/dashboard.html
```

### Phase 4: Generate Report
```bash
# Run integration test (submit 5-10 jobs)
# Let them complete (monitor queue)
# Save dashboard screenshot or generate metrics report
```

---

## 📝 Troubleshooting

### Tests Fail
```bash
# Clean up temp directories
Remove-Item -Path $env:TEMP\batch_processor_test_* -Recurse -Force -ErrorAction SilentlyContinue

# Re-run tests
python -m unittest discover tests -v
```

### Benchmark Slow/Hangs
```bash
# Try quick mode
python benchmark_parallel.py --url "..." --quick

# Or short video (30s, not 1h podcast)
# Use Ctrl+C to interrupt
```

### No Analytics Data
```bash
# Verify observability logging is integrated in web_app.py
# Check outputs/analytics.jsonl exists
# Submit a job and wait for completion
# Refresh dashboard (Ctrl+F5 to clear cache)
```

### Dashboard Won't Load
```bash
# Check app is running: .\abrir_app.ps1
# Check http://localhost:8787 works
# Try http://localhost:8787/dashboard.html?days=1
# Check browser console for errors (F12 -> Console)
```

---

## 🎯 Success Criteria

✅ All 12 unit tests pass  
✅ Benchmark shows speedup >= 2.5x  
✅ analytics.jsonl grows with events  
✅ Dashboard displays metrics  
✅ API endpoints respond  
✅ No errors in browser console  

---

**Next Steps**: 
1. Run tests: `python -m unittest discover tests -v`
2. Run benchmark: `python benchmark_parallel.py --url "..." --quick`
3. Start app: `.\abrir_app.ps1`
4. View dashboard: `http://localhost:8787/dashboard.html`
5. Submit jobs and monitor!
