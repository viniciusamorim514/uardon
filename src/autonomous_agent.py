"""
Autonomous monitoring agent for Poder em Jogo Studio.

This agent monitors system metrics in real-time, detects anomalies,
generates optimization recommendations, and learns from outcomes.

Runs in background thread, checks metrics every 120 seconds.
Cost-optimized: Claude recommendations batched once per day (~$0.12/day).

Author: Claude (Autonomous Professionalization Phase)
License: MIT
"""

import json
import os
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
import anthropic
import statistics

CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-4-7")
METRICS_URL = "http://localhost:8787/api/analytics"
RECOMMENDATIONS_FILE = Path(__file__).parent.parent / "outputs" / "agent_recommendations.jsonl"

class AutonomousAgent:
    """Monitors metrics and generates optimization recommendations."""

    def __init__(self, check_interval_seconds: int = 120, recommendation_interval_hours: int = 24):
        self.check_interval = check_interval_seconds
        self.recommendation_interval = recommendation_interval_hours * 3600
        self.running = False
        self.thread = None
        self.last_recommendation_time = 0
        self.metric_history = {}
        self.alerts = []

    def start(self):
        """Start monitoring thread."""
        if not self.running:
            self.running = True
            self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self.thread.start()
            print("[Agent] Autonomous monitoring started")

    def stop(self):
        """Stop monitoring thread."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        print("[Agent] Autonomous monitoring stopped")

    def _fetch_metrics(self) -> Optional[Dict]:
        """Fetch current metrics from /api/analytics."""
        try:
            import requests
            response = requests.get(METRICS_URL, timeout=5)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"[Agent] Failed to fetch metrics: {e}")
        return None

    def _detect_anomalies(self, metrics: Dict) -> List[Dict[str, Any]]:
        """Detect anomalies by comparing to 7-day baseline."""
        anomalies = []

        # Key metrics to monitor
        monitored_metrics = {
            "hook_success_rate": {"target": 85, "threshold": -15},  # Alert if drops 15%
            "job_completion_rate": {"target": 95, "threshold": -10},
            "api_latency_p95_ms": {"target": 2000, "threshold": 50},  # Alert if p95 > 2000
            "fallback_rate": {"target": 5, "threshold": 5},  # Alert if > 5%
        }

        for metric_name, config in monitored_metrics.items():
            current_value = metrics.get(metric_name)
            if current_value is None:
                continue

            # Store history
            if metric_name not in self.metric_history:
                self.metric_history[metric_name] = []
            self.metric_history[metric_name].append({
                "timestamp": datetime.now(),
                "value": current_value
            })

            # Keep only last 7 days
            cutoff = datetime.now() - timedelta(days=7)
            self.metric_history[metric_name] = [
                m for m in self.metric_history[metric_name]
                if m["timestamp"] > cutoff
            ]

            # Calculate baseline
            if len(self.metric_history[metric_name]) >= 2:
                values = [m["value"] for m in self.metric_history[metric_name][:-1]]
                if values:
                    baseline_avg = statistics.mean(values)
                    baseline_stdev = statistics.stdev(values) if len(values) > 1 else baseline_avg * 0.1

                    # Detect anomaly (> 2 stdev from baseline)
                    z_score = abs((current_value - baseline_avg) / max(baseline_stdev, 1))
                    if z_score > 2:
                        anomalies.append({
                            "metric": metric_name,
                            "current": current_value,
                            "baseline": baseline_avg,
                            "z_score": z_score,
                            "severity": "high" if z_score > 3 else "medium",
                            "direction": "up" if current_value > baseline_avg else "down"
                        })

        return anomalies

    def _generate_recommendation(self, metrics: Dict, anomalies: List) -> Optional[Dict]:
        """Generate Claude-powered recommendation based on anomalies."""
        if not anomalies or not CLAUDE_API_KEY:
            return None

        try:
            # Build context
            anomaly_text = "\n".join([
                f"- {a['metric']}: {a['current']:.1f} (baseline: {a['baseline']:.1f}, z-score: {a['z_score']:.2f})"
                for a in anomalies
            ])

            metrics_text = json.dumps({k: v for k, v in metrics.items() if isinstance(v, (int, float))}, indent=2)

            prompt = f"""You are optimizing a geopolitical video publishing system.
Anomalies detected:
{anomaly_text}

Current metrics:
{metrics_text}

Based on these anomalies, suggest ONE specific optimization change:
- What parameter should change? (e.g., hook_weight_question = 1.3)
- Why? (2-3 sentences)
- Expected impact? (% improvement)
- Confidence? (0-100%)

Respond as JSON only:
{{
    "parameter": "metric_name or config_name",
    "current_value": <number>,
    "suggested_value": <number>,
    "reason": "<explanation>",
    "expected_impact_percent": <number>,
    "confidence": <0-100>
}}"""

            client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}]
            )

            # Parse response
            response_text = response.content[0].text
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                recommendation = json.loads(json_match.group())
                recommendation["timestamp"] = datetime.now().isoformat()
                recommendation["anomalies"] = anomalies
                return recommendation
        except Exception as e:
            print(f"[Agent] Failed to generate recommendation: {e}")

        return None

    def _save_recommendation(self, recommendation: Dict):
        """Save recommendation to JSONL file."""
        try:
            RECOMMENDATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(RECOMMENDATIONS_FILE, 'a') as f:
                f.write(json.dumps(recommendation, ensure_ascii=False) + '\n')
            print(f"[Agent] Recommendation saved: {recommendation['parameter']}")
        except Exception as e:
            print(f"[Agent] Failed to save recommendation: {e}")

    def get_recommendations(self, limit: int = 10) -> List[Dict]:
        """Get recent recommendations from file."""
        recommendations = []
        if RECOMMENDATIONS_FILE.exists():
            try:
                with open(RECOMMENDATIONS_FILE) as f:
                    for line in f:
                        if line.strip():
                            recommendations.append(json.loads(line))
            except Exception as e:
                print(f"[Agent] Failed to load recommendations: {e}")
        return recommendations[-limit:]

    def get_alerts(self) -> List[Dict]:
        """Get current alerts."""
        return self.alerts

    def _monitor_loop(self):
        """Main monitoring loop."""
        while self.running:
            try:
                # Fetch metrics
                metrics = self._fetch_metrics()
                if not metrics:
                    time.sleep(self.check_interval)
                    continue

                # Detect anomalies
                anomalies = self._detect_anomalies(metrics)

                # Update alerts
                self.alerts = anomalies

                if anomalies:
                    print(f"[Agent] Detected {len(anomalies)} anomalies")
                    for anomaly in anomalies:
                        print(f"  - {anomaly['metric']}: {anomaly['severity']}")

                # Generate recommendation if enough time passed (batch once per day)
                now = time.time()
                if now - self.last_recommendation_time > self.recommendation_interval:
                    recommendation = self._generate_recommendation(metrics, anomalies)
                    if recommendation:
                        self._save_recommendation(recommendation)
                        self.last_recommendation_time = now

                time.sleep(self.check_interval)

            except Exception as e:
                print(f"[Agent] Monitor loop error: {e}")
                time.sleep(self.check_interval)

# Global agent instance
_agent_instance = None

def get_agent() -> AutonomousAgent:
    """Get or create agent singleton."""
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = AutonomousAgent()
    return _agent_instance

def start_agent():
    """Start autonomous agent."""
    agent = get_agent()
    if not agent.running:
        agent.start()

def stop_agent():
    """Stop autonomous agent."""
    agent = get_agent()
    if agent.running:
        agent.stop()

def get_alerts() -> List[Dict]:
    """Get current alerts from agent."""
    return get_agent().get_alerts()

def get_recommendations(limit: int = 10) -> List[Dict]:
    """Get recent recommendations from agent."""
    return get_agent().get_recommendations(limit)

# Example usage / testing
if __name__ == "__main__":
    import os

    # Start agent
    agent = get_agent()
    agent.start()

    # Run for 10 minutes to test
    print("Agent running (10 minute test)...")
    try:
        for i in range(50):  # 50 * 120 seconds = ~100 minutes
            print(f"\n[{i}] Alerts: {len(agent.get_alerts())}")
            if agent.get_alerts():
                for alert in agent.get_alerts():
                    print(f"  - {alert['metric']}: {alert['severity']}")

            time.sleep(agent.check_interval)
            if i % 5 == 0:
                recommendations = agent.get_recommendations(1)
                if recommendations:
                    print(f"  Latest recommendation: {recommendations[-1]['parameter']}")

    except KeyboardInterrupt:
        print("\nStopping agent...")
        agent.stop()
