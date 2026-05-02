"""
AutoOrchestrator — Turn-key K-Aware Orchestration for Hermes Agent

Wraps KVectorCollector + THMMonitor + Checkpoint into a single
before_turn() / after_turn() interface. Auto-saves/loads K_eq
baseline across sessions for zero cold start.

v1.2 — New features:
  - Phase1Checker: epistemic conflict + capability match before delegation
  - interpret_actions(): structured action signals (no tool calls)
  - Auto-detect trivial task → bypass K-Aware (zero overhead)
  - Cooldown timer to prevent metric bias from rapid turns

Usage (in Hermes agent session):
    from auto_orchestrator import AutoOrchestrator

    orch = AutoOrchestrator()

    # Every turn — ONE call:
    result = orch.before_turn(
        context_text=current_conversation,
        n_active=len(pending_todos),
        n_parallel=len(active_delegations),
    )

    # Use interpret_actions() to get structured signals:
    action = orch.interpret_actions(result)
    if action['action'] == 'PAUSE_ALL':
        # Hermes session: clarify("⚠️ ...")
    elif action['action'] == 'SERIALIZE':
        # one task at a time
"""

import json
import os
import sys
import time
import math
from collections import deque
from typing import Optional, List, Tuple, Dict, Any

# Resolve paths to sibling skills dynamically
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_SKILL_ROOT = os.path.dirname(_SCRIPT_DIR)               # .../k-aware-orchestrator
_SKILLS_DIR = os.path.dirname(os.path.dirname(_SKILL_ROOT))  # .../skills

_METRICS_PATH = os.path.join(_SKILLS_DIR, 'mlops', 'thm-metrics-engine', 'scripts')
_COLLECTOR_PATH = os.path.join(_SKILLS_DIR, 'mlops', 'k-vector-collector', 'scripts')
_CHECKPOINT_PATH = os.path.join(_SKILLS_DIR, 'devops', 'checkpoint-protocol', 'scripts')

for _p in [_METRICS_PATH, _COLLECTOR_PATH, _CHECKPOINT_PATH]:
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

from metrics import THMMonitor
from collector import KVectorCollector
from checkpoint import checkpoint, format_memory_entry, classify_checkpoint_type


# ============================================================
# CONSTANTS
# ============================================================

DEFAULT_EQ_PATH = os.path.join(
    os.path.expanduser('~'), '.hermes', 'k_eq_baseline.json'
)

# Cooldown: skip K-vector update if last update was < this many seconds ago
DEFAULT_COOLDOWN_S = 5.0

# Trivial task auto-detect thresholds
_TRIVIAL_MAX_CHARS = 80       # ≤80 chars = trivial
_TRIVIAL_MAX_LINES = 2        # ≤2 lines = trivial
_TRIVIAL_MAX_ACTIVE = 1       # ≤1 active task = trivial


# ============================================================
# PHASE 1 CHECKER — Epistemic conflict + compatibility
# ============================================================

class Phase1Checker:
    """
    Phase 1: Task intake checks — run BEFORE delegating a task.

    Four checks:
      1. Capability match — does the agent have the skills for this task?
      2. Resource — is the agent currently overloaded?
      3. Valid state — is the task in the valid configuration set V?
      4. Epistemic conflict proxy — would this task spike C_K?

    Usage:
        checker = Phase1Checker()
        ok, reason = checker.check_compatibility(
            task_caps={'python', 'git'},
            agent_caps={'python', 'git', 'sql'},
            n_active=2,  # max_load=5 from constructor
        )
    """

    def __init__(self, max_load: int = 5, config_V: set = None):
        self.max_load = max_load
        # config_V = set of valid task capability combinations (ontology level A).
        # Each element is a frozenset of capabilities that form a valid task config.
        # E.g. {frozenset({'python', 'git'}), frozenset({'docker', 'deploy'})}
        self.config_V = config_V or set()
        # Normalize: if caller passes strings, wrap in frozenset
        self._normalized_V = self._normalize_config_V(self.config_V)

    @staticmethod
    def _normalize_config_V(raw_V) -> set:
        """Convert any V representation to set of frozensets."""
        if not raw_V:
            return set()
        normalized = set()
        for item in raw_V:
            if isinstance(item, frozenset):
                normalized.add(item)
            elif isinstance(item, set):
                normalized.add(frozenset(item))
            elif isinstance(item, str):
                # Single capability: treat as {item}
                normalized.add(frozenset({item}))
            else:
                # Assume iterable of strings
                normalized.add(frozenset(item))
        return normalized

    def check_compatibility(self,
                            task_caps: set,
                            agent_caps: set,
                            n_active: int = 0,
                            config_V: set = None) -> tuple:
        """
        Run all 4 Phase 1 checks.

        Args:
            task_caps: Set of capabilities the task requires
                       (e.g. {'python', 'web', 'api_design'})
            agent_caps: Set of capabilities the agent has
                        (e.g. {'python', 'git', 'sql', 'terminal'})
            n_active: Number of currently active tasks
            config_V: Optional override for valid task configuration set.
                      Format: iterable of sets, e.g. [{'python', 'git'}, {'docker'}]

        Returns:
            (True, 'COMPATIBLE') or (False, '<REASON>')
        """
        v = config_V if config_V is not None else self._normalized_V
        if config_V is not None:
            v = self._normalize_config_V(config_V)

        # 1. Capability match
        if task_caps and agent_caps:
            if not task_caps.issubset(agent_caps):
                missing = task_caps - agent_caps
                return False, f'CAPABILITY_MISMATCH:{",".join(sorted(missing))}'

        # 2. Resource
        if n_active >= self.max_load:
            return False, f'AGENT_OVERLOAD:{n_active}/{self.max_load}'

        # 3. Valid state (task capability set ∈ V)
        if v and task_caps:
            task_key = frozenset(task_caps)
            if task_key not in v:
                return False, 'INVALID_STATE:task_not_in_V'

        # 4. Epistemic conflict proxy
        if n_active >= self.max_load - 1:
            return False, 'EPISTEMIC_CONFLICT:load_near_max'

        return True, 'COMPATIBLE'


# ============================================================
# ACTION INTERPRETER — Structured signals (no direct tool calls)
# ============================================================

def interpret_actions(result: dict) -> dict:
    """
    Convert K-Aware result dict into a structured action signal.

    CRITICAL: This function NEVER calls agent tools (clarify, todo, etc.)
    — it returns structured dicts that the Hermes session layer interprets.

    Returns:
        {
            'action': str,       # PROCEED | SERIALIZE | PAUSE_ALL |
                                 # CHECKPOINT | EMERGENCY_CHECKPOINT |
                                 # ESCALATE | BYPASS
            'regime': str,
            'signal': str or None,  # 'clarify_required' when user input needed
            'message': str or None, # User-facing message (if any)
        }
    """
    actions = result.get('actions', [])
    regime = result.get('regime', 'Active')
    metrics = result.get('metrics', {})

    if 'EMERGENCY_CHECKPOINT' in actions:
        return {
            'action': 'EMERGENCY_CHECKPOINT',
            'regime': regime,
            'signal': None,
            'message': f"⚠️ γ={metrics.get('gamma', '?'):.3f} — ต้อง checkpoint ทันที",
        }

    if 'PAUSE_ALL' in actions:
        return {
            'action': 'PAUSE_ALL',
            'regime': regime,
            'signal': 'clarify_required',
            'message': '⚠️ ระบบกำลัง Turbulent — ต้องการให้ pause หรือ continue?',
        }

    if 'SERIALIZE' in actions:
        return {
            'action': 'SERIALIZE',
            'regime': regime,
            'signal': None,
            'message': '→ Serialize: ทำทีละ task (ลด parallel)',
        }

    if 'CHECKPOINT' in actions:
        return {
            'action': 'CHECKPOINT',
            'regime': regime,
            'signal': None,
            'message': '→ ต้องการ checkpoint — decay detected',
        }

    if 'ESCALATE' in actions:
        return {
            'action': 'ESCALATE',
            'regime': regime,
            'signal': 'clarify_required',
            'message': '⚠️ ระบบ Frozen — task ค้าง ต้องการคำแนะนำ',
        }

    return {
        'action': 'PROCEED',
        'regime': regime,
        'signal': None,
        'message': None,
    }


# ============================================================
# TRIVIAL TASK DETECTOR
# ============================================================

def _is_trivial(context_text: str = None, n_active: int = 0) -> bool:
    """
    Auto-detect trivial tasks — short Q&A, no delegation needed.

    Returns True if ALL conditions met:
      - context_text is short (< 80 chars, < 3 lines)
      - n_active ≤ 1
    """
    if n_active > _TRIVIAL_MAX_ACTIVE:
        return False
    if context_text is None:
        return False
    text = context_text.strip()
    if len(text) < 5:  # too short to be real input
        return True
    if len(text) > _TRIVIAL_MAX_CHARS:
        return False
    if text.count('\n') >= _TRIVIAL_MAX_LINES:
        return False
    return True


# ============================================================
# THM PREDICTOR — Predictive Regime Detection
# ============================================================

class THMPredictor:
    """
    Predict future regime based on historical metric trends.

    Uses linear extrapolation on T_ops and rate_op history to estimate
    when the system will transition to a different regime.

    Usage:
        predictor = THMPredictor()
        pred = predictor.predict(t_ops_history, rate_op_history, ck_history,
                                  gamma, n_active)
        # pred = {
        #     'predicted_regime': 'Critical',
        #     'time_to_transition': 3.2,   # estimated turns
        #     'confidence': 0.72,
        #     'suggested_action': 'reduce parallel NOW',
        #     'trend_description': 'T_ops accelerating rapidly'
        # }
    """

    # Thresholds (same as main classifier)
    T_OPS_CRITICAL = 0.5
    T_OPS_TURBULENT = 2.0
    RATE_TURBULENT = 1.5
    GAMMA_DECAYED = 0.15
    GAMMA_FROZEN_MAX = 0.1
    RATE_FROZEN = 0.01

    def predict(self,
                t_ops_history: List[float],
                rate_op_history: List[float],
                ck_history: List[Optional[float]],
                gamma: Optional[float],
                n_active: int,
                horizon: int = 5) -> Dict[str, Any]:
        """
        Predict regime `horizon` turns ahead.

        Args:
            t_ops_history: Recent T_ops values
            rate_op_history: Recent rate_op values
            ck_history: Recent C_K values
            gamma: Current γ value
            n_active: Current active task count
            horizon: Number of turns to predict ahead (default: 5)

        Returns:
            dict with predicted_regime, time_to_transition, confidence,
                  suggested_action, trend_description
        """
        if len(t_ops_history) < 3:
            return self._empty_prediction('need more data')

        t_ops = t_ops_history[-1]
        rate_op = rate_op_history[-1] if rate_op_history else 0.0
        ck = ck_history[-1] if ck_history else None

        # Trend: T_ops slope over last 5 points
        t_ops_slope = self._linear_slope(t_ops_history[-5:])
        rate_slope = self._linear_slope(rate_op_history[-5:]) if len(rate_op_history) >= 5 else 0.0

        # Predicted values N turns ahead
        t_ops_future = t_ops + t_ops_slope * horizon
        rate_future = rate_op + rate_slope * horizon

        # Classify predicted state
        regime, confidence, action, desc = self._classify_predicted(
            t_ops_future, rate_future, ck, gamma, n_active, t_ops_slope
        )

        # Time to transition (if currently in a different regime)
        time_to = self._estimate_transition_time(
            t_ops, t_ops_slope, t_ops_future, regime
        )

        return {
            'predicted_regime': regime,
            'time_to_transition': time_to,
            'confidence': round(confidence, 3),
            'suggested_action': action,
            'trend_description': desc,
            'projected_metrics': {
                'T_ops': round(t_ops_future, 3),
                'rate_op': round(rate_future, 3),
            }
        }

    def _linear_slope(self, values: List[float]) -> float:
        """Simple linear regression slope over last N points."""
        n = len(values)
        if n < 2:
            return 0.0
        xs = list(range(n))
        mean_x = (n - 1) / 2.0
        mean_y = sum(values) / n
        num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, values))
        den = sum((x - mean_x) ** 2 for x in xs)
        if den == 0:
            return 0.0
        return num / den

    def _classify_predicted(self, t_ops_f, rate_f, ck, gamma,
                            n_active, slope) -> Tuple[str, float, str, str]:
        """Classify predicted metrics and generate suggestion."""
        # Turbulent check
        if abs(t_ops_f) > self.T_OPS_TURBULENT and rate_f > self.RATE_TURBULENT:
            conf = min(1.0, 0.5 + 0.25 * (abs(t_ops_f) - 2.0))
            return ('Turbulent', conf,
                    'PAUSE_ALL: หยุดทันที — กำลังเข้าสู่ Turbulent',
                    f'T_ops กำลังพุ่งขึ้น {slope:.3f}/turn — near Turbulent')

        # Decayed check
        if gamma is not None and gamma > self.GAMMA_DECAYED:
            conf = min(1.0, 0.5 + 0.5 * (gamma - 0.15) / 0.85)
            return ('Decayed', conf,
                    'CHECKPOINT: γ เกิน 0.15 — checkpoint ก่อน',
                    f'γ={gamma:.3f} — structure กำลัง decay')

        # Critical check
        if t_ops_f > self.T_OPS_CRITICAL and (ck is None or ck > 5):
            conf = min(1.0, 0.5 + 0.3 * (t_ops_f - 0.5))
            return ('Critical', conf,
                    'SERIALIZE: ลด parallel — กำลังเข้า Critical',
                    f'T_ops slope={slope:.3f}/turn — accelerating toward Critical')

        # Frozen check
        if (n_active > 0 and gamma is not None
                and abs(gamma) < self.GAMMA_FROZEN_MAX
                and abs(rate_f) < self.RATE_FROZEN
                and (ck is None or ck < 3)):
            return ('Frozen', 0.6,
                    'ESCALATE: task ค้าง — เปลี่ยน approach',
                    f'rate_op≈0, tasks={n_active} — approaching Frozen')

        return ('Active', 0.7,
                'PROCEED: continue normally',
                f'T_ops stable ({t_ops_f:.2f}), no anomalies')

    def _estimate_transition_time(self, t_ops_now, slope, t_ops_future,
                                   predicted_regime) -> Optional[float]:
        """Estimate turns until regime transition."""
        if abs(slope) < 0.001 or predicted_regime == 'Active':
            return None

        # How many turns until T_ops crosses a critical threshold?
        if predicted_regime == 'Critical' and slope > 0:
            turns = (self.T_OPS_CRITICAL - t_ops_now) / slope
            return max(0, round(turns, 1)) if turns > 0 else None

        if predicted_regime == 'Turbulent' and abs(slope) > 0:
            turns = (self.T_OPS_TURBULENT - abs(t_ops_now)) / abs(slope)
            return max(0, round(turns, 1)) if turns > 0 else None

        return None

    def _empty_prediction(self, reason: str) -> Dict[str, Any]:
        return {
            'predicted_regime': 'UNKNOWN',
            'time_to_transition': None,
            'confidence': 0.0,
            'suggested_action': 'PROCEED',
            'trend_description': f'Cannot predict — {reason}',
            'projected_metrics': {},
        }


# ============================================================
# AUTO CALIBRATOR — Per-user threshold tuning
# ============================================================

class AutoCalibrator:
    """
    Tune K-Aware thresholds based on user feedback accuracy.

    Tracks false positives/negatives per regime and adjusts
    thresholds to match the user's actual workload patterns.

    Storage: JSON file at ~/.hermes/k_aware_calibration.json

    Usage:
        calibrator = AutoCalibrator()
        calibrator.record_feedback('Critical', was_correct=True)
        thresholds = calibrator.get_thresholds()
        # {'t_ops_critical': 0.55, 'gamma_decayed': 0.12, ...}
    """

    DEFAULT_THRESHOLDS = {
        't_ops_critical': 0.5,
        't_ops_turbulent': 2.0,
        'rate_turbulent': 1.5,
        'gamma_decayed': 0.15,
        'gamma_frozen_max': 0.1,
        'rate_frozen': 0.01,
        'max_load': 5,
    }

    THRESHOLD_RANGES = {
        't_ops_critical': (0.2, 1.0),
        't_ops_turbulent': (1.0, 4.0),
        'rate_turbulent': (0.5, 3.0),
        'gamma_decayed': (0.05, 0.5),
        'gamma_frozen_max': (0.01, 0.3),
        'rate_frozen': (0.001, 0.1),
        'max_load': (3, 15),
    }

    def __init__(self, storage_path: str = None):
        if storage_path is None:
            storage_path = os.path.join(
                os.path.expanduser('~'), '.hermes', 'k_aware_calibration.json'
            )
        self.storage_path = storage_path
        self.thresholds = dict(self.DEFAULT_THRESHOLDS)
        self.history = deque(maxlen=200)  # feedback history
        self._n_correct = 0
        self._n_total = 0
        self._load()

    # ----------------------------------------------------------
    # Feedback Recording
    # ----------------------------------------------------------

    def record_feedback(self, regime: str, was_correct: bool,
                        metrics_snapshot: dict = None):
        """
        Record user feedback on regime classification accuracy.

        Args:
            regime: The regime that was classified
            was_correct: Whether the user agreed with the classification
            metrics_snapshot: Optional metrics at time of classification
        """
        self._n_total += 1
        if was_correct:
            self._n_correct += 1

        entry = {
            'regime': regime,
            'correct': was_correct,
            'timestamp': time.time(),
        }
        if metrics_snapshot:
            entry['metrics'] = {
                k: round(v, 4) if isinstance(v, float) else v
                for k, v in metrics_snapshot.items()
            }
        self.history.append(entry)

        # Auto-calibrate every 10 feedbacks
        if self._n_total % 10 == 0 and self._n_total >= 20:
            self._auto_calibrate()

    @property
    def accuracy(self) -> float:
        """Overall accuracy rate."""
        if self._n_total == 0:
            return 0.0
        return self._n_correct / self._n_total

    # ----------------------------------------------------------
    # Threshold Access
    # ----------------------------------------------------------

    def get_thresholds(self) -> dict:
        """Get current thresholds (merged with defaults for missing keys)."""
        result = dict(self.DEFAULT_THRESHOLDS)
        result.update(self.thresholds)
        return result

    def get_calibrated_threshold(self, key: str) -> float:
        """Get a single threshold value."""
        return self.get_thresholds().get(key, self.DEFAULT_THRESHOLDS.get(key, 0.0))

    # ----------------------------------------------------------
    # Auto-Calibration Logic
    # ----------------------------------------------------------

    def _auto_calibrate(self):
        """
        Adjust thresholds based on recent feedback patterns.

        Simple heuristic: if false positive rate > 30% for a regime,
        make that regime harder to trigger (adjust threshold).

        More sophisticated approaches (Bayesian calibration) can
        be added later.
        """
        if len(self.history) < 20:
            return

        recent = list(self.history)[-50:]  # last 50 entries

        # Count false positives per regime
        fp_by_regime = {}
        total_by_regime = {}
        for entry in recent:
            r = entry['regime']
            total_by_regime[r] = total_by_regime.get(r, 0) + 1
            if not entry['correct']:
                fp_by_regime[r] = fp_by_regime.get(r, 0) + 1

        # Adjust thresholds
        for regime, total in total_by_regime.items():
            fp_rate = fp_by_regime.get(regime, 0) / total

            if fp_rate > 0.3:
                # Too many false positives → make stricter
                self._tighten_for_regime(regime)
            elif fp_rate < 0.1 and total >= 10:
                # Very good accuracy → maybe loosen slightly
                self._loosen_for_regime(regime)

        self._save()

    def _tighten_for_regime(self, regime: str):
        """Make regime harder to trigger by adjusting thresholds."""
        if regime == 'Critical':
            self._adjust_threshold('t_ops_critical', +0.05)
        elif regime == 'Turbulent':
            self._adjust_threshold('t_ops_turbulent', +0.1)
            self._adjust_threshold('rate_turbulent', +0.1)
        elif regime == 'Decayed':
            self._adjust_threshold('gamma_decayed', +0.02)
        elif regime == 'Frozen':
            self._adjust_threshold('gamma_frozen_max', -0.01)
        elif regime == 'Active':
            pass  # Don't tighten Active — it's the default

    def _loosen_for_regime(self, regime: str):
        """Make regime slightly easier to trigger."""
        if regime == 'Critical':
            self._adjust_threshold('t_ops_critical', -0.02)
        elif regime == 'Decayed':
            self._adjust_threshold('gamma_decayed', -0.01)

    def _adjust_threshold(self, key: str, delta: float):
        """Adjust threshold within valid range."""
        current = self.get_calibrated_threshold(key)
        lo, hi = self.THRESHOLD_RANGES.get(key, (0, float('inf')))
        new_val = max(lo, min(hi, current + delta))
        self.thresholds[key] = new_val

    # ----------------------------------------------------------
    # Persistence
    # ----------------------------------------------------------

    def _save(self):
        """Save calibration data to disk."""
        try:
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
            with open(self.storage_path, 'w') as f:
                json.dump({
                    'thresholds': self.thresholds,
                    'n_correct': self._n_correct,
                    'n_total': self._n_total,
                    'updated': time.time(),
                }, f, indent=2)
        except OSError:
            pass

    def _load(self):
        """Load calibration data from disk."""
        if not os.path.exists(self.storage_path):
            return
        try:
            with open(self.storage_path, 'r') as f:
                data = json.load(f)
            self.thresholds.update(data.get('thresholds', {}))
            self._n_correct = data.get('n_correct', 0)
            self._n_total = data.get('n_total', 0)
        except (json.JSONDecodeError, OSError):
            pass

    def reset(self):
        """Reset to factory defaults."""
        self.thresholds = dict(self.DEFAULT_THRESHOLDS)
        self._n_correct = 0
        self._n_total = 0
        self.history.clear()
        if os.path.exists(self.storage_path):
            try:
                os.remove(self.storage_path)
            except OSError:
                pass


# ============================================================
# AUTO ORCHESTRATOR
# ============================================================

class AutoOrchestrator:
    """
    K-Aware Orchestrator — auto mode.

    Handles:
    - K-vector collection + context recording
    - THM metrics + regime classification
    - K_eq persistence across sessions
    - Phase 1 compatibility checking
    - Cooldown to prevent metric bias
    - Auto-detect trivial tasks → bypass
    - Predictive regime detection (|horizon turns ahead)
    - Auto-calibration (per-user threshold tuning)
    - Health dashboard (markdown report)

    Usage:
        orch = AutoOrchestrator()
        result = orch.before_turn(context_text="...", n_active=3)
        action = orch.interpret_actions(result)
        pred = orch.predict()           # predictive detection
        cal = orch.record_feedback(True)  # auto-calibration
        print(orch.report())             # dashboard
    """

    def __init__(self, window_size: int = 20,
                 eq_path: str = DEFAULT_EQ_PATH,
                 cooldown_s: float = DEFAULT_COOLDOWN_S,
                 max_load: int = 5,
                 config_V: set = None,
                 calibrate_path: str = None):
        self.monitor = THMMonitor(window_size=window_size)
        self.collector = KVectorCollector()
        self.eq_path = eq_path
        self._loaded_eq = False
        self._last_update_ts = 0.0
        self._cooldown_s = cooldown_s
        self._last_result = None  # cached result during cooldown

        # Phase 1 checker
        self.phase1 = Phase1Checker(max_load=max_load, config_V=config_V)

        # Predictive detection
        self.predictor = THMPredictor()

        # Auto-calibration
        self.calibrator = AutoCalibrator(storage_path=calibrate_path)

        # Try to bootstrap K_eq from saved baseline
        self._load_k_eq()

    # ----------------------------------------------------------
    # MAIN API — call before_turn() every agent turn
    # ----------------------------------------------------------

    def before_turn(self,
                    context_text: str = None,
                    n_active: int = 0,
                    n_parallel: int = 0,
                    task_depth: float = None,
                    context_override: float = None,
                    record_tool_call: bool = True) -> dict:
        """
        ONE call to do everything before an agent action.

        Auto-detects trivial tasks → BYPASS regime (zero overhead).
        Enforces cooldown to prevent metric bias from rapid turns.

        Args:
            context_text: Full conversation text (for token estimation)
            n_active: Current pending/in-progress task count
            n_parallel: Current active delegate_task count
            task_depth: Mean task tree depth (auto if None)
            context_override: Explicit context fraction [0,1]
            record_tool_call: Whether to auto-record a tool call

        Returns:
            dict with: regime, confidence, trend, metrics, actions
        """
        # --- Auto-detect trivial tasks (BYPASS) ---
        if _is_trivial(context_text, n_active):
            return {
                'regime': 'BYPASS',
                'confidence': 1.0,
                'trend': 'STABLE',
                'metrics': {
                    'C_K': None,
                    'T_ops': 0.0,
                    'gamma': None,
                    'rate_op': 0.0
                },
                'actions': []
            }

        # --- Cooldown: skip update if too fast ---
        now = time.time()
        if self._last_update_ts > 0 and (now - self._last_update_ts) < self._cooldown_s:
            if self._last_result is not None:
                return dict(self._last_result)  # return cached (shallow copy)

        self._last_update_ts = now

        # 1. Record context (token proxy)
        if context_text is not None:
            self.collector.record_context(context_text)

        # 2. Record tool call (for error rate tracking)
        if record_tool_call:
            self.collector.record_tool_call()

        # 3. Collect K-vector
        k_raw = self.collector.collect(
            n_active_tasks=n_active,
            n_parallel_agents=n_parallel,
            task_depth_mean=task_depth,
            context_token_frac=context_override,
        )

        # 4. Monitor → compute metrics → classify regime
        result = self.monitor.update(k_raw)

        # 5. Auto-save K_eq if newly calibrated
        self._save_k_eq()

        # Cache result for cooldown
        self._last_result = result

        return result

    def after_turn(self,
                   regime: str,
                   gamma: float,
                   metrics: dict,
                   completed_tasks: list = None,
                   pending_tasks: list = None) -> dict:
        """
        Optional — run checkpoint check after each turn.

        Returns checkpoint result if needed, or NONE.
        """
        if completed_tasks is None:
            completed_tasks = []
        if pending_tasks is None:
            pending_tasks = []

        result = checkpoint(
            gamma=gamma,
            regime=regime,
            metrics=metrics,
            completed_tasks=completed_tasks,
            pending_tasks=pending_tasks,
        )
        return result

    # ----------------------------------------------------------
    # PREDICTIVE REGIME DETECTION
    # ----------------------------------------------------------

    def predict(self, horizon: int = 5) -> Dict[str, Any]:
        """
        Predict regime `horizon` turns ahead using trend extrapolation.

        Uses THMPredictor on the current metric history.
        Returns None if insufficient data (< 3 turns).

        Usage:
            pred = orch.predict(horizon=5)
            if pred['predicted_regime'] == 'Critical':
                print(pred['suggested_action'])
                # → 'SERIALIZE: ลด parallel — กำลังเข้า Critical'
        """
        t_ops_hist = list(self.monitor.T_ops_history)
        rate_hist = list(self.monitor.rate_op_history)
        ck_hist = list(self.monitor.C_K_history)
        gamma = self.monitor.gamma_history[-1] if self.monitor.gamma_history else None
        n_active = self._last_result.get('metrics', {}).get('n_active', 0) if self._last_result else 0

        return self.predictor.predict(
            t_ops_history=t_ops_hist,
            rate_op_history=rate_hist,
            ck_history=ck_hist,
            gamma=gamma,
            n_active=n_active,
            horizon=horizon,
        )

    # ----------------------------------------------------------
    # CALIBRATION FEEDBACK
    # ----------------------------------------------------------

    def record_feedback(self, was_correct: bool) -> dict:
        """
        Record user feedback on the last classification.

        Call this when the user confirms (or rejects) the regime.
        Auto-calibrates thresholds every 10 feedbacks.

        Usage:
            orch.record_feedback(was_correct=True)
            print(orch.calibrator.accuracy)
            # → 0.85 (85% accurate)

            th = orch.calibrator.get_thresholds()
            print(th['t_ops_critical'])
            # → 0.55 (calibrated from 0.5)
        """
        if self._last_result is None:
            return {'status': 'no_data', 'accuracy': self.calibrator.accuracy}

        metrics = self._last_result.get('metrics', {}).copy()
        # Ensure we have the regime in the snapshot
        metrics['regime'] = self._last_result.get('regime', 'Active')

        self.calibrator.record_feedback(
            regime=self._last_result.get('regime', 'Active'),
            was_correct=was_correct,
            metrics_snapshot=metrics,
        )
        return {
            'status': 'recorded',
            'accuracy': self.calibrator.accuracy,
            'n_feedbacks': self.calibrator._n_total,
        }

    def calibrator_summary(self) -> dict:
        """Get current calibration state."""
        return {
            'accuracy': self.calibrator.accuracy,
            'n_feedbacks': self.calibrator._n_total,
            'thresholds': self.calibrator.get_thresholds(),
            'calibrated': self.calibrator._n_total >= 20,
        }

    # ----------------------------------------------------------
    # HEALTH DASHBOARD
    # ----------------------------------------------------------

    def report(self) -> str:
        """
        Generate a markdown health dashboard for the current K-state.

        Usage:
            print(orch.report())
            # → ## K-State Report
            #    ...
        """
        if not self._last_result:
            return "*No data yet — call before_turn() first.*"

        r = self._last_result
        reg = r.get('regime', '?')
        conf = r.get('confidence', 0)
        trend = r.get('trend', 'STABLE')
        metrics = r.get('metrics', {})
        s = self.summary()
        cal = self.calibrator_summary()

        # Prediction
        pred = self.predict(horizon=5)
        pred_regime = pred.get('predicted_regime', 'UNKNOWN')
        pred_action = pred.get('suggested_action', '')
        pred_time = pred.get('time_to_transition')
        time_str = f"~{pred_time} turns" if pred_time else "not projected"
        pred_desc = pred.get('trend_description', '')

        lines = []
        lines.append(f"## K-State Report")
        lines.append(f"")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| **Regime** | {reg} (conf={conf:.0%}) |")
        lines.append(f"| **Trend** | {trend} |")
        lines.append(f"| **C_K** | {metrics.get('C_K', '—')} |")
        lines.append(f"| **T_ops** | {metrics.get('T_ops', 0):.4f} |")
        lines.append(f"| **γ** | {metrics.get('gamma', '—')} |")
        lines.append(f"| **rate_op** | {metrics.get('rate_op', 0):.4f} |")
        lines.append(f"| **Samples** | {s.get('n_samples', 0)} |")
        lines.append(f"| **Classifier** | {s.get('classifier', '?')} |")
        lines.append(f"| **K_eq** | {'✅ bootstrapped' if s.get('k_eq_bootstrapped', False) else '❌ cold start'} |")
        lines.append(f"| **γ calibrated** | {'✅' if s.get('gamma_calibrated', False) else '❌'} |")
        lines.append(f"")
        lines.append(f"### Prediction ({5}-turn horizon)")
        lines.append(f"| Field | Value |")
        lines.append(f"|-------|-------|")
        lines.append(f"| **Predicted regime** | {pred_regime} (conf={pred.get('confidence', 0):.0%}) |")
        lines.append(f"| **Time to transition** | {time_str} |")
        lines.append(f"| **Suggested action** | {pred_action} |")
        lines.append(f"| **Trend description** | {pred_desc} |")
        if pred.get('projected_metrics'):
            pm = pred['projected_metrics']
            lines.append(f"| **Projected T_ops** | {pm.get('T_ops', '—')} |")
            lines.append(f"| **Projected rate_op** | {pm.get('rate_op', '—')} |")
        lines.append(f"")
        lines.append(f"### Calibration")
        lines.append(f"| Field | Value |")
        lines.append(f"|-------|-------|")
        lines.append(f"| **Accuracy** | {cal['accuracy']:.0%} ({cal['n_feedbacks']} feedbacks) |")
        lines.append(f"| **Calibrated** | {'✅' if cal['calibrated'] else '❌ (< 20 feedbacks)'} |")

        # Show calibrated thresholds (only if different from default)
        custom = {k: v for k, v in cal['thresholds'].items()
                  if v != AutoCalibrator.DEFAULT_THRESHOLDS.get(k)}
        if custom:
            lines.append(f"| **Custom thresholds** | `{custom}` |")
        else:
            lines.append(f"| **Custom thresholds** | None (factory defaults) |")

        return '\n'.join(lines)

    # ----------------------------------------------------------
    # ACTION INTERPRETER
    # ----------------------------------------------------------

    def interpret_actions(self, result: dict = None) -> dict:
        """
        Convert latest K-Aware result into structured action signal.

        This is the SAFE way to act on regime — returns structured
        dicts for the Hermes session layer to interpret (no tool calls).

        If result is None, uses the last cached result from before_turn().
        """
        if result is None:
            result = self._last_result
        if result is None:
            return {'action': 'PROCEED', 'regime': 'Active',
                    'signal': None, 'message': None}
        return interpret_actions(result)

    # ----------------------------------------------------------
    # PHASE 1 CHECKER
    # ----------------------------------------------------------

    def check_phase1(self,
                      task_caps: set,
                      agent_caps: set = None,
                      n_active: int = 0,
                      config_V: set = None) -> tuple:
        """
        Run Phase 1 compatibility check before delegating.

        Convenience wrapper for Phase1Checker.check_compatibility().
        If agent_caps is None, only checks resource + valid state.

        Returns:
            (True, 'COMPATIBLE') or (False, '<REASON>')
        """
        caps = agent_caps or set()
        return self.phase1.check_compatibility(
            task_caps=task_caps,
            agent_caps=caps,
            n_active=n_active,
            config_V=config_V,
        )

    # ----------------------------------------------------------
    # COOLDOWN CONTROL
    # ----------------------------------------------------------

    def set_cooldown(self, seconds: float):
        """Set cooldown between K-vector updates (default: 5s)."""
        self._cooldown_s = max(0.0, seconds)

    def clear_cooldown(self):
        """Force next before_turn() to do a full update."""
        self._last_update_ts = 0.0
        self._last_result = None

    # ----------------------------------------------------------
    # K_eq Persistence
    # ----------------------------------------------------------

    def _load_k_eq(self):
        """Load K_eq baseline from disk — cross-session bootstrap."""
        if not os.path.exists(self.eq_path):
            return

        try:
            with open(self.eq_path, 'r') as f:
                data = json.load(f)
            K_eq = data.get('K_eq')
            if K_eq and len(K_eq) == 9:
                self.monitor.gamma_est.set_K_eq(K_eq)
                self._loaded_eq = True
        except (json.JSONDecodeError, OSError, TypeError):
            pass  # Corrupted file — ignore, start fresh

    def _save_k_eq(self):
        """Save K_eq baseline to disk after each update if calibrated."""
        K_eq = self.monitor.gamma_est.get_K_eq()
        if K_eq is None:
            return

        try:
            os.makedirs(os.path.dirname(self.eq_path), exist_ok=True)
            with open(self.eq_path, 'w') as f:
                json.dump({'K_eq': K_eq}, f)
        except OSError:
            pass  # Can't write — not critical

    def clear_k_eq(self):
        """Delete saved K_eq baseline (start fresh)."""
        self._loaded_eq = False
        if os.path.exists(self.eq_path):
            try:
                os.remove(self.eq_path)
            except OSError:
                pass

    @property
    def k_eq_bootstrapped(self) -> bool:
        """True if K_eq was loaded from a previous session."""
        return self._loaded_eq

    # ----------------------------------------------------------
    # Reset
    # ----------------------------------------------------------

    def reset(self):
        """Reset all state for a fresh session. Keeps saved K_eq."""
        self.monitor.reset()
        self.collector.reset()
        self.clear_cooldown()

    def reset_hard(self):
        """Reset everything including saved K_eq."""
        self.clear_k_eq()
        self.monitor.reset()
        self.collector.reset()
        self.clear_cooldown()

    # ----------------------------------------------------------
    # Summary
    # ----------------------------------------------------------

    def summary(self) -> dict:
        """Get current orchestration state summary."""
        mon = self.monitor.get_summary()
        return {
            'k_eq_bootstrapped': self.k_eq_bootstrapped,
            'n_samples': mon['n_samples'],
            'classifier': mon['classifier'],
            'regime': mon['current_regime'],
            'gamma_calibrated': mon['gamma_calibrated'],
        }
