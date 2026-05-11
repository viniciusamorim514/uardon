"""Unit tests for BatchProcessor - Job queue management and persistence."""

import unittest
import tempfile
import json
import time
import threading
from pathlib import Path
from datetime import datetime, timedelta

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.batch_processor import BatchProcessor, Job, JobStatus


class TestBatchProcessor(unittest.TestCase):
    """Core BatchProcessor functionality tests."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "studio_db.json"
        self.processor = BatchProcessor(db_path=self.db_path)

    def tearDown(self):
        import shutil
        if Path(self.temp_dir).exists():
            shutil.rmtree(self.temp_dir)

    def test_add_job_single(self):
        """Verify single job creation and default status."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        job_id = self.processor.add_job(url)
        self.assertIsNotNone(job_id)
        job = self.processor.get_job(job_id)
        self.assertIsNotNone(job)
        self.assertEqual(job.url, url)
        self.assertEqual(job.status, JobStatus.PENDING.value)

    def test_add_job_multiple(self):
        """Add multiple jobs and verify all are stored."""
        urls = [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://www.youtube.com/watch?v=anotherVideo",
            "https://www.youtube.com/watch?v=thirdVideo",
        ]
        job_ids = [self.processor.add_job(url) for url in urls]
        self.assertEqual(len(job_ids), 3)
        self.assertEqual(len(set(job_ids)), 3)
        for job_id, url in zip(job_ids, urls):
            job = self.processor.get_job(job_id)
            self.assertIsNotNone(job)
            self.assertEqual(job.url, url)

    def test_priority_ordering(self):
        """Verify priority-based job ordering."""
        id1 = self.processor.add_job("https://url1.com", priority="normal")
        id2 = self.processor.add_job("https://url2.com", priority="low")
        id3 = self.processor.add_job("https://url3.com", priority="high")
        
        next1 = self.processor.get_next_pending()
        self.assertEqual(next1.id, id3)
        self.processor.update_job_status(id3, JobStatus.RENDERING)
        
        next2 = self.processor.get_next_pending()
        self.assertEqual(next2.id, id1)

    def test_get_next_pending(self):
        """Verify FIFO job retrieval."""
        id1 = self.processor.add_job("https://url1.com")
        id2 = self.processor.add_job("https://url2.com")
        next_job = self.processor.get_next_pending()
        self.assertEqual(next_job.id, id1)
        self.processor.update_job_status(id1, JobStatus.RENDERING)
        next_job = self.processor.get_next_pending()
        self.assertEqual(next_job.id, id2)

    def test_update_job_status(self):
        """Verify status transitions and timestamps."""
        job_id = self.processor.add_job("https://url.com")
        job = self.processor.get_job(job_id)
        self.assertEqual(job.status, JobStatus.PENDING.value)
        self.processor.update_job_status(job_id, JobStatus.RENDERING)
        job = self.processor.get_job(job_id)
        self.assertEqual(job.status, JobStatus.RENDERING.value)
        self.assertIsNotNone(job.started_at)

    def test_persistence_after_restart(self):
        """Verify jobs survive processor restart."""
        id1 = self.processor.add_job("https://url1.com")
        self.processor.update_job_status(id1, JobStatus.RENDERING)
        processor2 = BatchProcessor(db_path=self.db_path)
        job1 = processor2.get_job(id1)
        self.assertIsNotNone(job1)
        self.assertEqual(job1.status, JobStatus.RENDERING.value)

    def test_set_output_dir(self):
        """Verify output directory attachment."""
        job_id = self.processor.add_job("https://url.com")
        output_dir = Path(self.temp_dir) / "outputs" / job_id
        self.processor.set_output_dir(job_id, str(output_dir))
        job = self.processor.get_job(job_id)
        self.assertEqual(job.output_dir, str(output_dir))

    def test_list_jobs_with_filter(self):
        """Verify job listing and filtering."""
        id1 = self.processor.add_job("https://url1.com")
        id2 = self.processor.add_job("https://url2.com")
        self.processor.update_job_status(id1, JobStatus.RENDERING)
        self.processor.update_job_status(id2, JobStatus.READY)
        
        rendering = self.processor.list_jobs(status=JobStatus.RENDERING)
        self.assertEqual(len(rendering), 1)
        self.assertEqual(rendering[0].id, id1)

    def test_get_stats(self):
        """Verify statistics tracking."""
        for i in range(5):
            self.processor.add_job(f"https://url{i}.com")
        stats = self.processor.get_stats()
        self.assertEqual(stats['total'], 5)
        self.assertEqual(stats['completed'], 0)
        self.assertEqual(stats['failed'], 0)

    def test_archive_job(self):
        """Verify job archival."""
        id1 = self.processor.add_job("https://url1.com")
        id2 = self.processor.add_job("https://url2.com")
        self.processor.update_job_status(id1, JobStatus.READY)
        self.processor.archive_job(id1)
        job = self.processor.get_job(id1)
        self.assertIsNone(job)
        job2 = self.processor.get_job(id2)
        self.assertIsNotNone(job2)

    def test_concurrent_writes(self):
        """Verify file integrity under concurrent writes."""
        results = {'job_ids': [], 'errors': []}
        def add_job_thread(url):
            try:
                job_id = self.processor.add_job(url)
                results['job_ids'].append(job_id)
            except Exception as e:
                results['errors'].append(str(e))
        
        threads = [threading.Thread(target=add_job_thread, args=(f"https://url{i}.com",)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        self.assertEqual(len(results['errors']), 0)
        self.assertEqual(len(results['job_ids']), 10)


class TestJobDataclass(unittest.TestCase):
    """Tests for Job dataclass and JobStatus enum."""

    def test_job_creation(self):
        """Verify Job creation."""
        job = Job(id="test_job_1", url="https://url.com", status=JobStatus.PENDING.value)
        self.assertEqual(job.id, "test_job_1")
        self.assertEqual(job.url, "https://url.com")
        self.assertEqual(job.status, JobStatus.PENDING.value)

    def test_job_status_enum(self):
        """Verify all JobStatus values."""
        statuses = [JobStatus.PENDING, JobStatus.RENDERING, JobStatus.VALIDATING, JobStatus.READY, JobStatus.FAILED]
        self.assertEqual(len(statuses), 5)


class TestErrorHandling(unittest.TestCase):
    """Tests for error handling and edge cases."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "studio_db.json"
        self.processor = BatchProcessor(db_path=self.db_path)

    def tearDown(self):
        import shutil
        if Path(self.temp_dir).exists():
            shutil.rmtree(self.temp_dir)

    def test_get_nonexistent_job(self):
        """Verify graceful handling of nonexistent jobs."""
        result = self.processor.get_job("nonexistent_id")
        self.assertIsNone(result)

    def test_empty_db_initialization(self):
        """Verify processor handles missing DB on startup."""
        new_processor = BatchProcessor(db_path=self.db_path)
        stats = new_processor.get_stats()
        self.assertEqual(stats['total'], 0)
        job_id = new_processor.add_job("https://url.com")
        self.assertIsNotNone(job_id)


class TestBatchProcessorIntegration(unittest.TestCase):
    """Integration tests for realistic workflows."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "studio_db.json"
        self.processor = BatchProcessor(db_path=self.db_path)

    def tearDown(self):
        import shutil
        if Path(self.temp_dir).exists():
            shutil.rmtree(self.temp_dir)

    def test_realistic_workflow(self):
        """Test a realistic job queue workflow."""
        job_ids = []
        for i in range(5):
            job_id = self.processor.add_job(
                f"https://youtube.com/watch?v={i}",
                priority="normal" if i < 3 else "high"
            )
            job_ids.append(job_id)

        next_job = self.processor.get_next_pending()
        self.assertIn(next_job.id, job_ids[3:])
        self.processor.update_job_status(next_job.id, JobStatus.RENDERING)

        output_dir = Path(self.temp_dir) / "outputs" / next_job.id
        self.processor.set_output_dir(next_job.id, str(output_dir))
        self.processor.update_job_status(next_job.id, JobStatus.VALIDATING)
        self.processor.update_job_status(next_job.id, JobStatus.READY)

        stats = self.processor.get_stats()
        self.assertEqual(stats['total'], 5)
        self.assertEqual(stats['completed'], 1)

    def test_priority_mixed_workflow(self):
        """Test mixed priority workflow."""
        ids = [
            self.processor.add_job("url1", priority="normal"),
            self.processor.add_job("url2", priority="low"),
            self.processor.add_job("url3", priority="normal"),
            self.processor.add_job("url4", priority="high"),
            self.processor.add_job("url5", priority="low"),
        ]

        next1 = self.processor.get_next_pending()
        self.assertEqual(next1.id, ids[3])


if __name__ == '__main__':
    unittest.main(verbosity=2)
