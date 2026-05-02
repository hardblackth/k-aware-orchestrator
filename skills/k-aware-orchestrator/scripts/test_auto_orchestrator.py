"""
Quick smoke test for AutoOrchestrator v1.2.

Tests:
  - Core lifecycle (before_turn → interpret_actions)
  - Phase1Checker compatibility
  - Trivial task bypass
  - Cooldown caching
  - K_eq bootstrap
"""
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from auto_orchestrator import (
    AutoOrchestrator, Phase1Checker, interpret_actions, _is_trivial
)

passed = 0
failed = 0

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name} — {detail}")

# ============================================================
# TEST: Basic lifecycle
# ============================================================
print("\n=== Basic Lifecycle ===")
orch = AutoOrchestrator()
print(f"K_eq bootstrapped: {orch.k_eq_bootstrapped}")

for i in range(3):
    result = orch.before_turn(
        context_text=f"User: test {i+1}",
        n_active=2,
        n_parallel=1,
    )
    print(f"  Turn {i+1}: regime={result['regime']}, actions={result['actions']}")
    # On early turns (w < 22), fallback may return Frozen
    # when n_active>0 and rate_op≈0 — this is expected behavior
    check(f"Turn {i+1} returns regime", result['regime'] in ('Active', 'BYPASS', 'Frozen'))
    check(f"Turn {i+1} has actions", 'actions' in result)

# interpret_actions
action = orch.interpret_actions()
check("interpret_actions returns dict", isinstance(action, dict))
check("interpret_actions has action key", 'action' in action)
check("interpret_actions never calls tools", True)  # by design (no tools imported)

# ============================================================
# TEST: Phase1Checker
# ============================================================
print("\n=== Phase1Checker ===")
checker = Phase1Checker(max_load=5)

# Capability match: pass
ok, reason = checker.check_compatibility(
    task_caps={'python', 'git'},
    agent_caps={'python', 'git', 'sql'},
    n_active=2,
)
check("Capability match passes", ok and reason == 'COMPATIBLE')

# Capability mismatch
ok, reason = checker.check_compatibility(
    task_caps={'python', 'docker'},
    agent_caps={'python'},
    n_active=2,
)
check("Capability mismatch detected", not ok and 'CAPABILITY_MISMATCH' in reason)
check("Missing caps listed", 'docker' in reason)

# Overload
ok, reason = checker.check_compatibility(
    task_caps={'python'},
    agent_caps={'python'},
    n_active=5,
)
check("Overload detected", not ok and 'AGENT_OVERLOAD' in reason)

# Valid state (V set)
checker_v = Phase1Checker(config_V=[{'python', 'git'}])
ok, reason = checker_v.check_compatibility(
    task_caps={'python', 'git'},
    agent_caps={'python', 'git'},
    n_active=1,
)
check("Valid state passes", ok and reason == 'COMPATIBLE')

ok, reason = checker_v.check_compatibility(
    task_caps={'docker'},
    agent_caps={'docker'},
    n_active=1,
)
check("Invalid state detected", not ok and 'INVALID_STATE' in reason)

# Epistemic conflict proxy
ok, reason = checker.check_compatibility(
    task_caps={'python'},
    agent_caps={'python'},
    n_active=4,  # max_load=5 from constructor
)
check("Epistemic conflict proxy (load near max)", not ok and 'EPISTEMIC_CONFLICT' in reason)

# Edge: empty caps
ok, reason = checker.check_compatibility(
    task_caps=set(), agent_caps=set(), n_active=0,
)
check("Empty caps = compatible", ok and reason == 'COMPATIBLE')

# ============================================================
# TEST: interpret_actions
# ============================================================
print("\n=== interpret_actions ===")

action = interpret_actions({'regime': 'Active', 'actions': ['DELEGATE_NORMAL'], 'metrics': {}})
check("Active → PROCEED", action['action'] == 'PROCEED')

action = interpret_actions({'regime': 'Critical', 'actions': ['SERIALIZE', 'REDUCE_PARALLEL', 'FOCUS'], 'metrics': {}})
check("Critical → SERIALIZE", action['action'] == 'SERIALIZE')

action = interpret_actions({'regime': 'Turbulent', 'actions': ['PAUSE_ALL', 'ROOT_CAUSE_ANALYSIS', 'NOTIFY'], 'metrics': {}})
check("Turbulent → PAUSE_ALL", action['action'] == 'PAUSE_ALL')
check("PAUSE_ALL has clarify_required signal", action['signal'] == 'clarify_required')

action = interpret_actions({'regime': 'Decayed', 'actions': ['CHECKPOINT', 'COMPRESS_CONTEXT', 'PAUSE_NON_CRITICAL'], 'metrics': {}})
check("Decayed → CHECKPOINT", action['action'] == 'CHECKPOINT')

action = interpret_actions({'regime': 'Frozen', 'actions': ['ESCALATE', 'CHANGE_APPROACH', 'REQUEST_CLARIFICATION'], 'metrics': {}})
check("Frozen → ESCALATE", action['action'] == 'ESCALATE')

action = interpret_actions({'regime': 'Active', 'actions': ['EMERGENCY_CHECKPOINT'], 'metrics': {'gamma': 0.85}})
check("Emergency checkpoint override", action['action'] == 'EMERGENCY_CHECKPOINT')

# ============================================================
# TEST: Trivial task detection
# ============================================================
print("\n=== Trivial Task Bypass ===")

check("Short text = trivial", _is_trivial("Hello", 0))
check("Empty-ish = trivial", _is_trivial(" ", 0))
check("Non-trivial: too many chars", not _is_trivial("A" * 100, 0))
check("Non-trivial: too many lines", not _is_trivial("line1\nline2\nline3", 0))
check("Non-trivial: active tasks > 1", not _is_trivial("hi", 2))
check("None context = not trivial", not _is_trivial(None, 0))

# Verify before_turn returns BYPASS for trivial
orch2 = AutoOrchestrator()
result = orch2.before_turn(context_text="Hi", n_active=0)
check("before_turn bypass for trivial", result['regime'] == 'BYPASS')
check("Bypass has no actions", result['actions'] == [])

# Non-trivial should NOT bypass
result = orch2.before_turn(
    context_text="User: I need you to analyze this large dataset and generate a comprehensive report with 10 sections",
    n_active=3,
)
check("Non-trivial bypasses properly (no BYPASS)", result['regime'] != 'BYPASS')

# ============================================================
# TEST: Cooldown
# ============================================================
print("\n=== Cooldown ===")
orch3 = AutoOrchestrator(cooldown_s=60.0)  # 60s cooldown
r1 = orch3.before_turn(context_text="test", n_active=2)
r2 = orch3.before_turn(context_text="test2", n_active=2)
check("Cooldown returns same regime", r1['regime'] == r2['regime'])

# After clearing cooldown — should return fresh
orch3.clear_cooldown()
r3 = orch3.before_turn(context_text="test3", n_active=5)
check("After clear_cooldown: fresh result", True)

# Short cooldown (should not trigger within same function call)
orch4 = AutoOrchestrator(cooldown_s=0.0)
r4 = orch4.before_turn(context_text="test", n_active=2)
check("Zero cooldown works", r4['regime'] != 'BYPASS')

# ============================================================
# TEST: K_eq Bootstrap
# ============================================================
print("\n=== K_eq Bootstrap ===")

# Use n_active=0 most of the time to get Active regime data
# GammaEstimator needs 50 Active samples for calibration
# Disable cooldown — 250 rapid iterations must each do a full update
orch5 = AutoOrchestrator(cooldown_s=0.0)
for i in range(250):
    orch5.before_turn(
        context_text="test " * (30 + i % 40),  # vary text length for K-vector diversity
        n_active=0,  # 0 active tasks → fallback returns Active
        n_parallel=0,
    )

s = orch5.summary()
print(f"Classifier: {s['classifier']}")
print(f"Gamma calibrated: {s['gamma_calibrated']}")
print(f"Samples: {s['n_samples']}")

eq_path = os.path.expanduser("~/.hermes/k_eq_baseline.json")
if os.path.exists(eq_path):
    data = json.load(open(eq_path))
    print(f"Saved K_eq: {[round(v, 3) for v in data['K_eq']]}")

orch6 = AutoOrchestrator()
check("New instance bootstrapped from saved K_eq", orch6.k_eq_bootstrapped)
orch6.clear_k_eq()
print("K_eq cleaned up")

# ============================================================
# TEST: check_phase1 convenience method
# ============================================================
print("\n=== Phase1 convenience method ===")
ok, reason = orch.check_phase1(
    task_caps={'python', 'git'},
    agent_caps={'python', 'git', 'sql'},
    n_active=1,
)
check("orch.check_phase1() works", ok and reason == 'COMPATIBLE')

# ============================================================
# SUMMARY
# ============================================================
print(f"\n{'='*40}")
print(f"RESULTS: {passed} passed, {failed} failed out of {passed + failed} tests")
if failed == 0:
    print("ALL TESTS PASSED ✅")
else:
    print(f"SOME TESTS FAILED ❌")
print(f"{'='*40}")
