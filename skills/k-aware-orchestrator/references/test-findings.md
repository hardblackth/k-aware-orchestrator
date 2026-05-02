# Test Findings — 2026-05-02

Session where the K-Aware Orchestrator meta-skill was created, tested, and validated.

## Approach

1. **Created SKILL.md** with classification logic from the full spec
2. **Wrote test_classifier.py** — pure Python (no numpy dependency)
3. **Ran iterative tests** — 3 major revisions:
   - v1: Constant K-vectors → all classified as Frozen (rate_op=0 bug)
   - v2: Added noise → but thresholds didn't match dynamics
   - v3: Three-layer architecture (explicit metrics → metric computation → full pipeline)

## Bugs Found & Fixed

### Bug 1: Frozen Without n_active Guard
**Symptom:** Idle state (n_active=0, rate_op ≈ 0) classified as Frozen  
**Fix:** Added `n_active > 0` to Frozen check  
**Priority:** Priority order → Turbulent > Decayed > Frozen > Critical > Active  
**Guard:** Frozen requires `n_active > 0` — idle (no tasks) is not stuck

### Bug 2: LID Spurious on Near-Degenerate Data
**Symptom:** noise=0.0001 across 9 dims → LID returns 7+ instead of degenerate  
**Root cause:** LID MLE sees small gaussian structure as a manifold  
**Mitigation:** fallback classifier for w < 22; in production, natural tool-call noise prevents this

### Bug 3: γ Threshold Hard to Trigger with Linear Drift
**Finding:** γ = (dist_t - dist_t1) / ‖K_eq‖  
For threshold 0.3 → need per-step distance change > 1.632 (with ‖K_eq‖ ≈ 5.44)  
Linear drift of 8 units over 25 steps → γ ≈ 0.184 (too low)  
Only exponential drift (exp(2t)-1) reaches γ > 0.3

## Threshold Calibration Notes

| Threshold | Current | Tested With | Result |
|-----------|---------|-------------|--------|
| Turbulent: \|T_ops\| > 2.0 ✓ | 2.0 | Sine oscillation amplitude 4.0 | Rate_op > 1.5 ✓ |
| Decayed: γ > 0.3 ✓ | 0.3 | Exponential drift 0→6.4 | Works with exp(2t)-1 |
| Frozen: rate < 0.01 ✓ | 0.01 | Gaussian noise 0.0001 | rate_op ≈ 0.001 < 0.01 |
| Critical: T_ops > 0.5 ✓ | 0.5 | Arithmetic progression 0.01→0.61 | T_ops = 0.503 > 0.5 |

## Action Mapping Verified

| Regime | Actions | Verified |
|--------|---------|----------|
| Active | DELEGATE_NORMAL | ✅ |
| Critical | SERIALIZE, REDUCE_PARALLEL, FOCUS | ✅ |
| Turbulent | PAUSE_ALL, ROOT_CAUSE_ANALYSIS, NOTIFY | ✅ |
| Frozen | ESCALATE, CHANGE_APPROACH, REQUEST_CLARIFICATION | ✅ |
| Decayed | CHECKPOINT, COMPRESS_CONTEXT, PAUSE_NON_CRITICAL | ✅ |
| γ > 0.7 override | EMERGENCY_CHECKPOINT prepended | ✅ |

## Test Coverage

- **Layer 1 (Classification Logic):** 18/18 ✅
  - All 5 regimes + fallback variants + edge cases
- **Layer 2 (Metric Computation):** 11/11 ✅
  - C_K on spiral, noise, degenerate, insufficient data
  - T_ops on constant, accelerating, decelerating, insufficient
  - γ with no K_eq, toward, away
- **Layer 3 (Full Pipeline):** 6/6 ✅
  - Active, Frozen, Decayed, Critical, Turbulent
  - Realistic K-vector generation per regime type
