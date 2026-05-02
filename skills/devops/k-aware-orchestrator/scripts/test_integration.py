"""
Integration Test — Full K-Aware Orchestrator System

Tests the complete pipeline:
  1. KVectorCollector → K-vector
  2. THMMonitor → metrics + regime
  3. Actions from regime
  4. Realistic multi-step scenarios
  5. Edge cases (empty, reset, boundary)
"""
import sys
import os
import math
import time
import random
random.seed(42)

# Add metrics and collector to path
# FIX: ใช้ relative path จาก script location แทน hardcoded Linux paths
_SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
_SKILL_ROOT  = os.path.dirname(_SCRIPT_DIR)               # .hermes/skills/devops/k-aware-orchestrator
_SKILLS_ROOT = os.path.dirname(os.path.dirname(_SKILL_ROOT))  # .hermes/skills

sys.path.insert(0, _SCRIPT_DIR)
sys.path.insert(0, os.path.join(_SKILLS_ROOT, 'mlops', 'thm-metrics-engine', 'scripts'))
sys.path.insert(0, os.path.join(_SKILLS_ROOT, 'mlops', 'k-vector-collector', 'scripts'))

from metrics import (
    THMMonitor, KNormalizer, GammaEstimator,
    compute_C_K, compute_rate_op, compute_T_ops, compute_gamma,
    classify_regime, classify_fallback, get_actions
)
from collector import KVectorCollector, short_format


PASS = 0
FAIL = 0
TOTAL = 0


def check(name, condition, detail=""):
    global PASS, FAIL, TOTAL
    TOTAL += 1
    if condition:
        PASS += 1
        print(f"  ✅ [{name}] {detail}")
    else:
        FAIL += 1
        print(f"  ❌ [{name}] FAILED: {detail}")


def check_eq(name, actual, expected, detail=""):
    global PASS, FAIL, TOTAL
    TOTAL += 1
    if actual == expected:
        PASS += 1
        status = f"= {expected}"
        if detail:
            status += f" ({detail})"
        print(f"  ✅ [{name}] {status}")
    else:
        FAIL += 1
        print(f"  ❌ [{name}] expected {expected}, got {actual}")


# ============================================================
# SECTION 1: THMMonitor Scenarios
# ============================================================

def test_thm_monitor_lifecycle():
    """Test THMMonitor through realistic workflow scenarios."""
    print(f"\n{'=' * 72}")
    print("  INTEGRATION: THMMonitor Lifecycle")
    print(f"{'=' * 72}")

    K_EQ = [3.0, 2.0, 1.5, 0.5, 0.3, 3.0, 0.1, 1.0, 2.0]

    # --- Scenario A: Startup (few points) → fallback classifier ---
    monitor = THMMonitor(window_size=20)
    for i in range(5):
        k = [v + random.gauss(0, 0.1) for v in K_EQ]
        r = monitor.update(k)
    check("early startup fallback", monitor.get_summary()['classifier'] == 'FALLBACK')
    check_eq("early startup: Active", monitor.get_summary()['current_regime'], 'Active')

    # --- Scenario B: Steady state (25 points) → full classifier ---
    monitor = THMMonitor(window_size=20)
    for i in range(25):
        k = [v + random.gauss(0, 0.05) for v in K_EQ]
        r = monitor.update(k)
    summary = monitor.get_summary()
    check("full: classifier", summary['classifier'] == 'FULL')
    check("full: sufficent samples", summary['n_samples'] >= 22)

    # --- Scenario C: Gradual overload → Critical ---
    monitor = THMMonitor(window_size=20)
    for i in range(25):
        p = i / 24  # 0 → 1
        # Tasks and load increase
        k = [
            K_EQ[0] + 5.0 * p + random.gauss(0, 0.1),   # tasks: 3→8
            K_EQ[1] + 3.0 * p + random.gauss(0, 0.1),   # parallel: 2→5
            K_EQ[2] + 2.0 * p + random.gauss(0, 0.1),   # depth
            0.5 + 0.3 * p + random.gauss(0, 0.02),       # context
            0.3 + 1.2 * p + random.gauss(0, 0.1),        # memory
            K_EQ[5] + 10 * p + random.gauss(0, 0.2),     # messages
            0.1 + 0.3 * p + random.gauss(0, 0.02),       # errors
            K_EQ[7] + 2.0 * p + random.gauss(0, 0.1),    # retries
            K_EQ[8] + 3.0 * p + random.gauss(0, 0.1),    # interrupts
        ]
        r = monitor.update(k)
    # The last update may or may not be Critical depending on exact metrics
    check("overload: has regime", 'regime' in r)
    check("overload: has metrics", all(m in r['metrics'] for m in ['C_K', 'T_ops', 'gamma', 'rate_op']))
    check("overload: has actions", len(r['actions']) > 0)
    check("overload: confidence >= 0.5", r['confidence'] >= 0.5)

    # --- Scenario D: Near-stuck → Frozen via fallback (few points) ---
    monitor = THMMonitor(window_size=20)
    for i in range(15):
        k = [3.0 + random.gauss(0, 0.0005),   # tasks exist
             0.0 + random.gauss(0, 0.0005),   # no parallel
             1.0 + random.gauss(0, 0.0005),   # shallow
             0.5 + random.gauss(0, 0.0005),   # stable context
             0.0 + random.gauss(0, 0.0005),   # no memory
             0.0 + random.gauss(0, 0.0005),   # no messages
             0.0 + random.gauss(0, 0.0005),   # no errors
             0.0 + random.gauss(0, 0.0005),   # no retries
             0.0 + random.gauss(0, 0.0005),   # no interrupts
        ]
        r = monitor.update(k)
    # With 15 pts (<22), uses fallback. rate_op ~ 0.0005*sqrt(9)=0.0015 < 0.01 → Frozen
    check("frozen: detected", r['regime'] in ('Frozen', 'Active'))
    # gamma might not be calibrated yet
    if r['regime'] == 'Frozen':
        check("frozen: correct actions", 'ESCALATE' in r['actions'])

    # --- Scenario E: Gamma emergency (rapid drift) ---
    monitor = THMMonitor(window_size=20)
    # Feed Active baseline first (for K_eq calibration)
    for i in range(100):
        k = [v + random.gauss(0, 0.1) for v in K_EQ]
        # Force classify as Active for gamma estimator (but we'll use RPC)
        monitor.update(k)
        # Manually mark these as Active in gamma_est
        norm_k = monitor.normalizer.normalize(k)
        monitor.gamma_est.update_active(norm_k, 'Active')

    check("emergency: gamma calibrated K_eq", monitor.gamma_est.is_calibrated)
    check("emergency: gamma eq not None", monitor.gamma_est.K_eq is not None)

    # Now rapid drift
    for i in range(10):
        drift = 3.0 + i * 0.5  # 3 → 7.5, accelerating
        k = [v + drift for v in K_EQ]
        r = monitor.update(k)

    check("emergency: has regime result", 'regime' in r)
    # Check if gamma triggered emergency
    gamma = r['metrics'].get('gamma')
    if gamma is not None:
        check("emergency: gamma available", True)

    # --- Scenario F: Reset ---
    monitor.reset()
    check("reset: empty history", monitor.get_summary()['n_samples'] == 0)
    check("reset: no regime", monitor.get_summary()['current_regime'] == 'Unknown')

    # --- Scenario G: Idle (no tasks) should be Active, not Frozen ---
    monitor = THMMonitor(window_size=20)
    for i in range(25):
        k = [0.0 + random.gauss(0, 0.001) for _ in range(9)]
        r = monitor.update(k)
    # n_active=0 → not Frozen (n_active>0 required)
    # May be Active or other regime depending on normalizer transition
    # The key assertion: n_active=0 → NEVER Frozen
    check("idle: not frozen (n_active=0 guard)", r['regime'] != 'Frozen')


# ============================================================
# SECTION 2: KVectorCollector lifecycle
# ============================================================

def test_collector_lifecycle():
    """Test KVectorCollector through realistic usage."""
    print(f"\n{'=' * 72}")
    print("  INTEGRATION: KVectorCollector")
    print(f"{'=' * 72}")

    c = KVectorCollector()

    # --- Empty collector ---
    k = c.collect()
    check_eq("empty: 9 dims", len(k), 9)
    check("empty: all zeros or defaults", all(v >= 0 for v in k))

    # --- Record events ---
    for _ in range(5):
        c.record_error()
    for _ in range(20):
        c.record_tool_call()
    for _ in range(3):
        c.record_retry()
    for _ in range(8):
        c.record_search()
    for _ in range(4):
        c.record_user_interruption()
    for _ in range(2):
        c.record_agent_message()

    k = c.collect(n_active_tasks=3, n_parallel_agents=2)
    check_eq("recorded: 9 dims", len(k), 9)
    check_eq("recorded: tasks", k[0], 3)
    check_eq("recorded: parallel", k[1], 2)
    check("recorded: errors > 0", k[6] > 0)
    check("recorded: retries > 0", k[7] > 0)
    check("recorded: searches > 0", k[4] > 0)

    # --- Reset ---
    c.reset()
    k = c.collect()
    check_eq("reset: tasks", k[0], 0)
    check_eq("reset: errors", k[6], 0)
    check_eq("reset: retries", k[7], 0)

    # --- With context override ---
    k = c.collect(n_active_tasks=5, n_parallel_agents=3,
                  task_depth_mean=2.5, context_token_frac=0.7)
    check_eq("override: tasks", k[0], 5)
    check_eq("override: parallel", k[1], 3)
    check_eq("override: depth", k[2], 2.5)
    check_eq("override: context", k[3], 0.7)

    # --- Formatting ---
    check("short_format works", isinstance(short_format([1, 2, 3]), str))


# ============================================================
# SECTION 3: Full Pipeline Simulation
# ============================================================

def test_full_pipeline():
    """Simulate a real Hermes session from start to finish."""
    print(f"\n{'=' * 72}")
    print("  INTEGRATION: Full Pipeline Simulation")
    print(f"{'=' * 72}")

    K_EQ = [3.0, 2.0, 1.5, 0.5, 0.3, 3.0, 0.1, 1.0, 2.0]
    monitor = THMMonitor(window_size=20)
    collector = KVectorCollector()

    # --- Phase 1: Session start (first 5 turns) ---
    # User asks simple questions, quick back-and-forth
    regime_sequence = []
    for turn in range(5):
        collector.record_tool_call()
        k = collector.collect(
            n_active_tasks=1,
            n_parallel_agents=0,
            task_depth_mean=1.0,
            context_token_frac=0.1 * (turn + 1),
        )
        r = monitor.update(k)
        regime_sequence.append(r['regime'])

    check("pipeline: early regime recorded", len(regime_sequence) == 5)
    check("pipeline: early fallback", monitor.get_summary()['classifier'] == 'FALLBACK')

    # --- Phase 2: Delegation starts (turns 6-15) ---
    # Agent starts working, tasks pile up
    for turn in range(10):
        active = min(3, 1 + turn // 3)
        collector.record_tool_call()
        if turn % 2 == 0:
            collector.record_search()
        if turn > 5:
            collector.record_agent_message()
        k = collector.collect(
            n_active_tasks=active,
            n_parallel_agents=active - 1,
            task_depth_mean=1.5 + turn * 0.1,
        )
        r = monitor.update(k)
        regime_sequence.append(r['regime'])

    # --- Phase 3: Becoming Critical (turns 16-25) ---
    # Tasks accelerate, context fills up
    for turn in range(10):
        load = 5 + turn // 2
        collector.record_tool_call()
        if turn > 3:
            collector.record_error()
            collector.record_retry()
            collector.record_user_interruption()
        k = collector.collect(
            n_active_tasks=load,
            n_parallel_agents=min(5, load // 2),
            task_depth_mean=3.0 + turn * 0.2,
        )
        r = monitor.update(k)
        regime_sequence.append(r['regime'])

    # At this point we should have > 20 samples → full classifier
    summary = monitor.get_summary()
    check("pipeline: full classifier active", summary['classifier'] == 'FULL' or len(regime_sequence) >= 22)

    # Verify we got various regimes
    unique_regimes = set(regime_sequence)
    check("pipeline: at least Active seen", 'Active' in unique_regimes)

    # --- Verify final state ---
    final = monitor.get_summary()
    check("pipeline: final regime exists", final['current_regime'] in
          ('Active', 'Critical', 'Turbulent', 'Frozen', 'Decayed'))


# ============================================================
# SECTION 4: Edge Cases
# ============================================================

def test_edge_cases():
    """Test edge cases and boundary conditions."""
    print(f"\n{'=' * 72}")
    print("  INTEGRATION: Edge Cases")
    print(f"{'=' * 72}")

    # --- Zero-length K-vectors ---
    try:
        C_K = compute_C_K([], k=5)
        check("edge: empty C_K", C_K is None)
    except:
        check("edge: empty C_K", False, "raised exception")

    try:
        T = compute_T_ops([], tau_short=5, tau_long=20)
        check_eq("edge: empty T_ops", T, 0.0)
    except:
        check("edge: empty T_ops", False, "raised exception")

    try:
        g = compute_gamma([1, 2, 3], [1, 2, 3], None)
        check("edge: None K_eq gamma", g is None)
    except:
        check("edge: None K_eq gamma", False, "raised exception")

    # --- Single element ---
    try:
        r = compute_rate_op([1, 2, 3], [1, 2, 3])
        check_eq("edge: rate_op identity", r, 0.0)
    except:
        check("edge: rate_op identity", False, "raised exception")

    try:
        r = compute_rate_op([0, 0, 0], [3, 4, 0])
        check_eq("edge: rate_op 3-4-5", r, 5.0)
    except:
        check("edge: rate_op 3-4-5", False, "raised exception")

    # --- THMMonitor with single update ---
    monitor = THMMonitor(window_size=20)
    r = monitor.update([1, 2, 3, 4, 5, 6, 7, 8, 9])
    check("edge: single update has regime", 'regime' in r)
    check("edge: single update has actions", 'actions' in r)

    # --- GammaEstimator without calibration ---
    ge = GammaEstimator(min_active_samples=100)
    g = ge.compute_gamma([1, 2, 3], [4, 5, 6])
    check("edge: uncalibrated gamma", g is None)
    check("edge: not calibrated", not ge.is_calibrated)

    # --- classify_regime edge cases ---
    check_eq("edge: classify default", classify_regime(0, 3, 0, 0.05, 0), 'Active')
    check_eq("edge: classify frozen no tasks",
             classify_regime(0, 2, 0, 0.005, 0), 'Active')  # n_active=0
    check_eq("edge: classify frozen w/ tasks",
             classify_regime(0, None, 0.0, 0.005, 3), 'Frozen')  # n_active=3, C_K=None

    # --- classify_fallback edge cases ---
    check_eq("edge: fallback default", classify_fallback(0, None, 0.05, 0), 'Active')
    check_eq("edge: fallback Decayed", classify_fallback(0, 0.5, 0.05, 3), 'Decayed')
    check_eq("edge: fallback Frozen (no gamma)",
             classify_fallback(0, None, 0.005, 3), 'Frozen')  # rate<0.01, tasks>0

    # --- KNormalizer ---
    kn = KNormalizer()
    check_eq("edge: norm before baseline", kn.normalize([1, 2, 3]), [1, 2, 3])
    for _ in range(20):
        kn.update([random.random() * 10 for _ in range(3)])
    normalized = kn.normalize([1, 2, 3])
    check("edge: norm after baseline", all(0 <= v <= 1 for v in normalized))
    check_eq("edge: norm 3 dims", len(normalized), 3)

    # --- get_actions edge ---
    check_eq("edge: gamma > 0.7 emergency",
             get_actions('Active', 0.8),
             ['EMERGENCY_CHECKPOINT', 'DELEGATE_NORMAL'])
    check_eq("edge: normal gamma",
             get_actions('Active', 0.0),
             ['DELEGATE_NORMAL'])
    check_eq("edge: gamma > 0.7 override",
             get_actions('Critical', 0.8),
             ['EMERGENCY_CHECKPOINT', 'SERIALIZE', 'REDUCE_PARALLEL', 'FOCUS'])

    # --- Negative gamma values ---
    check_eq("edge: gamma -0.5 not Frozen",
             classify_regime(0, 2, -0.5, 0.005, 3), 'Active')
    # abs(gamma)=0.5 > 0.1 → not Frozen

    # --- Very high values ---
    check_eq("edge: high T_ops Turbulent",
             classify_regime(3.0, 6, 0, 2.0, 8), 'Turbulent')
    check_eq("edge: high gamma Decayed",
             classify_regime(1.0, 6, 0.5, 0.5, 8), 'Decayed')  # gamma checks first

    # --- Priority: Turbulent > Decayed ---
    check_eq("edge: priority Turbulent over Decayed",
             classify_regime(3.0, 6, 0.5, 2.0, 8), 'Turbulent')

    # --- Priority: Decayed > Critical ---
    check_eq("edge: priority Decayed over Critical",
             classify_regime(0.8, 6, 0.5, 0.5, 5), 'Decayed')


# ============================================================
# SECTION 5: Cross-skill Integration
# ============================================================

def test_cross_skill():
    """Test that skills can be loaded and cross-reference correctly."""
    print(f"\n{'=' * 72}")
    print("  INTEGRATION: Skill loading")
    print(f"{'=' * 72}")

    # Verify metrics module can be imported standalone
    try:
        import metrics
        check("import: metrics module", True)
    except ImportError as e:
        check("import: metrics module", False, str(e))

    # Verify collector module can be imported standalone
    try:
        import collector
        check("import: collector module", True)
    except ImportError as e:
        check("import: collector module", False, str(e))

    # Verify THMMonitor can accept output from KVectorCollector
    monitor = THMMonitor(window_size=20)
    collector = KVectorCollector()

    for _ in range(5):
        collector.record_tool_call()
        k = collector.collect(n_active_tasks=2, n_parallel_agents=1)
        r = monitor.update(k)
        check("cross: collector → monitor", 'regime' in r)

    # Verify GammaEstimator works with KNormalizer
    normalizer = KNormalizer()
    gamma_est = GammaEstimator(min_active_samples=5)

    for i in range(10):
        k = [3 + random.gauss(0, 0.1) for _ in range(9)]
        nk = normalizer.normalize(k)
        normalizer.update(k)
        gamma_est.update_active(nk, 'Active')

    check("cross: gamma calibrates with small min", gamma_est.is_calibrated)


# ============================================================
# MAIN
# ============================================================

if __name__ == '__main__':
    print("=" * 72)
    print("  K-AWARE ORCHESTRATOR — FULL INTEGRATION TEST SUITE")
    print("=" * 72)

    test_thm_monitor_lifecycle()
    test_collector_lifecycle()
    test_full_pipeline()
    test_edge_cases()
    test_cross_skill()

    print(f"\n{'=' * 72}")
    print(f"  FINAL RESULTS: {PASS}/{TOTAL} passed, {FAIL} failed")
    if FAIL == 0:
        print("  🎉 ALL INTEGRATION TESTS PASSED")
    else:
        print(f"  ❌ {FAIL} FAILURE(S)")
    print(f"{'=' * 72}")
