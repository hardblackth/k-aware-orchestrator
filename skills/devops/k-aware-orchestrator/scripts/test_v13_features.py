"""Quick v1.3 feature test — predictive, calibration, dashboard."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from auto_orchestrator import AutoOrchestrator, THMPredictor, AutoCalibrator

passed = 0
failed = 0

def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  [OK] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} — {detail}")

print("=== THMPredictor ===")
p = THMPredictor()

# Prediction with upward T_ops trend
pred = p.predict([0.1, 0.15, 0.2, 0.25, 0.3], [0.01]*5, [None]*5, None, 0)
check("Predicts non-UNKNOWN", pred["predicted_regime"] != "UNKNOWN")
check("Has confidence", pred["confidence"] > 0)
check("Has action", len(pred["suggested_action"]) > 0)
check("Has trend desc", len(pred["trend_description"]) > 0)

# Prediction with insufficient data
pred2 = p.predict([0.1], [0.0], [None], None, 0)
check("Insufficient data = UNKNOWN", pred2["predicted_regime"] == "UNKNOWN")

# Prediction with high T_ops (should predict Critical)
pred3 = p.predict([0.1, 0.2, 1.0, 1.5, 2.0], [0.1]*5, [8.0]*5, None, 3)
check("High T_ops → Critical", pred3["predicted_regime"] in ("Critical", "Turbulent"))

# Prediction with high gamma
pred4 = p.predict([0.1]*5, [0.01]*5, [3.0]*5, 0.45, 2)
check("High gamma → Decayed", pred4["predicted_regime"] == "Decayed")

# Prediction with n_active>0 and rate≈0 (Frozen)
pred5 = p.predict([0.0]*5, [0.001]*5, [2.0]*5, 0.01, 3)
check("Stuck tasks → Frozen", pred5["predicted_regime"] == "Frozen")

print()
print("=== AutoCalibrator ===")
c = AutoCalibrator()

# Record some feedback
for i in range(15):
    c.record_feedback("Active", True)
check("15 correct = 100% accuracy", c.accuracy == 1.0)

for i in range(5):
    c.record_feedback("Critical", False)
check("After 5 wrong, accuracy < 1.0", c.accuracy < 1.0)

# Check thresholds
th = c.get_thresholds()
check("Has t_ops_critical threshold", "t_ops_critical" in th)
check("Has gamma_decayed threshold", "gamma_decayed" in th)

# Reset
c.reset()
check("After reset, no history", c.accuracy == 0.0)

print()
print("=== AutoOrchestrator Integration ===")
o = AutoOrchestrator()

# 3 turns of non-trivial data
for i in range(5):
    o.before_turn(
        context_text=f"User: This is test message number {i}",
        n_active=2 if i > 0 else 0,
        n_parallel=1,
    )

# predict
pred = o.predict()
check("orch.predict() returns dict", isinstance(pred, dict))
check("orch.predict() has regime", "predicted_regime" in pred)

# report
r = o.report()
check("orch.report() returns string", isinstance(r, str))
check("report mentions regime", "Regime" in r)
check("report mentions prediction", "Predicted" in r)
check("report mentions calibration", "Calibration" in r)

# feedback
fb = o.record_feedback(True)
check("orch.record_feedback() works", fb["status"] == "recorded")
check("accuracy tracked", fb["accuracy"] >= 0)

# calibrator_summary
cs = o.calibrator_summary()
check("calibrator_summary has accuracy", "accuracy" in cs)
check("calibrator_summary has thresholds", "thresholds" in cs)

print()
print(f"=== RESULTS: {passed} passed, {failed} failed ===")
if failed == 0:
    print("ALL V1.3 FEATURES PASSED ✅")
else:
    print(f"SOME FAILED ❌")
