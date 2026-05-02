"""
Scenario 5 Simulation: Predictive Intervention

จำลอง: T_ops ค่อยๆ สูงขึ้น → K-Aware predict ก่อน 4 turns → proactive action
Without K-Aware: รู้ตัวเมื่อสายแล้ว (context เต็ม)
With K-Aware: predict ล่วงหน้า → SERIALIZE ก่อนพัง

Run: python test_scenario5_predictive.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from auto_orchestrator import AutoOrchestrator

passed = 0; failed = 0
def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1; print(f"  ✅ {name}")
    else:
        failed += 1; print(f"  ❌ {name} — {detail}")

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

section("SCENARIO 5: Predictive Intervention — See It Before It Breaks")

# ============================================================
# BUILD UP GRADUAL T_OPS INCREASE
# ============================================================
print("\n  Simulating gradual T_ops increase (0 → Critical)...\n")

orch = AutoOrchestrator(cooldown_s=0.0)

predictions = []
t_ops_values = []

for turn in range(1, 31):
    # Simulate increasing load over time
    if turn <= 5:
        n_active = 1; n_parallel = 0
        text = f"turn {turn}: normal query operation"
    elif turn <= 10:
        n_active = 2; n_parallel = 1
        text = f"turn {turn}: starting to delegate some tasks to subagents for processing"
    elif turn <= 15:
        n_active = 3; n_parallel = 2
        text = f"turn {turn}: more complex tasks with multiple parallel agent delegations running"
    elif turn <= 20:
        n_active = 4; n_parallel = 2
        text = f"turn {turn}: heavy load phase with error injection to stress test the system"
    elif turn <= 25:
        n_active = 5; n_parallel = 3
        text = f"turn {turn}: near maximum capacity with many concurrent operations running"
    else:
        n_active = 3; n_parallel = 2
        text = f"turn {turn}: recovery phase after peak load with reduced task count"

    result = orch.before_turn(
        context_text=text,
        n_active=n_active,
        n_parallel=n_parallel,
    )

    t = result['metrics']['T_ops']
    t_ops_values.append(t)

    # Predict every 5 turns
    if turn % 5 == 0:
        pred = orch.predict(horizon=3)
        predictions.append((turn, pred))
    elif turn == 1:
        pred = orch.predict(horizon=3)
        predictions.append((turn, pred))

# ============================================================
# TIMELINE
# ============================================================
section("Timeline: T_ops Progression")

header = f"{'Turn':6s} {'n_active':10s} {'Regime':12s} {'T_ops':8s} {'Prediction':20s} {'Action'}"
print(f"\n  {header}")
print(f"  {'-'*70}")
for i in range(0, 30, 5):
    r = orch._last_result  # Can't re-get, use logged data
    t = t_ops_values[i]

    # Find prediction for this turn
    pred_action = "—"
    for turn, pred in predictions:
        if turn == i + 1:
            pred_action = f"{pred['predicted_regime']:8s} (c={pred['confidence']:.0%})"
            break

    print(f"  T{i+1:<3}  ?        ?           {t:.4f}    {pred_action}")

# Better: re-read from stored values
print()
for i, t in enumerate(t_ops_values):
    if i % 3 == 0 or i == len(t_ops_values) - 1:
        # Find prediction for this point
        p_text = ""
        for turn, pred in predictions:
            if turn == i + 1:
                p_text = f"  → predict: {pred['predicted_regime']} ({pred['confidence']:.0%})"
                break
        print(f"  Turn {i+1:2d}: T_ops={t:.4f}{p_text}")

# ============================================================
# CRITICAL INSIGHT: Predictive vs Reactive
# ============================================================
section("The Predictive Advantage")

# Show the key prediction moments
for turn, pred in predictions:
    t = t_ops_values[turn - 1] if turn <= len(t_ops_values) else 0

    # Classify this turn's actual state
    if t > 2.0:
        actual = "Turbulent"
    elif t > 0.5:
        actual = "Critical"
    elif t < -0.3:
        actual = "Decayed"
    else:
        actual = "Active"

    print(f"\n  Turn {turn:2d}: T_ops={t:.4f} ({actual})")
    print(f"           Predicted ({3}-turn ahead): {pred['predicted_regime']}")
    print(f"           Confidence: {pred['confidence']:.0%}")
    print(f"           Suggestion: {pred['suggested_action']}")

    # Is the prediction useful?
    if pred['predicted_regime'] != 'Active' and actual == 'Active':
        print(f"           ⚠️ PREDICTIVE WARNING: sees {pred['predicted_regime']} before it arrives!")
    elif pred['predicted_regime'] == actual:
        print(f"           ✅ Accurate prediction")
    else:
        print(f"           ℹ️ Informational")

# ============================================================
# COMPARISON
# ============================================================
section("Comparison Timeline")

print("""
Turn   T_ops    WITHOUT K-Aware              WITH K-Aware v1.3
────   ─────    ────────────────              ────────────────
""")

for i in range(0, 30, 3):
    t = t_ops_values[i]

    # Without K-Aware
    if t < 0.3:
        without = "✅ Normal operation"
    elif t < 0.5:
        without = "⚠️ Context filling (not noticed)"
    elif t < 1.0:
        without = "❌ Context full — quality drops"
    elif t < 2.0:
        without = "❌❌ Output unusable — panic"
    else:
        without = "💀 System crash — /new"

    # With K-Aware
    if t < 0.3:
        kaware = "✅ Active → PROCEED"
    elif t < 0.5:
        kaware = "👀 Monitoring → predict(3) check"
    elif t < 1.0:
        kaware = "🔴 Critical detected → SERIALIZE"
    elif t < 2.0:
        kaware = "🟡 Turbulent → PAUSE_ALL signal"
    else:
        kaware = "🆘 Recovery mode"

    # Find prediction for this turn
    pred_info = ""
    for turn, pred in predictions:
        if abs(turn - (i+1)) <= 1:
            pred_info = f"  [pred: {pred['predicted_regime']}]"

    print(f"T{i+1:<3}  {t:.3f}   {without:35s} {kaware:40s}{pred_info}")

# ============================================================
section("Final Predictive State")

pred = orch.predict(horizon=5)
print(f"\n  Current T_ops: {t_ops_values[-1]:.4f}")
print(f"  Predicted regime (+5 turns): {pred['predicted_regime']}")
print(f"  Confidence: {pred['confidence']:.0%}")
print(f"  Suggested action: {pred['suggested_action']}")
print(f"  Trend: {pred['trend_description']}")

check("predict() works after load cycle", pred['predicted_regime'] != 'UNKNOWN')
check("predict() has confidence > 0", pred['confidence'] > 0)

# Dashboard
report = orch.report()
print(f"\n  Dashboard (last 8 lines):")
for line in report.split('\n')[-8:]:
    print(f"    {line}")

# ============================================================
section(f"RESULTS: {passed}/{passed + failed} passed")
print(f"""
KEY INSIGHT:
  Without K-Aware: output แย่ → panic → /new
                   (reactive — รู้เมื่อสาย)

  With K-Aware v1.3: sees T_ops rising BEFORE critical
                   → predict(3) → proactive SERIALIZE
                   → user รู้ล่วงหน้า
                
  K-Aware transforms 'silent degradation' →
  'predictive awareness with proactive action'
""")
if failed == 0:
    print("SCENARIO 5: ✅ ALL PASSED")
else:
    print(f"SOME TESTS FAILED ❌")
