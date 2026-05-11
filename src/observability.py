"""Structured logging and metrics for Poder em Jogo Studio.

Provides:
- JSON-based event logging (analytics.jsonl)
- Metrics collection (counters, timers, gauges)
- Easy querying and analysis

Usage:
    from observability import log_event, get_metrics

    log_event("job_submitted", {
        "job_id": "job-20250510-1",
        "url": "https://youtube.com/watch?v=...",
        "priority": "high"
    })

    metrics = get_metrics(event_type="job_completed", days=7)
    print(f"Success rate: {metrics['success_rate']:.1%}")
"""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
import threading


class ObservabilityManager:
    """Manages structured logging and metrics."""

    def __init__(self, analytics_path: Optional[Path] = None, max_file_size: int = 100 * 1024 * 1024):
        """Initialize observability manager.

        Args:
            analytics_path: Path to analytics.jsonl (default: outputs/analytics.jsonl)
            max_file_size: Max file size before rotation (default: 100MB)
        """
        if analytics_path is None:
            root = Path(__file__).resolve().parent.parent
            analytics_path = root / "outputs" / "analytics.jsonl"

        self.analytics_path = Path(analytics_path)
        self.max_file_size = max_file_size
        self.lock = threading.Lock()

        # Ensure outputs directory exists
        self.analytics_path.parent.mkdir(parents=True, exist_ok=True)

    def log_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Log a structured event.

        Args:
            event_type: Type of event (e.g., "job_submitted", "hook_generated")
            data: Event data as dict
        """
        # Rotate file if needed
        if self.analytics_path.exists() and self.analytics_path.stat().st_size > self.max_file_size:
            self._rotate_file()

        event = {
            "timestamp": datetime.now().isoformat(),
            "event": event_type,
            "data": data
        }

        with self.lock:
            with open(self.analytics_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def _rotate_file(self) -> None:
        """Rotate analytics file when it gets too large."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = self.analytics_path.with_name(
            f"analytics_{timestamp}.jsonl"
        )
        self.analytics_path.rename(backup_path)

    def get_events(
        self,
        event_type: Optional[str] = None,
        days: int = 7,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """Get events from analytics log.

        Args:
            event_type: Filter by event type (None = all events)
            days: Only events from last N days
            limit: Max events to return

        Returns:
            List of event dicts
        """
        if not self.analytics_path.exists():
            return []

        events = []
        cutoff_time = datetime.now() - timedelta(days=days)

        try:
            with open(self.analytics_path, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue

                    try:
                        event = json.loads(line)
                        event_timestamp = datetime.fromisoformat(event.get("timestamp", ""))

                        # Filter by time
                        if event_timestamp < cutoff_time:
                            continue

                        # Filter by type
                        if event_type and event.get("event") != event_type:
                            continue

                        events.append(event)

                        if len(events) >= limit:
                            break

                    except (json.JSONDecodeError, ValueError):
                        # Skip malformed lines
                        continue

        except IOError:
            pass

        return events

    def get_metrics(
        self,
        event_type: Optional[str] = None,
        days: int = 7
    ) -> Dict[str, Any]:
        """Calculate metrics from events.

        Args:
            event_type: Filter by event type
            days: Only events from last N days

        Returns:
            Dict with metrics
        """
        events = self.get_events(event_type=event_type, days=days, limit=10000)

        metrics = {
            "total_events": len(events),
            "event_type": event_type or "all",
            "days": days,
        }

        if not events:
            return metrics

        # Job completion metrics
        if event_type == "job_completed" or not event_type:
            job_events = [e for e in events if e.get("event") == "job_completed"]
            if job_events:
                completed = sum(1 for e in job_events if e.get("data", {}).get("status") == "ready")
                failed = sum(1 for e in job_events if e.get("data", {}).get("status") == "failed")
                total = len(job_events)

                metrics["job_stats"] = {
                    "total": total,
                    "completed": completed,
                    "failed": failed,
                    "success_rate": completed / total if total > 0 else 0,
                    "avg_duration_s": sum(e.get("data", {}).get("duration_s", 0) for e in job_events) / total if total > 0 else 0
                }

        # Hook generation metrics
        if event_type == "hook_generated" or not event_type:
            hook_events = [e for e in events if e.get("event") == "hook_generated"]
            if hook_events:
                successful = sum(1 for e in hook_events if e.get("data", {}).get("success", False))
                fallback = sum(1 for e in hook_events if e.get("data", {}).get("fallback_to_heuristic", False))
                total = len(hook_events)

                metrics["hook_stats"] = {
                    "total": total,
                    "successful": successful,
                    "fallback": fallback,
                    "success_rate": successful / total if total > 0 else 0,
                    "fallback_rate": fallback / successful if successful > 0 else 0,
                }

        # Hook selection metrics
        if event_type == "user_hook_selected" or not event_type:
            selection_events = [e for e in events if e.get("event") == "user_hook_selected"]
            if selection_events:
                styles = {}
                for e in selection_events:
                    style = e.get("data", {}).get("selected_style", "unknown")
                    styles[style] = styles.get(style, 0) + 1

                total = len(selection_events)
                metrics["hook_selection"] = {
                    "total": total,
                    "by_style": {k: {"count": v, "percentage": v / total} for k, v in styles.items()},
                }

        # API performance metrics
        if event_type == "api_call" or not event_type:
            api_events = [e for e in events if e.get("event") == "api_call"]
            if api_events:
                latencies = [e.get("data", {}).get("latency_ms", 0) for e in api_events]
                total = len(api_events)
                errors = sum(1 for e in api_events if e.get("data", {}).get("error"))

                metrics["api_stats"] = {
                    "total_calls": total,
                    "errors": errors,
                    "error_rate": errors / total if total > 0 else 0,
                    "avg_latency_ms": sum(latencies) / total if total > 0 else 0,
                    "p50_latency_ms": sorted(latencies)[total // 2] if total > 0 else 0,
                    "p95_latency_ms": sorted(latencies)[int(total * 0.95)] if total > 0 else 0,
                }

        return metrics

    def get_summary(self, days: int = 7) -> Dict[str, Any]:
        """Get high-level summary of system health.

        Args:
            days: Summarize events from last N days

        Returns:
            Dict with health summary
        """
        summary = {
            "timestamp": datetime.now().isoformat(),
            "period_days": days,
        }

        # Job health
        job_metrics = self.get_metrics(event_type="job_completed", days=days)
        if "job_stats" in job_metrics:
            summary["job_health"] = job_metrics["job_stats"]

        # Hook health
        hook_metrics = self.get_metrics(event_type="hook_generated", days=days)
        if "hook_stats" in hook_metrics:
            summary["hook_health"] = hook_metrics["hook_stats"]

        # API health
        api_metrics = self.get_metrics(event_type="api_call", days=days)
        if "api_stats" in api_metrics:
            summary["api_health"] = api_metrics["api_stats"]

        # User behavior
        selection_metrics = self.get_metrics(event_type="user_hook_selected", days=days)
        if "hook_selection" in selection_metrics:
            summary["user_preferences"] = selection_metrics["hook_selection"]

        return summary


# Global singleton instance
_instance: Optional[ObservabilityManager] = None


def get_manager() -> ObservabilityManager:
    """Get or create global ObservabilityManager instance."""
    global _instance
    if _instance is None:
        _instance = ObservabilityManager()
    return _instance


def log_event(event_type: str, data: Dict[str, Any]) -> None:
    """Log a structured event.

    Convenience function using global manager.

    Args:
        event_type: Type of event (e.g., "job_submitted", "hook_generated")
        data: Event data as dict

    Example:
        log_event("job_completed", {
            "job_id": "job-001",
            "duration_s": 120.5,
            "status": "ready"
        })
    """
    get_manager().log_event(event_type, data)


def get_metrics(event_type: Optional[str] = None, days: int = 7) -> Dict[str, Any]:
    """Get metrics from analytics.

    Convenience function using global manager.

    Args:
        event_type: Filter by event type
        days: Only events from last N days

    Returns:
        Dict with calculated metrics
    """
    return get_manager().get_metrics(event_type=event_type, days=days)


def get_summary(days: int = 7) -> Dict[str, Any]:
    """Get system health summary.

    Convenience function using global manager.

    Args:
        days: Summarize from last N days

    Returns:
        Dict with health summary
    """
    return get_manager().get_summary(days=days)


def clear_analytics(older_than_days: int = 30) -> None:
    """Archive old analytics (cleanup).

    Args:
        older_than_days: Archive events older than N days
    """
    manager = get_manager()
    if not manager.analytics_path.exists():
        return

    # Read all events
    events = []
    cutoff_time = datetime.now() - timedelta(days=older_than_days)

    with open(manager.analytics_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                event = json.loads(line)
                event_timestamp = datetime.fromisoformat(event.get("timestamp", ""))
                if event_timestamp >= cutoff_time:
                    events.append(event)
            except (json.JSONDecodeError, ValueError):
                pass

    # Rewrite keeping only recent events
    with open(manager.analytics_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    # Example usage
    import time

    print("Testing observability module...")

    # Log some test events
    log_event("job_submitted", {
        "job_id": "job-test-001",
        "url": "https://youtube.com/watch?v=test",
        "priority": "high"
    })

    log_event("job_completed", {
        "job_id": "job-test-001",
        "duration_s": 120.5,
        "clips_rendered": 3,
        "status": "ready"
    })

    log_event("hook_generated", {
        "job_id": "job-test-001",
        "style": "bold",
        "duration_s": 5.2,
        "success": True,
        "fallback_to_heuristic": False
    })

    # Get summary
    summary = get_summary(days=1)
    print("\nSystem Health Summary:")
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    # Get specific metrics
    hook_metrics = get_metrics(event_type="hook_generated")
    print("\nHook Generation Metrics:")
    print(json.dumps(hook_metrics, indent=2, ensure_ascii=False))

    print("\n✓ Observability test complete")
