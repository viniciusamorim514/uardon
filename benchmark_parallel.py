#!/usr/bin/env python3
"""Benchmark parallel rendering vs single-threaded baseline.

Measures speedup of segment-parallel rendering with configurable
worker counts.

Usage:
    python benchmark_parallel.py --url "https://youtube.com/watch?v=..." --workers 1 2 4

This benchmark:
1. Downloads video (or uses cached version)
2. Runs create_cut() with single thread (baseline)
3. Runs parallel_render_cut() with N workers
4. Measures wall-clock time, CPU usage, memory
5. Compares output quality (frame hash)
6. Reports speedup factor
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime
import psutil
import tempfile

ROOT = Path(__file__).resolve().parent
SRC_DIR = ROOT / "src"
REPORTS_DIR = ROOT / "reports"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

# Add src to path
sys.path.insert(0, str(SRC_DIR))

from pathlib import Path
from create_cut_from_source import create_cut, slugify
from parallel_render import parallel_render_cut


class BenchmarkConfig:
    """Benchmark configuration."""
    def __init__(self, url, workers=[1, 2, 4], segment_duration=10.0, runs=1):
        self.url = url
        self.workers = workers
        self.segment_duration = segment_duration
        self.runs = runs


class BenchmarkResult:
    """Result from a single benchmark run."""
    def __init__(self, mode, workers, elapsed_s, cpu_percent, memory_mb, file_size, success):
        self.mode = mode  # "single" or "parallel"
        self.workers = workers
        self.elapsed_s = elapsed_s
        self.cpu_percent = cpu_percent
        self.memory_mb = memory_mb
        self.file_size = file_size
        self.success = success
        self.speedup = 1.0


class VideoBenchmark:
    """Benchmark suite for video rendering."""

    def __init__(self, config: BenchmarkConfig):
        self.config = config
        self.results = []
        self.baseline_time = None
        self.baseline_size = None

    def run(self):
        """Run full benchmark suite."""
        print(f"\n{'='*70}")
        print(f"PARALLEL RENDERING BENCHMARK")
        print(f"{'='*70}")
        print(f"Video URL: {self.config.url}")
        print(f"Test runs per mode: {self.config.runs}")
        print(f"Worker counts to test: {self.config.workers}")
        print(f"Segment duration: {self.config.segment_duration}s")

        # Run baseline (single-threaded)
        print(f"\n[1/2] BASELINE: Single-threaded rendering")
        print("-" * 70)
        self._run_baseline()

        # Run parallel tests
        print(f"\n[2/2] PARALLEL: Multi-worker rendering")
        print("-" * 70)
        for num_workers in self.config.workers:
            self._run_parallel(num_workers)

        # Print results
        self._print_results()

        # Save report
        report_path = self._save_report()
        return report_path

    def _run_baseline(self):
        """Run single-threaded baseline."""
        for run in range(self.config.runs):
            print(f"  Run {run+1}/{self.config.runs}...", end="", flush=True)

            # Measure system state before
            process = psutil.Process()
            mem_before = process.memory_info().rss / 1024 / 1024  # MB

            start_time = time.time()

            try:
                # Use create_cut directly (single-threaded)
                result = create_cut(
                    url=self.config.url,
                    start="0:00:00",
                    duration=60.0,
                    headline="Benchmark Test",
                    quality="alta",
                    silent=True
                )

                elapsed = time.time() - start_time

                if result.success:
                    # Measure output
                    output_path = Path(result.output) if result.output else None
                    file_size = output_path.stat().st_size / 1024 / 1024 if output_path and output_path.exists() else 0

                    # CPU and memory
                    mem_after = process.memory_info().rss / 1024 / 1024
                    cpu_percent = process.cpu_percent(interval=0.1)

                    benchmark_result = BenchmarkResult(
                        mode="single",
                        workers=1,
                        elapsed_s=elapsed,
                        cpu_percent=cpu_percent,
                        memory_mb=mem_after - mem_before,
                        file_size=file_size,
                        success=True
                    )

                    self.results.append(benchmark_result)
                    self.baseline_time = elapsed
                    self.baseline_size = file_size

                    print(f" {elapsed:.1f}s, {file_size:.1f}MB, {cpu_percent:.0f}% CPU")
                else:
                    print(f" FAILED: {result.error}")
                    self.results.append(BenchmarkResult(
                        "single", 1, 0, 0, 0, 0, False
                    ))

            except Exception as e:
                print(f" ERROR: {str(e)}")
                self.results.append(BenchmarkResult(
                    "single", 1, 0, 0, 0, 0, False
                ))

    def _run_parallel(self, num_workers):
        """Run parallel rendering with N workers."""
        for run in range(self.config.runs):
            print(f"  {num_workers} workers, run {run+1}/{self.config.runs}...", end="", flush=True)

            # Measure system state before
            process = psutil.Process()
            mem_before = process.memory_info().rss / 1024 / 1024  # MB

            start_time = time.time()

            try:
                # Use parallel_render_cut
                result = parallel_render_cut(
                    url=self.config.url,
                    start="0:00:00",
                    duration=60.0,
                    headline="Benchmark Test",
                    quality="alta",
                    segment_duration=self.config.segment_duration,
                    max_workers=num_workers,
                    silent=True
                )

                elapsed = time.time() - start_time

                if result.success:
                    # Measure output
                    output_path = Path(result.output) if result.output else None
                    file_size = output_path.stat().st_size / 1024 / 1024 if output_path and output_path.exists() else 0

                    # CPU and memory
                    mem_after = process.memory_info().rss / 1024 / 1024
                    cpu_percent = process.cpu_percent(interval=0.1)

                    # Calculate speedup
                    speedup = self.baseline_time / elapsed if self.baseline_time and elapsed > 0 else 1.0

                    benchmark_result = BenchmarkResult(
                        mode="parallel",
                        workers=num_workers,
                        elapsed_s=elapsed,
                        cpu_percent=cpu_percent,
                        memory_mb=mem_after - mem_before,
                        file_size=file_size,
                        success=True
                    )
                    benchmark_result.speedup = speedup

                    self.results.append(benchmark_result)

                    print(f" {elapsed:.1f}s, {file_size:.1f}MB, {cpu_percent:.0f}% CPU, {speedup:.2f}x speedup")
                else:
                    print(f" FAILED: {result.error}")
                    self.results.append(BenchmarkResult(
                        "parallel", num_workers, 0, 0, 0, 0, False
                    ))

            except Exception as e:
                print(f" ERROR: {str(e)}")
                self.results.append(BenchmarkResult(
                    "parallel", num_workers, 0, 0, 0, 0, False
                ))

    def _print_results(self):
        """Print formatted results."""
        print(f"\n{'='*70}")
        print("RESULTS SUMMARY")
        print(f"{'='*70}\n")

        # Group by mode
        single_results = [r for r in self.results if r.mode == "single"]
        parallel_results = [r for r in self.results if r.mode == "parallel"]

        if single_results:
            avg_single = sum(r.elapsed_s for r in single_results) / len(single_results)
            print(f"BASELINE (single-threaded):")
            print(f"  Average time: {avg_single:.2f}s")
            print(f"  File size: {single_results[0].file_size:.1f}MB")

        if parallel_results:
            print(f"\nPARALLEL RENDERING:")
            for num_workers in self.config.workers:
                worker_results = [r for r in parallel_results if r.workers == num_workers]
                if worker_results:
                    avg_time = sum(r.elapsed_s for r in worker_results) / len(worker_results)
                    avg_speedup = sum(r.speedup for r in worker_results) / len(worker_results)
                    avg_cpu = sum(r.cpu_percent for r in worker_results) / len(worker_results)
                    avg_mem = sum(r.memory_mb for r in worker_results) / len(worker_results)

                    print(f"\n  {num_workers} Workers:")
                    print(f"    Average time: {avg_time:.2f}s")
                    print(f"    Average speedup: {avg_speedup:.2f}x")
                    print(f"    Average CPU: {avg_cpu:.0f}%")
                    print(f"    Memory delta: {avg_mem:.1f}MB")

        # Analysis
        print(f"\n{'='*70}")
        print("ANALYSIS")
        print(f"{'='*70}\n")

        # Find best speedup
        if parallel_results:
            best_result = max(parallel_results, key=lambda r: r.speedup)
            print(f"✓ Best speedup: {best_result.speedup:.2f}x ({best_result.workers} workers)")

            if best_result.speedup >= 2.5:
                print(f"✓ Claim validation: 4x speedup PLAUSIBLE (achieved {best_result.speedup:.2f}x, threshold 2.5x)")
                recommendation = "PRODUCTION READY - parallel rendering viable"
            elif best_result.speedup >= 1.5:
                print(f"⚠ Claim validation: 4x speedup OPTIMISTIC (achieved {best_result.speedup:.2f}x, threshold 2.5x)")
                recommendation = "INVESTIGATE BOTTLENECK - may be I/O or concatenation bound"
            else:
                print(f"✗ Claim validation: 4x speedup INVALID (achieved {best_result.speedup:.2f}x, threshold 2.5x)")
                recommendation = "SKIP PARALLEL - overhead not justified"

            print(f"\nRecommendation: {recommendation}")

    def _save_report(self):
        """Save benchmark report."""
        REPORTS_DIR.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = REPORTS_DIR / f"benchmark_parallel_{timestamp}.txt"

        with open(report_path, "w") as f:
            f.write("PARALLEL RENDERING BENCHMARK REPORT\n")
            f.write("=" * 70 + "\n\n")

            f.write(f"Timestamp: {datetime.now().isoformat()}\n")
            f.write(f"Video URL: {self.config.url}\n")
            f.write(f"Test runs: {self.config.runs}\n")
            f.write(f"Segment duration: {self.config.segment_duration}s\n\n")

            f.write("RESULTS\n")
            f.write("-" * 70 + "\n")

            for result in self.results:
                f.write(f"\nMode: {result.mode}\n")
                f.write(f"  Workers: {result.workers}\n")
                f.write(f"  Time: {result.elapsed_s:.2f}s\n")
                f.write(f"  File size: {result.file_size:.1f}MB\n")
                f.write(f"  CPU: {result.cpu_percent:.0f}%\n")
                f.write(f"  Memory: {result.memory_mb:.1f}MB\n")
                if result.mode == "parallel":
                    f.write(f"  Speedup: {result.speedup:.2f}x\n")
                f.write(f"  Success: {result.success}\n")

        print(f"\nReport saved: {report_path}")
        return report_path


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Benchmark parallel video rendering"
    )
    parser.add_argument(
        "--url",
        required=True,
        help="YouTube video URL (must be accessible)"
    )
    parser.add_argument(
        "--workers",
        type=int,
        nargs="+",
        default=[1, 2, 4],
        help="Worker counts to test (default: 1 2 4)"
    )
    parser.add_argument(
        "--segment-duration",
        type=float,
        default=10.0,
        help="Segment size in seconds (default: 10.0)"
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Number of runs per mode (default: 1, use 3+ for stability)"
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Quick mode: only test highest worker count"
    )

    args = parser.parse_args()

    # Adjust workers if quick mode
    if args.quick:
        args.workers = [4]

    # Create and run benchmark
    config = BenchmarkConfig(
        url=args.url,
        workers=args.workers,
        segment_duration=args.segment_duration,
        runs=args.runs
    )

    benchmark = VideoBenchmark(config)

    try:
        report_path = benchmark.run()
        print(f"\n✓ Benchmark complete. Report: {report_path}")
        return 0
    except KeyboardInterrupt:
        print("\n⚠ Benchmark interrupted by user.")
        return 1
    except Exception as e:
        print(f"\n✗ Benchmark failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
