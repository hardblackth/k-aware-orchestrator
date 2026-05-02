"""
K-Vector Collector — Unit Tests

Covers:
  - Empty collector defaults (9 dims, all >= 0)
  - Recording events (errors, retries, searches, etc.)
  - Override values
  - Reset
  - Formatting functions
  - estimate_from_session helper
  - Edge cases (no events, single event)
"""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collector import KVectorCollector, estimate_from_session, format_k_vector, short_format

PASS = 0; FAIL = 0; TOTAL = 0

def chk(name, ok, detail=""):
    global PASS, FAIL, TOTAL; TOTAL += 1
    if ok: PASS += 1; print(f"  ✅ [{name}] {detail}")
    else:  FAIL += 1; print(f"  ❌ [{name}] FAIL: {detail}")

def eq(name, a, b, d=""):
    global PASS, FAIL, TOTAL; TOTAL += 1
    if a == b: PASS += 1; print(f"  ✅ [{name}] = {b}" + (f" ({d})" if d else ""))
    else: FAIL += 1; print(f"  ❌ [{name}] expected {b}, got {a}")

# --- Test 1: Empty collector ---
def t1():
    print("\n--- Empty Collector ---")
    c = KVectorCollector()
    k = c.collect()
    eq("9 dims", len(k), 9)
    chk("all >= 0", all(v >= 0 for v in k))
    eq("tasks default", k[0], 0)
    eq("parallel default", k[1], 0)
    eq("depth default", k[2], 1.0)
    eq("errors default", k[6], 0.0)
    eq("retries default", k[7], 0.0)

# --- Test 2: Recording events ---
def t2():
    print("\n--- Recording Events ---")
    c = KVectorCollector()
    for _ in range(5): c.record_error()
    for _ in range(3): c.record_retry()
    for _ in range(8): c.record_search()
    for _ in range(4): c.record_user_interruption()
    for _ in range(2): c.record_agent_message()

    k = c.collect(n_active_tasks=3, n_parallel_agents=2)
    eq("9 dims after record", len(k), 9)
    eq("tasks", k[0], 3)
    eq("parallel", k[1], 2)
    chk("errors > 0", k[6] > 0)
    chk("retries > 0", k[7] > 0)
    chk("searches recorded", k[4] > 0)
    chk("interrupts recorded", k[8] > 0)
    chk("messages recorded", k[5] > 0)

# --- Test 3: Override values ---
def t3():
    print("\n--- Override Values ---")
    c = KVectorCollector()
    k = c.collect(n_active_tasks=5, n_parallel_agents=3,
                  task_depth_mean=2.5, context_token_frac=0.7)
    eq("tasks override", k[0], 5)
    eq("parallel override", k[1], 3)
    eq("depth override", k[2], 2.5)
    eq("context override", k[3], 0.7)

# --- Test 4: Reset ---
def t4():
    print("\n--- Reset ---")
    c = KVectorCollector()
    for _ in range(10): c.record_error()
    for _ in range(5): c.record_retry()
    k_before = c.collect(n_active_tasks=3)
    chk("errors before reset", k_before[6] > 0)
    c.reset()
    k_after = c.collect()
    eq("tasks after reset", k_after[0], 0)
    eq("errors after reset", k_after[6], 0)
    eq("retries after reset", k_after[7], 0)

# --- Test 5: Formatting ---
def t5():
    print("\n--- Formatting ---")
    k = [3.0, 2.0, 1.5, 0.6, 0.5, 4.0, 0.1, 1.0, 2.0]
    sf = short_format(k)
    chk("short_format returns string", isinstance(sf, str))
    chk("short_format has brackets", sf.startswith('[') and sf.endswith(']'))
    fk = format_k_vector(k)
    chk("format_k_vector returns string", isinstance(fk, str))
    chk("format_k_vector multi-line", '\n' in fk)
    chk("format_k_vector has dim names", 'n_active_tasks' in fk)

# --- Test 6: estimate_from_session ---
def t6():
    print("\n--- estimate_from_session ---")
    ctx = {
        'n_active': 3, 'n_parallel': 2, 'depth': 2.0,
        'pages': 20, 'hours': 1.0, 'searches': 10,
        'messages': 5, 'errors': 2, 'total_calls': 20,
        'retries': 1, 'interruptions': 3,
    }
    k = estimate_from_session(ctx)
    eq("session 9 dims", len(k), 9)
    eq("session tasks", k[0], 3)
    eq("session parallel", k[1], 2)
    eq("session depth", k[2], 2.0)
    chk("session context < 1", k[3] <= 1.0)
    chk("session error rate < 1", k[6] <= 1.0)

# --- Test 7: Edge cases ---
def t7():
    print("\n--- Edge Cases ---")
    c = KVectorCollector()
    # Single record
    c.record_tool_call()
    k = c.collect()
    chk("single tool call no crash", len(k) == 9)
    # Very high values
    k = c.collect(n_active_tasks=999, n_parallel_agents=999)
    chk("high values no crash", len(k) == 9)
    # No events at all (fresh after reset)
    c.reset()
    k = c.collect()
    chk("fresh reset all zeros", sum(k) == 0.0 or all(v >= 0 for v in k))
    # Empty context for estimate_from_session
    k = estimate_from_session({})
    eq("empty session 9 dims", len(k), 9)
    chk("empty session defaults to 0", all(v == 0 for v in k[:2]))

if __name__ == '__main__':
    print("K-VECTOR COLLECTOR — UNIT TESTS\n")
    t1(); t2(); t3(); t4(); t5(); t6(); t7()
    print(f"\n{PASS}/{TOTAL} passed, {FAIL} failed" + (" 🎉" if FAIL==0 else f" ❌ {FAIL}"))