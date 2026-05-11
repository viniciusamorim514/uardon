"""
A/B Testing & Automated Feedback Loops for Poder em Jogo Studio.

This module implements:
1. Hook variant A/B testing (track which variant was shown)
2. Encoding quality A/B testing (fast vs slow FFmpeg preset)
3. Metadata caption A/B testing (3 caption variations)
4. TikTok metrics integration (when API approved)
5. Automated learning (identify winners, update weights)

Cost: $0 (all local processing, no API calls)

Author: Claude (Autonomous Professionalization Phase)
License: MIT
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
import random
from collections import defaultdict

# Configuration
AB_TEST_RESULTS_FILE = Path(__file__).parent.parent / "outputs" / "ab_test_results.jsonl"
LEARNED_RULES_FILE = Path(__file__).parent.parent / "outputs" / "learned_rules.json"

class ABTestManager:
    """Manages A/B testing variants and learning."""

    def __init__(self):
        self.results = []
        self.learned_rules = self._load_learned_rules()
        self.load_results()

    def _load_learned_rules(self) -> Dict:
        """Load previously learned rules."""
        if LEARNED_RULES_FILE.exists():
            try:
                with open(LEARNED_RULES_FILE) as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        return {
            "hook_weights": {"bold": 1.0, "question": 1.0, "story": 1.0},
            "caption_weights": {1: 1.0, 2: 1.0, 3: 1.0},
            "encoding_weights": {"fast": 1.0, "slow": 0.8},
            "segment_rules": {}
        }

    def _save_learned_rules(self):
        """Save learned rules to file."""
        try:
            AB_TEST_RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(LEARNED_RULES_FILE, 'w') as f:
                json.dump(self.learned_rules, f, indent=2)
        except IOError as e:
            print(f"[ABTest] Failed to save learned rules: {e}")

    def load_results(self):
        """Load previous A/B test results."""
        if AB_TEST_RESULTS_FILE.exists():
            try:
                with open(AB_TEST_RESULTS_FILE) as f:
                    for line in f:
                        if line.strip():
                            self.results.append(json.loads(line))
            except (json.JSONDecodeError, IOError) as e:
                print(f"[ABTest] Failed to load results: {e}")

    def select_hook_variant(self, segment_type: str = "general") -> str:
        """
        Select a hook variant using learned weights.

        Segment types: "breaking_news", "education", "debate", "opinion", "general"

        Returns: "bold", "question", or "story"
        """
        # Get segment-specific rule if available
        if segment_type in self.learned_rules["segment_rules"]:
            rule = self.learned_rules["segment_rules"][segment_type]
            if rule.get("winning_style") and random.random() < (rule.get("confidence", 0) / 100):
                return rule["winning_style"]

        # Use global weights with random selection
        weights = self.learned_rules["hook_weights"]
        styles = list(weights.keys())
        style_weights = [weights[s] for s in styles]
        return random.choices(styles, weights=style_weights, k=1)[0]

    def select_caption_variant(self, segment_type: str = "general") -> int:
        """
        Select a caption variant (1, 2, or 3).

        Caption variations:
        1. Aggressive/engagement-focused
        2. Educational
        3. Question-format
        """
        weights = self.learned_rules["caption_weights"]
        captions = [1, 2, 3]
        caption_weights = [weights[c] for c in captions]
        return random.choices(captions, weights=caption_weights, k=1)[0]

    def select_encoding_preset(self) -> str:
        """
        Select encoding preset using learned weights.

        Returns: "fast" or "slow"
        """
        weights = self.learned_rules["encoding_weights"]
        presets = ["fast", "slow"]
        preset_weights = [weights[p] for p in presets]
        return random.choices(presets, weights=preset_weights, k=1)[0]

    def track_variant_shown(self, job_id: str, hook_style: str, caption_version: int,
                           encoding_preset: str, segment_type: str):
        """
        Track which variants were shown to user.

        Called when variants are generated/selected.
        """
        event = {
            "timestamp": datetime.now().isoformat(),
            "job_id": job_id,
            "hook_style": hook_style,
            "caption_version": caption_version,
            "encoding_preset": encoding_preset,
            "segment_type": segment_type,
            "event_type": "variant_shown",
            "tiktok_metrics": None  # Will be filled later
        }
        self.results.append(event)

    def record_tiktok_metrics(self, job_id: str, views: int, engagement_rate: float,
                             likes: int = 0, shares: int = 0, comments: int = 0):
        """
        Record TikTok metrics for a published video.

        Called 24h after video published, when metrics are available.
        """
        # Find matching variant record
        for result in self.results:
            if result["job_id"] == job_id and result["event_type"] == "variant_shown":
                result["tiktok_metrics"] = {
                    "timestamp": datetime.now().isoformat(),
                    "views": views,
                    "engagement_rate": engagement_rate,
                    "likes": likes,
                    "shares": shares,
                    "comments": comments,
                    "total_engagement": likes + shares + comments
                }
                self._save_result(result)
                break

    def _save_result(self, result: Dict):
        """Save single result to JSONL file."""
        try:
            AB_TEST_RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(AB_TEST_RESULTS_FILE, 'a') as f:
                f.write(json.dumps(result, ensure_ascii=False) + '\n')
        except IOError as e:
            print(f"[ABTest] Failed to save result: {e}")

    def analyze_winners_last_n_days(self, days: int = 7) -> Dict[str, Any]:
        """
        Analyze A/B test results from last N days.

        Returns winners for hook style, caption, and encoding.
        """
        cutoff = datetime.now() - timedelta(days=days)
        recent_results = [
            r for r in self.results
            if r.get("tiktok_metrics") and
            datetime.fromisoformat(r["tiktok_metrics"]["timestamp"]) > cutoff
        ]

        if not recent_results:
            return {"note": "No results with metrics in this period"}

        # Analyze hook styles
        hook_performance = defaultdict(list)
        caption_performance = defaultdict(list)
        encoding_performance = defaultdict(list)

        for result in recent_results:
            metrics = result.get("tiktok_metrics", {})
            engagement = metrics.get("engagement_rate", 0)

            hook_style = result.get("hook_style")
            if hook_style:
                hook_performance[hook_style].append(engagement)

            caption = result.get("caption_version")
            if caption:
                caption_performance[caption].append(engagement)

            encoding = result.get("encoding_preset")
            if encoding:
                encoding_performance[encoding].append(engagement)

        # Calculate averages
        hook_avg = {k: sum(v) / len(v) for k, v in hook_performance.items() if v}
        caption_avg = {k: sum(v) / len(v) for k, v in caption_performance.items() if v}
        encoding_avg = {k: sum(v) / len(v) for k, v in encoding_performance.items() if v}

        # Find winners
        hook_winner = max(hook_avg, key=hook_avg.get) if hook_avg else None
        caption_winner = max(caption_avg, key=caption_avg.get) if caption_avg else None
        encoding_winner = max(encoding_avg, key=encoding_avg.get) if encoding_avg else None

        return {
            "period_days": days,
            "samples": len(recent_results),
            "hook_analysis": {
                "results": hook_avg,
                "winner": hook_winner,
                "winner_engagement": hook_avg.get(hook_winner) if hook_winner else None
            },
            "caption_analysis": {
                "results": caption_avg,
                "winner": caption_winner,
                "winner_engagement": caption_avg.get(caption_winner) if caption_winner else None
            },
            "encoding_analysis": {
                "results": encoding_avg,
                "winner": encoding_winner,
                "winner_engagement": encoding_avg.get(encoding_winner) if encoding_winner else None
            }
        }

    def learn_and_update_weights(self, days: int = 7) -> Dict[str, Any]:
        """
        Analyze winners and update weights automatically.

        Called daily to adapt to changing audience preferences.
        """
        analysis = self.analyze_winners_last_n_days(days)

        if "note" in analysis:
            return analysis

        updates = {}

        # Update hook weights
        if analysis["hook_analysis"]["winner"]:
            winner = analysis["hook_analysis"]["winner"]
            old_weight = self.learned_rules["hook_weights"][winner]
            new_weight = min(1.5, old_weight * 1.1)  # Increase by 10%, max 1.5
            self.learned_rules["hook_weights"][winner] = new_weight
            updates["hook_weight_change"] = {
                "style": winner,
                "old": old_weight,
                "new": new_weight,
                "engagement_lift": f"+{(analysis['hook_analysis']['winner_engagement'] - 0.06) * 100:.1f}%"
            }

        # Update caption weights
        if analysis["caption_analysis"]["winner"]:
            winner = analysis["caption_analysis"]["winner"]
            old_weight = self.learned_rules["caption_weights"][winner]
            new_weight = min(1.5, old_weight * 1.1)
            self.learned_rules["caption_weights"][winner] = new_weight
            updates["caption_weight_change"] = {
                "version": winner,
                "old": old_weight,
                "new": new_weight
            }

        # Update encoding weights
        if analysis["encoding_analysis"]["winner"]:
            winner = analysis["encoding_analysis"]["winner"]
            old_weight = self.learned_rules["encoding_weights"][winner]
            new_weight = min(1.3, old_weight * 1.15)
            self.learned_rules["encoding_weights"][winner] = new_weight
            loser = "slow" if winner == "fast" else "fast"
            self.learned_rules["encoding_weights"][loser] = max(0.5, self.learned_rules["encoding_weights"][loser] * 0.9)
            updates["encoding_change"] = {
                "winner": winner,
                "winner_weight": new_weight,
                "loser_weight": self.learned_rules["encoding_weights"][loser]
            }

        # Save updated rules
        self._save_learned_rules()

        return {
            "timestamp": datetime.now().isoformat(),
            "updates": updates,
            "new_weights": self.learned_rules
        }

    def learn_segment_rules(self, segment_type: str, days: int = 7) -> Dict:
        """
        Learn segment-specific rules (e.g., breaking news prefers question hooks).

        Args:
            segment_type: Type of segment ("breaking_news", "education", etc.)
            days: Number of days to analyze

        Returns:
            Learned rule with confidence and sample size
        """
        cutoff = datetime.now() - timedelta(days=days)
        segment_results = [
            r for r in self.results
            if r.get("segment_type") == segment_type and
            r.get("tiktok_metrics") and
            datetime.fromisoformat(r["tiktok_metrics"]["timestamp"]) > cutoff
        ]

        if len(segment_results) < 3:
            return {"note": f"Not enough samples for {segment_type} (need 3+, have {len(segment_results)})"}

        # Find best hook style for this segment
        hook_performance = defaultdict(list)
        for result in segment_results:
            engagement = result["tiktok_metrics"].get("engagement_rate", 0)
            hook_style = result.get("hook_style")
            if hook_style:
                hook_performance[hook_style].append(engagement)

        hook_avg = {k: sum(v) / len(v) for k, v in hook_performance.items() if v}
        winner = max(hook_avg, key=hook_avg.get) if hook_avg else None
        confidence = len(hook_performance.get(winner, [])) / len(segment_results) * 100 if winner else 0

        rule = {
            "segment_type": segment_type,
            "winning_style": winner,
            "confidence": confidence,
            "sample_size": len(segment_results),
            "performance": hook_avg,
            "learned_at": datetime.now().isoformat()
        }

        self.learned_rules["segment_rules"][segment_type] = rule
        self._save_learned_rules()

        return rule

    def get_statistics(self) -> Dict[str, Any]:
        """Get overall A/B testing statistics."""
        total_tests = len(self.results)
        with_metrics = len([r for r in self.results if r.get("tiktok_metrics")])

        return {
            "total_variants_tested": total_tests,
            "with_tiktok_metrics": with_metrics,
            "metrics_rate": f"{with_metrics / max(1, total_tests) * 100:.1f}%",
            "current_weights": self.learned_rules,
            "learned_segments": len(self.learned_rules["segment_rules"])
        }

# Global manager instance
_manager_instance = None

def get_ab_manager() -> ABTestManager:
    """Get or create A/B test manager singleton."""
    global _manager_instance
    if _manager_instance is None:
        _manager_instance = ABTestManager()
    return _manager_instance

# Export convenience functions
def select_hook_variant(segment_type: str = "general") -> str:
    return get_ab_manager().select_hook_variant(segment_type)

def select_caption_variant(segment_type: str = "general") -> int:
    return get_ab_manager().select_caption_variant(segment_type)

def select_encoding_preset() -> str:
    return get_ab_manager().select_encoding_preset()

def track_variant(job_id: str, hook_style: str, caption: int, encoding: str, segment_type: str):
    get_ab_manager().track_variant_shown(job_id, hook_style, caption, encoding, segment_type)

def record_metrics(job_id: str, views: int, engagement_rate: float, **kwargs):
    get_ab_manager().record_tiktok_metrics(job_id, views, engagement_rate, **kwargs)

def get_stats() -> Dict:
    return get_ab_manager().get_statistics()

if __name__ == "__main__":
    # Test example
    manager = get_ab_manager()

    # Simulate some tests
    job_id = "test-001"
    hook = manager.select_hook_variant("breaking_news")
    caption = manager.select_caption_variant()
    encoding = manager.select_encoding_preset()

    print(f"Selected: hook={hook}, caption={caption}, encoding={encoding}")
    manager.track_variant(job_id, hook, caption, encoding, "breaking_news")

    # Simulate TikTok metrics (24h later)
    manager.record_tiktok_metrics(job_id, views=450000, engagement_rate=0.082)

    # Check stats
    print("\n=== A/B Test Statistics ===")
    print(json.dumps(manager.get_statistics(), indent=2))

    # Learn from data
    print("\n=== Learning from Data ===")
    update = manager.learn_and_update_weights()
    print(json.dumps(update, indent=2))
