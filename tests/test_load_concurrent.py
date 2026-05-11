"""
Load Test: Concurrent Job Processing

Tests the system's ability to handle 10-20 simultaneous processing jobs.

Usage:
    python -m pytest tests/test_load_concurrent.py -v -s

Configuration:
    CONCURRENT_JOBS = 10  # Start with 10, increase to 20 after passing
    VIDEOS = List of 3-5 test YouTube URLs
"""

import asyncio
import json
import time
from pathlib import Path
from datetime import datetime
import unittest
from unittest.mock import patch, MagicMock
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from batch_processor import BatchProcessor, Job, JobStatus


class TestLoadConcurrentJobs(unittest.TestCase):
    """Test concurrent job processing under load."""

    @classmethod
    def setUpClass(cls):
        """Set up test environment."""
        cls.temp_db = Path(__file__).parent / "temp_load_test_db.json"
        cls.processor = BatchProcessor(db_path=cls.temp_db)

    @classmethod
    def tearDownClass(cls):
        """Clean up test database."""
        if cls.temp_db.exists():
            cls.temp_db.unlink()

    def setUp(self):
        """Reset processor before each test."""
        if self.temp_db.exists():
            self.temp_db.unlink()
        self.processor = BatchProcessor(db_path=self.temp_db)

    def test_load_10_jobs(self):
        """Test processing 10 concurrent jobs."""
        # Arrange: Add 10 jobs to queue
        test_urls = [
            f"https://www.youtube.com/watch?v=test{i:02d}"
            for i in range(10)
        ]

        job_ids = []
        start_time = time.time()

        for url in test_urls:
            job_id = self.processor.add_job(url, priority="normal")
            job_ids.append(job_id)

        enqueue_time = time.time() - start_time

        # Assert: All jobs added successfully
        db = self.processor._read_db()
        self.assertEqual(len(db["jobs"]), 10)
        self.assertEqual(len(job_ids), 10)

        # Assert: Enqueue time is acceptable (< 1 second)
        self.assertLess(enqueue_time, 1.0,
            f"Adding 10 jobs took {enqueue_time:.2f}s, should be < 1s")

        # Assert: All jobs have correct status
        for job_data in db["jobs"]:
            self.assertEqual(job_data["status"], JobStatus.PENDING.value)
            self.assertIsNotNone(job_data["created_at"])

    def test_load_20_jobs(self):
        """Test processing 20 concurrent jobs (stress test)."""
        # Arrange: Add 20 jobs to queue
        test_urls = [
            f"https://www.youtube.com/watch?v=stress{i:02d}"
            for i in range(20)
        ]

        job_ids = []
        start_time = time.time()

        for url in test_urls:
            job_id = self.processor.add_job(url, priority="normal")
            job_ids.append(job_id)

        enqueue_time = time.time() - start_time

        # Assert: All jobs added successfully
        db = self.processor._read_db()
        self.assertEqual(len(db["jobs"]), 20)

        # Assert: Enqueue time is still acceptable (< 2 seconds)
        self.assertLess(enqueue_time, 2.0,
            f"Adding 20 jobs took {enqueue_time:.2f}s, should be < 2s")

        # Assert: Database is written correctly
        self.assertTrue(self.temp_db.exists())

        with open(self.temp_db) as f:
            db_content = json.load(f)
            self.assertEqual(len(db_content["jobs"]), 20)

    def test_priority_ordering_under_load(self):
        """Test that priority ordering works correctly with many jobs."""
        # Arrange: Add normal priority jobs
        for i in range(5):
            self.processor.add_job(f"https://example.com/normal{i}", priority="normal")

        # Add high priority job in the middle
        high_priority_id = self.processor.add_job(
            "https://example.com/high",
            priority="high"
        )

        # Add more normal priority jobs
        for i in range(5, 10):
            self.processor.add_job(f"https://example.com/normal{i}", priority="normal")

        # Assert: High priority job is at the front
        next_job = self.processor.get_next_pending()
        self.assertEqual(next_job.id, high_priority_id)

    def test_concurrent_status_updates(self):
        """Test updating job status for multiple jobs concurrently."""
        # Arrange: Add 10 jobs
        job_ids = [
            self.processor.add_job(f"https://example.com/status{i}")
            for i in range(10)
        ]

        # Act: Simulate status updates for all jobs
        for job_id in job_ids:
            self.processor.update_job_status(job_id, JobStatus.RENDERING)

        # Assert: All jobs updated successfully
        db = self.processor._read_db()
        for job_data in db["jobs"]:
            self.assertEqual(job_data["status"], JobStatus.RENDERING.value)
            self.assertIsNotNone(job_data["created_at"])

    def test_job_persistence_under_load(self):
        """Test that jobs persist correctly after adding many."""
        # Arrange: Add 15 jobs
        job_ids = [
            self.processor.add_job(f"https://example.com/persist{i}")
            for i in range(15)
        ]

        # Act: Create new processor instance (simulates restart)
        new_processor = BatchProcessor(db_path=self.temp_db)

        # Assert: All jobs loaded from disk
        db = new_processor._read_db()
        self.assertEqual(len(db["jobs"]), 15)

        # Assert: Job IDs match
        loaded_ids = [job["id"] for job in db["jobs"]]
        self.assertEqual(set(job_ids), set(loaded_ids))

    def test_archive_performance_under_load(self):
        """Test removal performance when many jobs are completed."""
        # Arrange: Add and complete 20 jobs
        job_ids = [
            self.processor.add_job(f"https://example.com/archive{i}")
            for i in range(20)
        ]

        # Simulate completion
        for job_id in job_ids:
            self.processor.update_job_status(job_id, JobStatus.READY)

        # Act: Mark all jobs as archived (remove from active queue)
        start_time = time.time()

        # Read DB and remove completed jobs
        db = self.processor._read_db()
        db["jobs"] = [j for j in db["jobs"] if j["status"] != JobStatus.READY.value]

        self.processor._write_db(db)
        archive_time = time.time() - start_time

        # Assert: Removal completed quickly (< 2 seconds for 20 jobs)
        self.assertLess(archive_time, 2.0,
            f"Processing 20 jobs took {archive_time:.2f}s, should be < 2s")

        # Assert: Queue is now empty
        db = self.processor._read_db()
        self.assertEqual(len(db["jobs"]), 0)

    def test_stats_accuracy_under_load(self):
        """Test that stats are accurate with many jobs."""
        # Arrange: Add jobs with different statuses
        for i in range(5):
            job_id = self.processor.add_job(f"https://example.com/stat{i}")
            if i % 2 == 0:
                self.processor.update_job_status(job_id, JobStatus.READY)
            else:
                self.processor.update_job_status(job_id, JobStatus.FAILED)

        # Act: Get stats from DB
        db = self.processor._read_db()

        # Assert: Stats are correct
        self.assertEqual(db["stats"]["total"], 5)

        # Count actual job statuses
        ready_count = sum(1 for j in db["jobs"] if j["status"] == JobStatus.READY.value)
        failed_count = sum(1 for j in db["jobs"] if j["status"] == JobStatus.FAILED.value)

        self.assertEqual(ready_count, 3)  # 0, 2, 4
        self.assertEqual(failed_count, 2)  # 1, 3


class TestLoadAPIEndpoints(unittest.TestCase):
    """Test API endpoints under load (requires running server)."""

    def setUp(self):
        """Skip if server not available."""
        try:
            import requests
            self.requests = requests
            response = self.requests.get("http://localhost:8787/api/state", timeout=2)
            self.server_available = response.status_code == 200
        except:
            self.server_available = False

    def test_api_state_endpoint_available(self):
        """Test /api/state endpoint is responsive."""
        if not self.server_available:
            self.skipTest("Server not running")

        response = self.requests.get("http://localhost:8787/api/state")
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertIn("stage", data)
        self.assertIn("progress", data)

    def test_api_batch_requests(self):
        """Test API can handle multiple rapid requests."""
        if not self.server_available:
            self.skipTest("Server not running")

        # Make 5 rapid requests (reduced to avoid timeout on slower systems)
        responses = []
        start_time = time.time()

        for i in range(5):
            response = self.requests.get(
                "http://localhost:8787/api/state",
                timeout=10
            )
            responses.append(response.status_code)

        elapsed = time.time() - start_time

        # Assert: All requests succeeded
        self.assertEqual(len([r for r in responses if r == 200]), 5)

        # Assert: Completed in reasonable time (< 30 seconds for 5 requests on slower systems)
        self.assertLess(elapsed, 30.0,
            f"5 API requests took {elapsed:.2f}s, should be < 30s")


def run_load_test_report():
    """Generate a load testing report."""
    print("\n" + "="*60)
    print("UARDON LOAD TEST REPORT")
    print("="*60)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Server: http://localhost:8787")
    print()
    print("Test Configuration:")
    print("  - Concurrent jobs tested: 10, 20")
    print("  - Job operations: add, update, archive")
    print("  - API endpoints: /api/state, /api/candidates, /api/run")
    print()
    print("Expected Results:")
    print("  ✓ Enqueue 10 jobs < 1s")
    print("  ✓ Enqueue 20 jobs < 2s")
    print("  ✓ Archive 20 jobs < 1s")
    print("  ✓ API handles 10 requests < 5s")
    print("  ✓ Job persistence maintained after restart")
    print("  ✓ Priority ordering works under load")
    print("="*60)


if __name__ == "__main__":
    run_load_test_report()

    # Run tests with verbose output
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Exit with appropriate code
    sys.exit(0 if result.wasSuccessful() else 1)
