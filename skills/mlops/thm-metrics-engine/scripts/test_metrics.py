"""
THM Metrics Engine — Unit Test Suite
Tests: classification logic, metric computation, full pipeline
"""
import sys, os, math, random
random.seed(42)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from metrics import *

PASS = 0; FAIL = 0; TOTAL = 0

def chk(name, ok, detail=""):
    global PASS, FAIL, TOTAL; TOTAL += 1
    if ok: PASS += 1; print(f"  ✅ [{name}] {detail}")
    else:  FAIL += 1; print(f"  ❌ [{name}] FAIL: {detail}")

def eq(name, a, b, d=""):
    global PASS, FAIL, TOTAL; TOTAL += 1
    if a == b: PASS += 1; print(f"  ✅ [{name}] = {b}" + (f" ({d})" if d else ""))
    else: FAIL += 1; print(f"  ❌ [{name}] expected {b}, got {a}")

# --- Classification ---
def t1():
    print("\n--- Classification Logic ---")
    eq("active normal", classify_regime(0, 4, 0, 0.1, 3), 'Active')
    eq("critical high", classify_regime(0.8, 6, 0, 0.5, 5), 'Critical')
    eq("turbulent full", classify_regime(2.5, 4, 0, 2.0, 8), 'Turbulent')
    eq("frozen exact", classify_regime(0, 2, 0, 0.005, 3), 'Frozen')
    eq("idle no tasks", classify_regime(0, 2, 0, 0.005, 0), 'Active')
    eq("decayed soft", classify_regime(0, 3, 0.4, 0.1, 3), 'Decayed')
    eq("decayed new threshold 0.2", classify_regime(0, 3, 0.2, 0.1, 3), 'Decayed')  # v1.1: 0.15 threshold
    eq("decayed hard emergency", classify_regime(0, 4, 0.8, 0.2, 3), 'Decayed')
    eq("priority decayed > critical", classify_regime(0.8, 6, 0.5, 0.5, 5), 'Decayed')
    eq("priority turbulent > decayed", classify_regime(2.5, 6, 0.5, 2.0, 8), 'Turbulent')
    eq("fallback critical", classify_fallback(0.4, None, 0.2, 5), 'Critical')
    eq("fallback turbulent", classify_fallback(0, None, 0.6, 12), 'Turbulent')
    eq("fallback frozen no tasks", classify_fallback(0, None, 0.005, 2), 'Frozen')
    eq("fallback decayed 0.2", classify_fallback(0, 0.2, 0.05, 3), 'Decayed')  # v1.1: 0.15 threshold

# --- Metrics ---
def t2():
    print("\n--- Metric Computation ---")
    # C_K on 2D spiral
    spiral = [[math.cos(t*0.5)*(1+t*0.05), math.sin(t*0.5)*(1+t*0.05)] + [0]*7 for t in range(30)]
    ck = compute_C_K(spiral, 5)
    chk("C_K spiral 2D", ck and 1.5 <= ck <= 3.0, f"LID={ck:.3f}")

    # Degenerate
    chk("C_K degenerate", compute_C_K([[1]*9 for _ in range(30)]) is None)
    # Short
    chk("C_K too short", compute_C_K([[1]*9 for _ in range(6)], 5) is None)

    # T_ops constant
    chk("T_ops constant", abs(compute_T_ops([0.1]*25)) < 0.1)
    # T_ops accelerating
    acc = [0.01 + i*0.025 for i in range(25)]
    chk("T_ops accelerating", compute_T_ops(acc) > 0.5, f"T={compute_T_ops(acc):.4f}")
    # T_ops decelerating
    dec = [0.2 - i*0.006 for i in range(25)]
    chk("T_ops decelerating", compute_T_ops(dec) < -0.3, f"T={compute_T_ops(dec):.4f}")
    # T_ops short
    chk("T_ops insufficient", compute_T_ops([0.1]*10) == 0.0)

    # Gamma
    KE = [3, 2, 1.5, 0.5, 0.3, 3, 0.1, 1, 2]
    chk("gamma no K_eq", compute_gamma([1]*9, [1]*9, None) is None)
    chk("gamma toward eq", compute_gamma(KE, [v+1 for v in KE], KE) < 0)
    chk("gamma away from eq", compute_gamma([v+2 for v in KE], KE, KE) > 0)

    # rate_op
    chk("rate_op zero", compute_rate_op([1,2,3], [1,2,3]) == 0.0)
    chk("rate_op 3-4-5", compute_rate_op([0,0,0], [3,4,0]) == 5.0)

# --- THMMonitor ---
def t3():
    print("\n--- THMMonitor Pipeline ---")
    KE = [3.0, 2.0, 1.5, 0.5, 0.3, 3.0, 0.1, 1.0, 2.0]
    m = THMMonitor(20)
    for _ in range(5):
        m.update([v+random.gauss(0,0.05) for v in KE])
    chk("early fallback", not m.get_summary()['classifier'] == 'FULL')

    m.reset()
    for _ in range(25):
        m.update([v+random.gauss(0,0.05) for v in KE])
    chk("full classifier", m.get_summary()['classifier'] == 'FULL')

    m.reset()
    for i in range(25):
        p = i/24
        m.update([KE[0]+5*p+random.gauss(0,0.1), KE[1]+3*p+random.gauss(0,0.1),
                  KE[2]+2*p+random.gauss(0,0.1), 0.5+0.3*p+random.gauss(0,0.02),
                  0.3+1.2*p+random.gauss(0,0.1), KE[5]+10*p+random.gauss(0,0.2),
                  0.1+0.3*p+random.gauss(0,0.02), KE[7]+2*p+random.gauss(0,0.1),
                  KE[8]+3*p+random.gauss(0,0.1)])
    r = m.get_summary()
    chk("overload has regime", r['current_regime'] in ['Active','Critical','Turbulent','Frozen','Decayed'])

    m.reset()
    for i in range(120):
        k = [v+random.gauss(0,0.1) for v in KE]
        m.update(k)
        # After each update, manually feed normalized K to gamma estimator
        nk = m.normalizer.normalize(k) if m.normalizer.min_vals else k
        m.gamma_est.update_active(nk, 'Active')
    chk("gamma calibrated after 120", m.gamma_est.is_calibrated)
    if m.gamma_est.K_eq:
        chk("K_eq has correct dims", len(m.gamma_est.K_eq) == 9)

# --- KNormalizer ---
def t4():
    print("\n--- KNormalizer ---")
    kn = KNormalizer()
    eq("norm before baseline", kn.normalize([1,2,3]), [1,2,3])
    for _ in range(20):
        kn.update([random.random()*10 for _ in range(3)])
    n = kn.normalize([1,2,3])
    chk("norm after baseline", all(0<=v<=1 for v in n))

# --- get_actions ---
def t5():
    print("\n--- Actions ---")
    eq("active actions", get_actions('Active', 0), ['DELEGATE_NORMAL'])
    eq("critical actions", get_actions('Critical', 0), ['SERIALIZE','REDUCE_PARALLEL','FOCUS'])
    eq("emergency override", get_actions('Active', 0.8), ['EMERGENCY_CHECKPOINT','DELEGATE_NORMAL'])

if __name__ == '__main__':
    print("THM METRICS ENGINE — UNIT TESTS\n")
    t1(); t2(); t3(); t4(); t5()
    print(f"\n{PASS}/{TOTAL} passed, {FAIL} failed" + (" 🎉" if FAIL==0 else f" ❌ {FAIL}"))
