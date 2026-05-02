"""
Scenario 4 Simulation: Epistemic Mismatch (Shortest)

จำลอง: user ส่ง task ที่ agent ไม่มี capability → K-Aware reject ก่อน delegate
เทียบกับ: without K-Aware → delegate → fail → retry 3x → เสียเวลา

Run: python test_scenario4_epistemic.py
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from auto_orchestrator import AutoOrchestrator, Phase1Checker

passed = 0
failed = 0

def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1; print(f"  ✅ {name}")
    else:
        failed += 1; print(f"  ❌ {name} — {detail}")

print("=" * 60)
print("SCENARIO 4: Epistemic Mismatch — Phase1 Reject Test")
print("=" * 60)

# ============================================================
# WITHOUT K-AWARE (simulated)
# ============================================================
print("\n--- Without K-Aware ---")
print("  User: 'เขียน React component นี้'")
print("  Agent มี: python, git, sql")
print("  → delegate_task('react component') ...")
time.sleep(0.1)
simulated_waste = 0
for attempt in range(3):
    simulated_waste += 1
    print(f"  → Attempt {attempt+1}: syntax error (เสียเวลา ~3 นาที)")
print(f"  ❌ Task fail หลัง {simulated_waste} retries")
print(f"  ❌ เสียเวลา: ~{simulated_waste * 3} นาที")
waste_without = simulated_waste * 3

# ============================================================
# WITH K-AWARE v1.3
# ============================================================
print("\n--- With K-Aware v1.3 ---")
start = time.time()

orch = AutoOrchestrator()

# จำลองว่า Hermes session ส่ง task นี้มา
task_caps = {'react', 'javascript', 'css', 'html'}
agent_caps = {'python', 'git', 'sql', 'terminal'}
n_active = 2

# ก่อน delegate_task — ตรวจ Phase 1
ok, reason = orch.check_phase1(
    task_caps=task_caps,
    agent_caps=agent_caps,
    n_active=n_active,
)

elapsed = (time.time() - start) * 1000  # ms

print(f"  → check_phase1 ใช้เวลา: {elapsed:.2f} ms")
print(f"  → Result: ({ok}, '{reason}')")
print(f"  → ✅ Reject ก่อน delegate — ไม่เสียเวลา")

check("Rejects mismatched task", not ok)
check("Reason starts with CAPABILITY_MISMATCH", reason.startswith('CAPABILITY_MISMATCH'))
check("Lists missing caps: react", 'react' in reason)
check("Lists missing caps: javascript", 'javascript' in reason)
check("Lists missing caps: css", 'css' in reason)
check("Lists missing caps (not terminal)", 'terminal' not in reason)
check("Rejection is instant (< 10ms)", elapsed < 10)

waste_with_kaware = elapsed / 1000 / 60  # minutes
print(f"\n--- Time Comparison ---")
print(f"  Without K-Aware: ~{waste_without} minutes WASTED (3 retries)")
print(f"  With K-Aware:    ~{elapsed:.2f} ms (instant reject)")
print(f"  Improvement:     {waste_without * 60 * 1000 / max(elapsed, 0.001):.0f}x faster")

# ============================================================
# BONUS: Test that VALID tasks pass Phase 1
# ============================================================
print("\n--- Bonus: Valid task should PASS Phase 1 ---")
ok2, reason2 = orch.check_phase1(
    task_caps={'python'},
    agent_caps={'python', 'git', 'sql'},
    n_active=1,
)
check("Valid task passes Phase 1", ok2 and reason2 == 'COMPATIBLE')

# ============================================================
# BONUS: Test edge cases
# ============================================================
print("\n--- Bonus: Edge cases ---")

# Overload rejection
ok3, reason3 = orch.check_phase1(
    task_caps={'python'}, agent_caps={'python'},
    n_active=5,  # max_load=5
)
check("Overload (n_active=5) rejects", not ok3 and 'AGENT_OVERLOAD' in reason3)

# Epistemic conflict proxy
ok4, reason4 = orch.check_phase1(
    task_caps={'python'}, agent_caps={'python'},
    n_active=4,  # max_load=5 → 4 is max_load-1
)
check("Epistemic proxy (n_active=4) rejects", not ok4 and 'EPISTEMIC_CONFLICT' in reason4)

# Empty caps
ok5, reason5 = orch.check_phase1(
    task_caps=set(), agent_caps=set(), n_active=0,
)
check("Empty caps = compatible", ok5 and reason5 == 'COMPATIBLE')

# ============================================================
# SUMMARY
# ============================================================
print(f"\n{'='*60}")
print(f"RESULTS: {passed} passed, {failed} failed out of {passed + failed} tests")
if failed == 0:
    print("SCENARIO 4: ✅ K-Aware rejects epistemic mismatch instantly")
    print(f"             เสียเวลา 0 vs ~{waste_without} นาที (without)")
else:
    print("SOME TESTS FAILED ❌")
print(f"{'='*60}")
