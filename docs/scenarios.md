# Scenarios — 5 Validated Real-World Simulations

All scenarios pass with 32/32 tests. Run with:
```bash
cd skills/devops/k-aware-orchestrator/scripts
$env:PYTHONIOENCODING='utf-8'; python test_scenario4_epistemic.py
$env:PYTHONIOENCODING='utf-8'; python test_scenario3_error_cascade.py
$env:PYTHONIOENCODING='utf-8'; python test_scenario1_5tasks.py
$env:PYTHONIOENCODING='utf-8'; python test_scenario2_long_session.py
$env:PYTHONIOENCODING='utf-8'; python test_scenario5_predictive.py
```

## S4: Epistemic Mismatch ✅ (11 tests)

**Problem:** User delegates task requiring skills agent doesn't have.

```
Without K-Aware: delegate react component → syntax error × 3 → ~9 นาทีเสีย
With K-Aware:    check_phase1() → CAPABILITY_MISMATCH → 0.12 ms
```

**Improvement: 4,372,440x faster**

## S3: Error Cascade ✅ (10 tests)

**Problem:** One task error cascades to all parallel tasks.

```
Without K-Aware: task#2 error → cascade → 4/5 tasks fail
With K-Aware:    error_rate ↑ → PAUSE_ALL → user continue → SERIALIZE → 5/5 OK
```

**Key:** K-Aware converts silent cascade → structured interrupt with user consent.

## S1: 5 Tasks Parallel ✅ (5 tests)

**Problem:** Fan-out 5 tasks → context overload.

```
Without K-Aware: 5 parallel → context full → 2/5 fail + 20 min fix
With K-Aware:    progressive load detect → auto-serialize → 5/5 pass
```

## S2: 100-Turn Session ✅ (4 tests)

**Problem:** Long session context death.

```
Without K-Aware: dies at ~turn 80 → /new → ข้อมูลหาย
With K-Aware:    57% Active, 34% BYPASS, 7% Frozen, 2% Critical — 100 turns alive
```

**Regime transitions:** 17 transitions detected  
**Critical at turn 33:** T_ops=0.947

## S5: Predictive Intervention ✅ (2 tests)

**Problem:** No early warning before context crisis.

```
Without K-Aware: รู้เมื่อ T_ops พุ่งแล้ว (reactive panic)
With K-Aware:    predict(3) → T_ops=1.86 detect Turbulent → PAUSE_ALL proactive
```

**Key:** รู้ก่อน ~4 turns ว่าระบบจะเข้า Critical/Turbulent.
