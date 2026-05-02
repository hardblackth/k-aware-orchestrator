"""
K-Vector Collector — Collect 9-dim K-state from Hermes Agent.

Provides both the conceptual model and practical estimation
methods for each K-vector dimension.

Note: Some Hermes APIs are only available from within the agent
session, not from standalone Python scripts. The collector
provides estimation methods that can run in either context.
"""
import math
import time
from collections import deque
from typing import Optional, List, Dict, Any


class KVectorCollector:
    """
    Collect and maintain K-vector state for the K-Aware Orchestrator.

    Tracks running statistics for dimensions that need historical data
    (error rates, retry counts, etc.) using sliding windows.
    """

    DIMENSION_NAMES = [
        'n_active_tasks',
        'n_parallel_agents',
        'task_depth_mean',
        'context_token_frac',
        'memory_retrieval_rate',
        'cross_agent_messages',
        'error_rate_1h',
        'retry_count',
        'user_interruption_rate',
    ]

    def __init__(self, window_hours: float = 1.0):
        self.window_hours = window_hours
        self.window_seconds = window_hours * 3600

        # Sliding windows for time-series dimensions
        self.error_log: deque = deque()       # (timestamp, 1.0 for error)
        self.tool_log: deque = deque()        # (timestamp, 1.0 for call)
        self.retry_log: deque = deque()       # (timestamp, 1.0 for retry)
        self.interrupt_log: deque = deque()   # (timestamp, 1.0 for interrupt)
        self.search_log: deque = deque()      # (timestamp, 1.0 for search)
        self.msg_log: deque = deque()         # (timestamp, 1.0 for message)

        # Context proxy — char-based token estimate
        self.context_char_len: int = 0
        self.context_samples: int = 0
        self.CHARS_PER_TOKEN: int = 4          # ~4 chars/token (conservative)
        self.estimated_max_tokens: int = 8000  # typical Hermes context limit
        self.estimated_max_calls: int = 100    # fallback proxy
        self.tool_call_count: int = 0

        # K-vector history for task depth estimation
        self.task_history: deque = deque(maxlen=50)

    # ============================================================
    # Event recording — call these when events occur
    # ============================================================

    def record_tool_call(self):
        """Record a tool call (success or failure)."""
        self.tool_log.append((time.time(), 1.0))
        self.tool_call_count += 1
        self._prune(self.tool_log)

    def record_context(self, context_text: str):
        """
        Record actual conversation context for token estimation.

        Uses character length as a token proxy (~4 chars/token).
        More accurate than tool_call_count proxy.
        Call this every turn from the Hermes agent session.
        """
        self.context_char_len += len(context_text)
        self.context_samples += 1

    def record_error(self):
        """Record a tool failure."""
        self.error_log.append((time.time(), 1.0))
        self.tool_log.append((time.time(), 1.0))
        self._prune(self.error_log)
        self._prune(self.tool_log)

    def record_retry(self):
        """Record a retry."""
        self.retry_log.append((time.time(), 1.0))
        self._prune(self.retry_log)

    def record_user_interruption(self):
        """Record user interrupting while agent is working."""
        self.interrupt_log.append((time.time(), 1.0))
        self._prune(self.interrupt_log)

    def record_search(self):
        """Record a session_search / memory retrieval."""
        self.search_log.append((time.time(), 1.0))
        self._prune(self.search_log)

    def record_agent_message(self):
        """Record a cross-agent message (delegate_task interaction)."""
        self.msg_log.append((time.time(), 1.0))
        self._prune(self.msg_log)

    def record_task_update(self, task_info: Dict):
        """Record task state update for depth estimation."""
        self.task_history.append(task_info)

    # ============================================================
    # Dimension collection
    # ============================================================

    def collect(self,
                n_active_tasks: int = 0,
                n_parallel_agents: int = 0,
                task_depth_mean: Optional[float] = None,
                context_token_frac: Optional[float] = None,
                override_context: bool = False) -> List[float]:
        """
        Collect full 9-dim K-vector.

        Args:
            n_active_tasks: Current active task count
            n_parallel_agents: Current parallel agent count
            task_depth_mean: Override task depth (auto-estimate if None)
            context_token_frac: Override context usage (auto-estimate if None)
            override_context: If True, use override values even for auto dimensions

        Returns:
            9-element list: [n_active, n_parallel, depth, context,
                           memory_rate, messages, error_rate, retries, interrupts]
        """
        now = time.time()

        # 1. n_active_tasks (from caller)
        d1 = max(0, n_active_tasks)

        # 2. n_parallel_agents (from caller)
        d2 = max(0, n_parallel_agents)

        # 3. task_depth_mean (auto or override)
        if task_depth_mean is not None:
            d3 = max(0.0, float(task_depth_mean))
        else:
            d3 = self._estimate_task_depth()

        # 4. context_token_frac (char-based token estimate, fallback to tool calls)
        if context_token_frac is not None:
            d4 = max(0.0, min(1.0, float(context_token_frac)))
        elif self.context_samples > 0:
            # Use char-based token estimate (~4 chars/token)
            avg_chars_per_sample = self.context_char_len / self.context_samples
            estimated_tokens = avg_chars_per_sample / self.CHARS_PER_TOKEN
            d4 = min(1.0, estimated_tokens / self.estimated_max_tokens)
        elif override_context:
            d4 = 0.5  # default estimate
        else:
            # Fallback: tool call count proxy
            d4 = min(1.0, self.tool_call_count / self.estimated_max_calls)

        # 5. memory_retrieval_rate (per minute, last hour)
        d5 = self._count_in_window(self.search_log, now) / max(60.0, self.window_seconds / 60.0)

        # 6. cross_agent_messages (count in last hour)
        d6 = self._count_in_window(self.msg_log, now)

        # 7. error_rate_1h
        errs = self._count_in_window(self.error_log, now)
        tools = self._count_in_window(self.tool_log, now)
        d7 = errs / max(tools, 1)

        # 8. retry_count (count in last hour)
        d8 = self._count_in_window(self.retry_log, now)

        # 9. user_interruption_rate (per hour)
        d9 = self._count_in_window(self.interrupt_log, now) / max(1.0, self.window_hours)

        return [d1, d2, d3, d4, d5, d6, d7, d8, d9]

    def _count_in_window(self, log: deque, now: float) -> float:
        """Count events in sliding window."""
        if not log:
            return 0.0
        cutoff = now - self.window_seconds
        return sum(1.0 for ts, _ in log if ts >= cutoff)

    def _prune(self, log: deque):
        """Remove expired events from a log."""
        cutoff = time.time() - self.window_seconds
        while log and log[0][0] < cutoff:
            log.popleft()

    def _estimate_task_depth(self) -> float:
        """Estimate mean task depth from task history."""
        if not self.task_history:
            return 1.0
        depths = [
            t.get('depth', 1.0) for t in self.task_history
            if isinstance(t, dict)
        ]
        return sum(depths) / len(depths) if depths else 1.0

    def reset(self):
        """Reset all state — call when starting a new session."""
        self.error_log.clear()
        self.tool_log.clear()
        self.retry_log.clear()
        self.interrupt_log.clear()
        self.search_log.clear()
        self.msg_log.clear()
        self.tool_call_count = 0
        self.context_char_len = 0
        self.context_samples = 0
        self.task_history.clear()


# ============================================================
# Quick helper for Hermes sessions
# ============================================================

def estimate_from_session(session_context: dict) -> List[float]:
    """
    Quick K-vector estimate from available session context.

    Session context should contain (approximate):
      - n_active: number of active todo items
      - n_parallel: number of active delegations
      - pages: number of pages/conversation turns
      - searches: number of session_search calls
      - errors: number of tool failures
      - retries: number of retries
      - interruptions: number of user interrupts
    """
    return [
        session_context.get('n_active', 0),
        session_context.get('n_parallel', 0),
        session_context.get('depth', 1.0),
        min(1.0, session_context.get('pages', 0) / 50.0),
        session_context.get('searches', 0) / max(1.0, session_context.get('hours', 1.0) * 60),
        session_context.get('messages', 0),
        session_context.get('errors', 0) / max(1, session_context.get('total_calls', 1)),
        session_context.get('retries', 0),
        session_context.get('interruptions', 0) / max(1.0, session_context.get('hours', 1.0)),
    ]


# ============================================================
# K-Vector Formatting
# ============================================================

def format_k_vector(k_raw: list) -> str:
    """Pretty-print a K-vector for logging."""
    names = KVectorCollector.DIMENSION_NAMES
    lines = []
    for name, val in zip(names, k_raw):
        if isinstance(val, float):
            lines.append(f"  {name:30s} {val:.4f}")
        else:
            lines.append(f"  {name:30s} {val}")
    return '\n'.join(lines)


def short_format(k_raw: list) -> str:
    """One-line K-vector format for compact logging."""
    return f"[{','.join(f'{v:.2f}' if isinstance(v, float) else str(v) for v in k_raw)}]"
