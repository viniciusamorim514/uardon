"""
MCP Skill Server for Poder em Jogo Studio.

Provides Claude-accessible skills for:
1. Performance summarization (read analytics, generate insights)
2. Issue diagnosis (analyze errors, suggest fixes)
3. Audience optimization (personalized suggestions)
4. Competitor content analysis (positioning intelligence)

Cost: $0.05-0.10/day (batched skill calls from Claude)

Author: Claude (Autonomous Professionalization Phase)
License: MIT
"""

import json
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
from collections import defaultdict
import anthropic

# Configuration
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-4-7")
ANALYTICS_FILE = Path(__file__).parent.parent / "outputs" / "analytics.jsonl"
RECOMMENDATIONS_FILE = Path(__file__).parent.parent / "outputs" / "agent_recommendations.jsonl"
LEARNED_RULES_FILE = Path(__file__).parent.parent / "outputs" / "learned_rules.json"


class MCPSkillServer:
    """Skill endpoints for Claude integration."""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=CLAUDE_API_KEY) if CLAUDE_API_KEY else None

    # ==================== SKILL 1: Summarize Performance ====================

    def skill_summarize_performance(self, days: int = 7) -> Dict[str, Any]:
        """
        Read analytics.jsonl and generate natural language performance summary.

        Returns: {
            "summary": "natural language overview",
            "highlights": ["metric1", "metric2"],
            "concerns": ["issue1", "issue2"],
            "recommendations": ["action1", "action2"],
            "method": "claude|heuristic"
        }
        """
        analytics = self._load_analytics(days)

        if not analytics:
            return {
                "summary": "No analytics data available",
                "highlights": [],
                "concerns": ["No events logged"],
                "recommendations": ["Start generating content to populate analytics"],
                "method": "heuristic"
            }

        # Aggregate metrics
        summary_data = self._aggregate_analytics(analytics)

        if not self.client or not CLAUDE_API_KEY:
            return self._heuristic_performance_summary(summary_data)

        try:
            prompt = f"""Analyze this geopolitical video publishing system performance:

METRICS (last {days} days):
- Total jobs: {summary_data.get('total_jobs', 0)}
- Success rate: {summary_data.get('success_rate', 0):.1f}%
- Average processing time: {summary_data.get('avg_processing_time', 0):.1f}s
- Hook generation success: {summary_data.get('hook_success_rate', 0):.1f}%
- Fallback rate: {summary_data.get('fallback_rate', 0):.1f}%

HOOK PERFORMANCE:
{json.dumps(summary_data.get('hook_performance', {}), indent=2)}

ERRORS:
{json.dumps(summary_data.get('errors', []), indent=2) if summary_data.get('errors') else 'None'}

Provide:
1. One-sentence headline about system health
2. Top 3 highlights (what's working well)
3. Top 2 concerns (what needs attention)
4. 3 specific optimization recommendations
5. Confidence level (0-100%)

Respond as JSON:
{{
    "headline": "...",
    "highlights": ["...", "...", "..."],
    "concerns": ["...", "..."],
    "recommendations": ["...", "...", "..."],
    "confidence": <number>
}}"""

            response = self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = response.content[0].text
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                return {
                    "summary": result.get("headline", ""),
                    "highlights": result.get("highlights", []),
                    "concerns": result.get("concerns", []),
                    "recommendations": result.get("recommendations", []),
                    "method": "claude"
                }
        except Exception as e:
            print(f"[MCP] Claude summarization failed: {e}")

        return self._heuristic_performance_summary(summary_data)

    def _heuristic_performance_summary(self, data: Dict) -> Dict[str, Any]:
        """Fallback heuristic performance summary."""
        success_rate = data.get("success_rate", 0)

        return {
            "summary": f"System processing {data.get('total_jobs', 0)} jobs with {success_rate:.0f}% success rate",
            "highlights": [
                f"Hook generation {data.get('hook_success_rate', 0):.0f}% successful",
                f"Average processing time: {data.get('avg_processing_time', 0):.0f}s",
                f"Low fallback rate: {data.get('fallback_rate', 0):.0f}%"
            ] if success_rate > 85 else [
                f"{data.get('total_jobs', 0)} jobs processed",
                "System operational"
            ],
            "concerns": [
                f"Success rate {success_rate:.0f}% below target (85%)"
            ] if success_rate < 85 else [],
            "recommendations": [
                "Monitor hook generation quality",
                "Check for API latency issues",
                "Analyze failing jobs for patterns"
            ] if success_rate < 85 else [
                "Consider increasing batch size",
                "Monitor resource utilization"
            ],
            "method": "heuristic"
        }

    # ==================== SKILL 2: Diagnose Issue ====================

    def skill_diagnose_issue(self, error_message: str = "", job_id: str = "") -> Dict[str, Any]:
        """
        Diagnose system issues based on error messages or job failures.

        Args:
            error_message: Error message from system
            job_id: Job ID to investigate

        Returns: {
            "diagnosis": "root cause analysis",
            "severity": "low|medium|high",
            "affected_component": "hook_gen|rendering|api|queue",
            "fix_steps": ["step1", "step2"],
            "test_method": "how to verify fix"
        }
        """
        # Load recent errors from analytics
        analytics = self._load_analytics(days=1)
        errors = [e for e in analytics if e.get("event_type") == "error" or e.get("status") == "failed"]

        if not errors and not error_message:
            return {
                "diagnosis": "No recent errors detected",
                "severity": "low",
                "affected_component": "none",
                "fix_steps": [],
                "test_method": "Continue monitoring"
            }

        # Build diagnostic context
        recent_errors = errors[-5:]  # Last 5 errors
        error_context = f"Error: {error_message}\n\nRecent errors:\n"
        error_context += "\n".join([
            f"- {e.get('error_type', 'unknown')}: {e.get('error_detail', '')}"
            for e in recent_errors
        ])

        if job_id:
            job_events = [e for e in analytics if e.get("job_id") == job_id]
            error_context += f"\n\nJob {job_id} timeline:\n"
            error_context += "\n".join([
                f"- {e.get('event_type')}: {e.get('status', 'N/A')}"
                for e in job_events
            ])

        if not self.client or not CLAUDE_API_KEY:
            return self._heuristic_diagnose(error_message, recent_errors)

        try:
            prompt = f"""Diagnose this video publishing system error:

{error_context}

Identify:
1. Root cause (what went wrong?)
2. Severity (low/medium/high impact)
3. Affected component (hook_gen, rendering, api, queue, other)
4. Exact fix steps (numbered list, specific commands or config changes)
5. How to verify the fix works

Respond as JSON:
{{
    "diagnosis": "root cause in 2-3 sentences",
    "severity": "low|medium|high",
    "affected_component": "hook_gen|rendering|api|queue|other",
    "fix_steps": ["step 1", "step 2", ...],
    "test_method": "how to verify fix"
}}"""

            response = self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = response.content[0].text
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception as e:
            print(f"[MCP] Claude diagnosis failed: {e}")

        return self._heuristic_diagnose(error_message, recent_errors)

    def _heuristic_diagnose(self, error_msg: str, recent_errors: List) -> Dict[str, Any]:
        """Fallback heuristic diagnosis."""
        severity = "high" if "memory" in error_msg.lower() else "medium" if error_msg else "low"

        if "hook" in error_msg.lower():
            component = "hook_gen"
        elif "render" in error_msg.lower() or "ffmpeg" in error_msg.lower():
            component = "rendering"
        elif "api" in error_msg.lower():
            component = "api"
        elif "queue" in error_msg.lower():
            component = "queue"
        else:
            component = "other"

        return {
            "diagnosis": f"System detected {component} issue - check logs for detailed error trace",
            "severity": severity,
            "affected_component": component,
            "fix_steps": [
                "Check system logs in outputs/",
                f"Verify {component} service status",
                "Restart affected component if necessary"
            ],
            "test_method": f"Re-run failed job and check {component} output"
        }

    # ==================== SKILL 3: Optimize for Audience ====================

    def skill_optimize_for_audience(self, audience_type: str = "general") -> Dict[str, Any]:
        """
        Generate audience-specific optimization recommendations.

        Args:
            audience_type: "breaking_news", "education", "debate", "opinion", "general"

        Returns: {
            "audience": "audience type",
            "recommended_style": "hook style recommendation",
            "caption_strategy": "caption approach",
            "posting_schedule": "best time to post",
            "content_focus": "what resonates with this audience",
            "confidence": 0-100
        }
        """
        # Load learned rules and recent performance
        learned_rules = self._load_learned_rules()
        analytics = self._load_analytics(days=7)

        # Get performance for this segment
        segment_perf = defaultdict(list)
        for event in analytics:
            if event.get("segment_type") == audience_type and event.get("tiktok_metrics"):
                metrics = event["tiktok_metrics"]
                segment_perf[event.get("hook_style", "unknown")].append(metrics.get("engagement_rate", 0))

        # Calculate segment-specific averages
        segment_avgs = {
            style: sum(rates) / len(rates) if rates else 0
            for style, rates in segment_perf.items()
        }

        if not self.client or not CLAUDE_API_KEY:
            return self._heuristic_audience_optimization(audience_type, learned_rules, segment_avgs)

        try:
            prompt = f"""Recommend optimization strategy for "{audience_type}" content.

AUDIENCE CONTEXT:
- Type: {audience_type}
- Available segments: breaking_news, education, debate, opinion

LEARNED HOOK PREFERENCES FOR THIS AUDIENCE:
{json.dumps(segment_avgs, indent=2) if segment_avgs else 'No data yet - use heuristics'}

GLOBAL HOOK WEIGHTS (fallback):
{json.dumps(learned_rules.get('hook_weights', {}), indent=2)}

For this audience type, recommend:
1. Best hook style (bold/question/story) and why
2. Caption strategy (aggressive/educational/question-based)
3. Best time to post (time-based heuristic)
4. What content resonates (themes, keywords, format)
5. Expected engagement lift (%)

Respond as JSON:
{{
    "recommended_style": "bold|question|story",
    "style_reasoning": "why this works",
    "caption_strategy": "...",
    "posting_schedule": "...",
    "content_focus": "...",
    "expected_lift_percent": <number>,
    "confidence": <0-100>
}}"""

            response = self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = response.content[0].text
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                return {
                    "audience": audience_type,
                    "recommended_style": result.get("recommended_style", "question"),
                    "caption_strategy": result.get("caption_strategy", ""),
                    "posting_schedule": result.get("posting_schedule", ""),
                    "content_focus": result.get("content_focus", ""),
                    "expected_lift_percent": result.get("expected_lift_percent", 0),
                    "confidence": result.get("confidence", 0)
                }
        except Exception as e:
            print(f"[MCP] Claude optimization failed: {e}")

        return self._heuristic_audience_optimization(audience_type, learned_rules, segment_avgs)

    def _heuristic_audience_optimization(self, audience_type: str, rules: Dict, perf: Dict) -> Dict[str, Any]:
        """Fallback heuristic audience optimization."""
        heuristic_styles = {
            "breaking_news": "question",
            "education": "story",
            "debate": "bold",
            "opinion": "question",
            "general": "question"
        }

        heuristic_captions = {
            "breaking_news": "breaking news alert format",
            "education": "educational explanation",
            "debate": "controversial hook",
            "opinion": "thought-provoking question",
            "general": "engagement-focused"
        }

        heuristic_schedule = {
            "breaking_news": "ASAP (within 2 hours of event)",
            "education": "Monday-Friday 9am or 5pm",
            "debate": "Thursday-Friday prime time (6-9pm)",
            "opinion": "Whenever ready (evergreen)",
            "general": "Friday 6pm - Sunday 2pm"
        }

        return {
            "audience": audience_type,
            "recommended_style": heuristic_styles.get(audience_type, "question"),
            "caption_strategy": heuristic_captions.get(audience_type, ""),
            "posting_schedule": heuristic_schedule.get(audience_type, ""),
            "content_focus": f"Optimize for {audience_type} preferences",
            "expected_lift_percent": 15,
            "confidence": 60
        }

    # ==================== SKILL 4: Competitor Content Analysis ====================

    def skill_analyze_competitor(self, competitor_channel: str = "") -> Dict[str, Any]:
        """
        Analyze competitor positioning and generate competitive intelligence.

        Note: Currently uses heuristic analysis. When TikTok API approved,
        this will fetch real competitor data.

        Returns: {
            "competitor": "channel name",
            "positioning": "how they position content",
            "strength": "what they do well",
            "weakness": "where they're weak",
            "opportunity": "where we can differentiate",
            "recommendation": "our strategy vs theirs"
        }
        """
        # TODO: When TikTok API approved, add real competitor data fetching

        heuristic_analysis = {
            "positioning": "Educational geopolitical content with short-form video",
            "strength": ["Fast news cycle response", "International perspective", "Visual storytelling"],
            "weakness": ["Limited hook variety", "Inconsistent posting schedule", "Basic subtitle styling"],
            "opportunity": [
                "Advanced A/B testing (test hook variants with our system)",
                "Predictive publishing (optimize for audience behavior)",
                "Personalized captions (region/language specific)",
                "Analytics-driven content (show what's working)"
            ]
        }

        if not self.client or not CLAUDE_API_KEY:
            return {
                "competitor": competitor_channel or "Industry average",
                "positioning": heuristic_analysis["positioning"],
                "strength": heuristic_analysis["strength"],
                "weakness": heuristic_analysis["weakness"],
                "opportunity": heuristic_analysis["opportunity"],
                "recommendation": "Use our advanced A/B testing + autonomous learning to outcompete",
                "method": "heuristic"
            }

        try:
            prompt = f"""Provide competitive analysis for geopolitical TikTok/YouTube content.

COMPETITOR: {competitor_channel or 'General geopolitical content creators'}

INDUSTRY CONTEXT:
- Content: Geopolitical news and analysis (Ukraine, China, US politics, etc)
- Platform: TikTok/YouTube shorts (15-60 seconds)
- Audience: 18-35 year olds interested in global affairs

Analyze:
1. How competitors position geopolitical content
2. What makes their content successful (hook style, editing, timing)
3. Where they fall short (what's missing)
4. Opportunities for differentiation (what we can do better)
5. Our strategic advantage (AI-powered, autonomous learning, A/B testing)

Respond as JSON:
{{
    "positioning": "how they frame content",
    "strengths": ["strength1", "strength2"],
    "weaknesses": ["weakness1", "weakness2"],
    "opportunities": ["opp1", "opp2", "opp3"],
    "our_advantage": "why our approach wins"
}}"""

            response = self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}]
            )

            response_text = response.content[0].text
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                return {
                    "competitor": competitor_channel or "Industry average",
                    "positioning": result.get("positioning", ""),
                    "strength": result.get("strengths", []),
                    "weakness": result.get("weaknesses", []),
                    "opportunity": result.get("opportunities", []),
                    "recommendation": result.get("our_advantage", ""),
                    "method": "claude"
                }
        except Exception as e:
            print(f"[MCP] Claude competitor analysis failed: {e}")

        return {
            "competitor": competitor_channel or "Industry average",
            "positioning": heuristic_analysis["positioning"],
            "strength": heuristic_analysis["strength"],
            "weakness": heuristic_analysis["weakness"],
            "opportunity": heuristic_analysis["opportunity"],
            "recommendation": "Use our advanced A/B testing + autonomous learning to outcompete",
            "method": "heuristic_fallback"
        }

    # ==================== HELPER METHODS ====================

    def _load_analytics(self, days: int = 7) -> List[Dict]:
        """Load recent analytics events from JSONL."""
        if not ANALYTICS_FILE.exists():
            return []

        events = []
        cutoff = datetime.now() - timedelta(days=days)
        try:
            with open(ANALYTICS_FILE) as f:
                for line in f:
                    if line.strip():
                        event = json.loads(line)
                        if "timestamp" in event:
                            ts = datetime.fromisoformat(event["timestamp"])
                            if ts > cutoff:
                                events.append(event)
        except (json.JSONDecodeError, IOError) as e:
            print(f"[MCP] Failed to load analytics: {e}")

        return events

    def _load_learned_rules(self) -> Dict:
        """Load learned rules from A/B testing."""
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

    def _aggregate_analytics(self, events: List[Dict]) -> Dict[str, Any]:
        """Aggregate analytics into summary metrics."""
        total_jobs = len(set(e.get("job_id") for e in events if e.get("job_id")))
        successful = len([e for e in events if e.get("status") == "ready"])
        failed = len([e for e in events if e.get("status") == "failed"])

        success_rate = (successful / max(1, successful + failed)) * 100 if (successful + failed) > 0 else 0

        # Hook performance
        hook_performance = defaultdict(lambda: {"count": 0, "success": 0})
        for e in events:
            if e.get("hook_style"):
                hook = e["hook_style"]
                hook_performance[hook]["count"] += 1
                if e.get("status") == "ready":
                    hook_performance[hook]["success"] += 1

        hook_success_rate = 0
        if hook_performance:
            total_hooks = sum(h["count"] for h in hook_performance.values())
            total_success = sum(h["success"] for h in hook_performance.values())
            hook_success_rate = (total_success / max(1, total_hooks)) * 100

        # Average processing time
        processing_times = [e.get("duration_s", 0) for e in events if e.get("duration_s")]
        avg_processing_time = sum(processing_times) / len(processing_times) if processing_times else 0

        # Fallback rate
        fallback_events = [e for e in events if e.get("fallback_to_heuristic")]
        fallback_rate = (len(fallback_events) / max(1, len(events))) * 100 if events else 0

        # Errors
        errors = [e.get("error") for e in events if e.get("error")]

        return {
            "total_jobs": total_jobs,
            "total_events": len(events),
            "success_rate": success_rate,
            "hook_success_rate": hook_success_rate,
            "avg_processing_time": avg_processing_time,
            "fallback_rate": fallback_rate,
            "hook_performance": {
                hook: {
                    "count": data["count"],
                    "success_rate": (data["success"] / max(1, data["count"]) * 100)
                }
                for hook, data in hook_performance.items()
            },
            "errors": errors[:5]  # Last 5 errors
        }


# Global skill server instance
_skill_server = None

def get_skill_server() -> MCPSkillServer:
    """Get or create skill server singleton."""
    global _skill_server
    if _skill_server is None:
        _skill_server = MCPSkillServer()
    return _skill_server


# Exported skill functions
def summarize_performance(days: int = 7) -> Dict[str, Any]:
    """Summarize system performance."""
    return get_skill_server().skill_summarize_performance(days)


def diagnose_issue(error_message: str = "", job_id: str = "") -> Dict[str, Any]:
    """Diagnose system issues."""
    return get_skill_server().skill_diagnose_issue(error_message, job_id)


def optimize_for_audience(audience_type: str = "general") -> Dict[str, Any]:
    """Get audience-specific optimizations."""
    return get_skill_server().skill_optimize_for_audience(audience_type)


def analyze_competitor(channel: str = "") -> Dict[str, Any]:
    """Analyze competitor positioning."""
    return get_skill_server().skill_analyze_competitor(channel)


if __name__ == "__main__":
    # Test example
    server = get_skill_server()

    print("=== SKILL 1: Summarize Performance ===")
    perf = server.skill_summarize_performance(days=7)
    print(json.dumps(perf, indent=2, ensure_ascii=False))

    print("\n=== SKILL 2: Diagnose Issue ===")
    diag = server.skill_diagnose_issue(error_message="Hook generation failed: API timeout")
    print(json.dumps(diag, indent=2, ensure_ascii=False))

    print("\n=== SKILL 3: Optimize for Audience ===")
    opt = server.skill_optimize_for_audience(audience_type="breaking_news")
    print(json.dumps(opt, indent=2, ensure_ascii=False))

    print("\n=== SKILL 4: Analyze Competitor ===")
    comp = server.skill_analyze_competitor(competitor_channel="GeopoliticalNews")
    print(json.dumps(comp, indent=2, ensure_ascii=False))
