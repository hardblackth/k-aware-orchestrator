"""
THM Metrics Engine — Core Computational Module
================================================
Pure Python implementation of all metrics used in the K-Aware Orchestrator.

No external dependencies required (stdlib only).

Metrics:
  - C_K: Local Intrinsic Dimension via MLE (Levina-Bickel)
  - rate_op: Euclidean distance (PCA-projected fallback)
  - T_ops: Dual-timescale contrast
  - gamma: Structural decay rate from K_eq

Usage:
    from metrics import THMMonitor
    monitor = THMMonitor(window_size=20)
    result = monitor.update(k_raw_vector)
"""

import math
from collections import deque
from typing import Optional, List, Tuple, Dict, Any


# ============================================================
# MATH HELPERS
# ============================================================

def vec_norm(v: list) -> float:
    """L2 norm of a vector."""
    return math.sqrt(sum(x * x for x in v))


def vec_distance(a: list, b: list) -> float:
    """Euclidean distance between two vectors."""
    return math.sqrt(sum((x - y) * (x - y) for x, y in zip(a, b)))


def vec_mean(vecs: list) -> list:
    """Element-wise mean of a list of vectors."""
    n = len(vecs)
    if n == 0:
        return []
    d = len(vecs[0])
    return [sum(v[i] for v in vecs) / n for i in range(d)]


# ============================================================
# METRIC: C_K (Local Intrinsic Dimension via MLE)
# ============================================================

def compute_C_K(W_t: list, k: int = 5) -> Optional[float]:
    """
    LID via Maximum Likelihood Estimator (Levina-Bickel).

    Args:
        W_t: Sliding window of K-vectors (list of lists)
        k: Number of nearest neighbors (default: 5)

    Returns:
        Estimated LID, or None if degenerate/insufficient data

    Degeneracy guards:
      - len(W_t) < k + 2 → insufficient data
      - All points identical → None
      - r_max <= 0 → None
      - LID out of [0, 2*ambient_dim] → None
    """
    if len(W_t) < k + 2:
        return None

    first = W_t[0]
    if all(vec_distance(row, first) < 1e-3 for row in W_t):
        return None

    query = W_t[-1]
    dists = sorted(vec_distance(query, ref) for ref in W_t[:-1])
    dists = dists[:k]

    if dists[-1] <= 0:
        return None

    r_max = dists[-1]
    log_ratios = [math.log(r_max / max(d, 1e-10)) for d in dists[:-1]]

    if not log_ratios or abs(sum(log_ratios)) < 1e-10:
        return None

    lid = 1.0 / (sum(log_ratios) / len(log_ratios))
    ambient_dim = len(W_t[0])

    if lid < 0 or lid > ambient_dim * 2:
        return None

    return lid


# ============================================================
# METRIC: ‖dK/dt‖_op (Operational Rate of Change)
# ============================================================

def compute_rate_op(K_t: list, K_t1: list, W_t1: list = None) -> float:
    """
    Rate of structural change — Euclidean distance between consecutive K-vectors.

    Uses raw Euclidean distance (PCA projection requires eigendecomposition
    which is not practical without numpy). The spec allows fallback to raw
    Euclidean when PCA is unavailable or degenerate.

    Args:
        K_t: Current K-vector
        K_t1: Previous K-vector
        W_t1: Previous window (unused in pure Python fallback)

    Returns:
        Euclidean distance between K_t and K_t1
    """
    return vec_distance(K_t, K_t1)


# ============================================================
# METRIC: T_ops (Operational Temporal Density)
# ============================================================

def compute_T_ops(rate_op_history: list,
                  tau_short: int = 5,
                  tau_long: int = 20) -> float:
    """
    Dual-timescale contrast on rate_op history.

    T_ops = (mean_short - mean_long) / (mean_long + epsilon)

    Interpretation:
      >> 0: Acceleration → approaching Critical
      ≈ 0:  Steady → stable
      << 0: Deceleration → approaching Frozen

    Returns 0.0 if insufficient data (< tau_long).
    """
    if len(rate_op_history) < tau_long:
        return 0.0

    mean_short = sum(rate_op_history[-tau_short:]) / tau_short
    mean_long = sum(rate_op_history[-tau_long:]) / tau_long
    eps = 1e-8

    return (mean_short - mean_long) / (mean_long + eps)


# ============================================================
# METRIC: γ (Structural Decay Rate)
# ============================================================

def compute_gamma(K_t: list, K_t1: list, K_eq: Optional[list]) -> Optional[float]:
    """
    Structural decay rate — rate of departure from equilibrium K_eq.

    γ = (dist(K_t, K_eq) - dist(K_t1, K_eq)) / (||K_eq|| + epsilon)

    Returns None if K_eq is None (baseline not established yet).
    """
    if K_eq is None:
        return None

    dist_t = vec_distance(K_t, K_eq)
    dist_t1 = vec_distance(K_t1, K_eq)
    dist_scale = vec_norm(K_eq) + 1e-4

    return (dist_t - dist_t1) / dist_scale


# ============================================================
# NORMALIZER
# ============================================================

class KNormalizer:
    """
    Running min-max normalization with percentile-based range.

    Uses P5-P95 percentile to be robust to outliers.
    Baseline window: ≥ 20 samples before normalization activates.
    Returns raw values before baseline is established.
    """

    def __init__(self, baseline_window: int = 100):
        self.history: List[list] = []
        self.max_window = baseline_window
        self.min_vals: Optional[list] = None
        self.max_vals: Optional[list] = None

    def update(self, k_raw: list):
        """Record a new K-vector and recompute percentiles."""
        self.history.append(k_raw)
        if len(self.history) > self.max_window:
            self.history.pop(0)

        if len(self.history) >= 20:
            d = len(k_raw)
            n = len(self.history)
            sorted_vals = [
                sorted(h[i] for h in self.history) for i in range(d)
            ]
            p5_idx = max(0, int(n * 0.05))
            p95_idx = min(n - 1, int(n * 0.95))
            self.min_vals = [v[p5_idx] for v in sorted_vals]
            self.max_vals = [v[p95_idx] for v in sorted_vals]

    def normalize(self, k_raw: list) -> list:
        """Normalize a K-vector to [0, 1] or return raw if no baseline."""
        if self.min_vals is None or self.max_vals is None:
            return list(k_raw)

        result = []
        for v, mn, mx in zip(k_raw, self.min_vals, self.max_vals):
            rng = mx - mn + 1e-8
            result.append(max(0.0, min(1.0, (v - mn) / rng)))
        return result


# ============================================================
# GAMMA ESTIMATOR (K_eq baseline)
# ============================================================

class GammaEstimator:
    """
    Estimate structural decay rate γ.

    Collects K-vectors from Active regime to build K_eq baseline.
    K_eq = running mean of Active regime vectors.
    Requires ≥ 50 Active samples before γ estimates are reliable.
    Supports save/load for cross-session bootstrap.
    """

    def __init__(self, min_active_samples: int = 50):
        self.active_history: List[list] = []
        self.K_eq: Optional[list] = None
        self.min_samples = min_active_samples

    def update_active(self, K_t: list, regime: str):
        """Record K-vector during Active regime to build K_eq."""
        if regime == 'Active':
            self.active_history.append(K_t)
            if len(self.active_history) >= self.min_samples:
                self.K_eq = vec_mean(self.active_history)

    def compute_gamma(self, K_t: list, K_t1: list) -> Optional[float]:
        """Compute γ using stored K_eq."""
        return compute_gamma(K_t, K_t1, self.K_eq)

    @property
    def is_calibrated(self) -> bool:
        """True if K_eq baseline is established."""
        return self.K_eq is not None

    def get_K_eq(self) -> Optional[list]:
        """Get current K_eq vector for saving."""
        return self.K_eq

    def set_K_eq(self, K_eq: list):
        """
        Restore K_eq from saved data (cross-session bootstrap).
        Sets the baseline directly, skipping the 50-sample wait.
        Call this before the first update in a new session.
        """
        self.K_eq = list(K_eq)
        # Mark as calibrated by filling history with copies
        # (so is_calibrated and full classifier work immediately)
        self.active_history = [list(K_eq) for _ in range(self.min_samples)]


# ============================================================
# CLASSIFICATION
# ============================================================

def classify_regime(T_ops: float, C_K: Optional[float],
                    gamma: Optional[float], rate_op: float,
                    n_active: int) -> str:
    """
    Priority-based regime classification.

    Priority order (most specific first):
      1. Turbulent: |T_ops| > 2.0 AND rate_op > 1.5
      2. Decayed:   gamma > 0.15
      3. Frozen:    n_active > 0 AND |gamma| < 0.1 AND rate_op < 0.01 AND C_K < 3
      4. Critical:  T_ops > 0.5 AND (C_K > 5 OR C_K is None)
      5. Active:    (default)
    """
    # 1. Turbulent
    if abs(T_ops) > 2.0 and rate_op > 1.5:
        return 'Turbulent'

    # 2. Decayed
    if gamma is not None and gamma > 0.15:
        return 'Decayed'

    # 3. Frozen (requires active tasks — idle ≠ frozen)
    if (n_active > 0
            and gamma is not None
            and abs(gamma) < 0.1
            and abs(rate_op) < 0.01
            and (C_K is None or C_K < 3)):
        return 'Frozen'

    # 4. Critical
    if T_ops > 0.5 and (C_K is None or C_K > 5):
        return 'Critical'

    # 5. Default
    return 'Active'


def classify_fallback(T_ops: float, gamma: Optional[float],
                      rate_op: float, n_active: int) -> str:
    """
    Fallback heuristic when C_K is unavailable (w < 20 samples).

    Uses simpler thresholds that don't require manifold estimation.
    """
    if gamma is not None and gamma > 0.15:
        return 'Decayed'
    if abs(rate_op) < 0.01 and n_active > 0:
        return 'Frozen'
    if n_active > 10 and rate_op > 0.5:
        return 'Turbulent'
    if T_ops > 0.3:
        return 'Critical'
    return 'Active'


def estimate_confidence(regime: str, T_ops: float,
                        gamma: Optional[float], rate_op: float,
                        C_K: Optional[float]) -> float:
    """
    Estimate how confident the classification is.

    Based on distance from decision boundaries.
    Range: [0.5, 1.0] — 0.5 = on boundary, 1.0 = far from boundary.
    """
    if regime == 'Decayed':
        if gamma is None:
            return 0.5
        margin = (gamma - 0.15) / 0.85
        return max(0.5, min(1.0, 0.5 + 0.5 * margin))

    elif regime == 'Frozen':
        if gamma is None:
            return 0.5
        gamma_conf = 1.0 - min(abs(gamma) / 0.1, 1.0)
        rate_conf = 1.0 - min(rate_op / 0.01, 1.0)
        return max(0.5, min(1.0, 0.5 + 0.25 * (gamma_conf + rate_conf)))

    elif regime == 'Critical':
        margin = (T_ops - 0.5) / 1.5
        return max(0.5, min(1.0, 0.5 + 0.5 * margin))

    elif regime == 'Turbulent':
        t_margin = (abs(T_ops) - 2.0) / 2.0
        return max(0.5, min(1.0, 0.5 + 0.5 * t_margin))

    else:  # Active
        t_safe = 1.0 - min(abs(T_ops) / 0.5, 1.0)
        return max(0.5, min(1.0, 0.5 + 0.5 * t_safe))


# ============================================================
# ACTION MAPPING
# ============================================================

REGIME_ACTIONS = {
    'Active': ['DELEGATE_NORMAL'],
    'Critical': ['SERIALIZE', 'REDUCE_PARALLEL', 'FOCUS'],
    'Turbulent': ['PAUSE_ALL', 'ROOT_CAUSE_ANALYSIS', 'NOTIFY'],
    'Frozen': ['ESCALATE', 'CHANGE_APPROACH', 'REQUEST_CLARIFICATION'],
    'Decayed': ['CHECKPOINT', 'COMPRESS_CONTEXT', 'PAUSE_NON_CRITICAL'],
}

EMERGENCY_ACTION = 'EMERGENCY_CHECKPOINT'


def get_actions(regime: str, gamma: Optional[float]) -> list:
    """Get Hermes actions for regime, with gamma override."""
    actions = list(REGIME_ACTIONS.get(regime, ['DELEGATE_NORMAL']))
    if gamma is not None and gamma > 0.7:
        actions.insert(0, EMERGENCY_ACTION)
    return actions


# ============================================================
# THM MONITOR (Main Class)
# ============================================================

class THMMonitor:
    """
    Maintains sliding window, computes metrics, classifies regime.

    Usage:
        monitor = THMMonitor(window_size=20)
        result = monitor.update(K_raw_vector)

    The update() method returns a dict with regime, confidence,
    trend, metrics, and recommended actions.
    """

    def __init__(self, window_size: int = 20):
        self.window_size = window_size
        self.K_history: deque = deque(maxlen=window_size * 2)
        self.rate_op_history: List[float] = []
        self.normalizer = KNormalizer()
        self.gamma_est = GammaEstimator()

        # History for analysis
        self.C_K_history: List[Optional[float]] = []
        self.T_ops_history: List[float] = []
        self.gamma_history: List[Optional[float]] = []
        self.regime_history: List[str] = []

    def update(self, K_raw: list, override_classify: bool = False) -> Dict[str, Any]:
        """
        Process a new K-vector and return full monitor output.

        Args:
            K_raw: Raw K-vector (9 dimensions, unnormalized)
            override_classify: If True, force use of classify_regime even
                              when C_K is None (for testing)

        Returns:
            dict with: regime, confidence, trend, metrics, actions
        """
        # Normalize
        self.normalizer.update(K_raw)
        K_t = self.normalizer.normalize(K_raw)
        self.K_history.append(K_t)

        # Get previous K
        K_t1 = None
        if len(self.K_history) >= 2:
            K_t1 = list(self.K_history)[-2]

        # Build window for C_K
        K_list = list(self.K_history)
        W_t = K_list[-self.window_size:] if len(K_list) >= self.window_size else K_list

        # Compute C_K
        C_K = compute_C_K(W_t, k=5)
        self.C_K_history.append(C_K)

        # Compute rate_op
        if K_t1 is not None:
            rate_op = compute_rate_op(K_t, K_t1)
        else:
            rate_op = 0.0
        self.rate_op_history.append(rate_op)

        # Compute T_ops
        T_ops = compute_T_ops(self.rate_op_history)
        self.T_ops_history.append(T_ops)

        # Classify current regime (for gamma estimator baseline)
        n_active = int(round(K_raw[0])) if K_raw else 0
        current_regime = self._classify(C_K, T_ops, rate_op, n_active, override_classify)
        self.regime_history.append(current_regime)

        # Update gamma estimator with Active regime data
        self.gamma_est.update_active(K_t, current_regime)

        # Compute gamma
        gamma = None
        if K_t1 is not None:
            gamma = self.gamma_est.compute_gamma(K_t, K_t1)
        self.gamma_history.append(gamma)

        # Re-classify with gamma included
        final_regime = self._classify(C_K, T_ops, gamma, rate_op, n_active, override_classify)
        self.regime_history[-1] = final_regime

        # Actions
        actions = get_actions(final_regime, gamma)

        return {
            'regime': final_regime,
            'confidence': estimate_confidence(final_regime, T_ops, gamma, rate_op, C_K),
            'trend': self._estimate_trend(),
            'metrics': {
                'C_K': C_K,
                'T_ops': T_ops,
                'gamma': gamma,
                'rate_op': rate_op
            },
            'actions': actions
        }

    def _classify(self, C_K: Optional[float], T_ops: float,
                  gamma: Optional[float], rate_op: float,
                  n_active: int, force_full: bool = False) -> str:
        """Choose classifier based on data availability."""
        if len(self.K_history) >= 22 or force_full:
            return classify_regime(T_ops, C_K, gamma, rate_op, n_active)
        else:
            return classify_fallback(T_ops, gamma, rate_op, n_active)

    def _estimate_trend(self) -> str:
        """Estimate trend direction from recent T_ops history."""
        recent = self.T_ops_history[-5:] if len(self.T_ops_history) >= 5 else self.T_ops_history
        if not recent:
            return 'STABLE'
        avg = sum(recent) / len(recent)
        if avg > 0.3:
            return 'ACCELERATING'
        elif avg < -0.3:
            return 'DECELERATING'
        else:
            return 'STABLE'

    def get_summary(self) -> Dict[str, Any]:
        """Get current state summary."""
        return {
            'n_samples': len(self.K_history),
            'n_active': int(round(list(self.K_history)[-1][0])) if self.K_history else 0,
            'gamma_calibrated': self.gamma_est.is_calibrated,
            'classifier': 'FULL' if len(self.K_history) >= 22 else 'FALLBACK',
            'current_regime': self.regime_history[-1] if self.regime_history else 'Unknown'
        }

    def reset(self):
        """Reset all state. Use when starting a new session."""
        self.K_history.clear()
        self.rate_op_history.clear()
        self.C_K_history.clear()
        self.T_ops_history.clear()
        self.gamma_history.clear()
        self.regime_history.clear()
        self.normalizer = KNormalizer()
        self.gamma_est = GammaEstimator()
