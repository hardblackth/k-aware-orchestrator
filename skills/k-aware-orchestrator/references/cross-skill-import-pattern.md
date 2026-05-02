# Cross-Skill Dependency: Graceful Fallback Import

## Problem

Hermes skills can depend on each other (e.g., `k-aware-orchestrator` depends on `thm-metrics-engine/metrics.py`). Hardcoding import paths creates **code triplication** — same math/logic in multiple places that drifts apart when thresholds change.

## Solution: Import Canonical → Fallback to Local

```python
# At the top of your script, BEFORE defining any functions:
import sys, os

_SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
_SKILL_ROOT  = os.path.dirname(_SCRIPT_DIR)                    # skill dir (e.g., devops/k-aware-orchestrator)
_SKILLS_ROOT = os.path.dirname(os.path.dirname(_SKILL_ROOT))   # .hermes/skills

try:
    sys.path.insert(0, os.path.join(_SKILLS_ROOT, 'mlops', 'thm-metrics-engine', 'scripts'))
    from metrics import (
        compute_C_K, compute_T_ops, compute_gamma,
        classify_regime, classify_fallback,
        vec_norm, vec_distance,
        REGIME_ACTIONS, EMERGENCY_ACTION, get_actions,
    )
    ACTIONS = REGIME_ACTIONS
    EMERGENCY = EMERGENCY_ACTION
    _CANONICAL = True
except ImportError:
    _CANONICAL = False

# Local fallback definitions (indented under if not _CANONICAL:)
if not _CANONICAL:
    def compute_C_K(W_t, k): ...  # full implementation
    def classify_regime(...): ...
    # ... etc
```

### Directory Traversal Logic

For a script at `.hermes/skills/<category>/<skill>/scripts/test.py`:

```
__file__
  → dirname         → .hermes/skills/<category>/<skill>/scripts/
  → dirname         → .hermes/skills/<category>/<skill>/           (SKILL_ROOT)
  → dirname         → .hermes/skills/<category>/                   (CATEGORY_ROOT)
  → dirname(dirname)→ .hermes/skills/                              (SKILLS_ROOT)
```

```python
_SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
_SKILL_ROOT  = os.path.dirname(_SCRIPT_DIR)
_SKILLS_ROOT = os.path.dirname(os.path.dirname(_SKILL_ROOT))

# Then:
sys.path.insert(0, os.path.join(_SKILLS_ROOT, 'category', 'other-skill', 'scripts'))
```

### Threshold Calibration Procedure

When a threshold changes in the canonical source (`metrics.py`):

1. **Patch `metrics.py`** — single source of truth
2. **Verify** `test_classifier.py` passes (it imports canonical → tests the new threshold)
3. **Verify** `test_integration.py` passes (imports canonical through the pipeline)
4. **Update** SKILL.md thresholds table + confidence formula if changed
5. **Update** `guardrails.md` if guard conditions changed
6. **Run both test suites** to confirm consistency

### Known Pitfall: Threshold Drift Across 4 Skills

This ecosystem spans 4 skills that share thresholds (γ, T_ops, rate_op, C_K):

```
thm-metrics-engine/metrics.py     ← canonical (SINGLE SOURCE OF TRUTH)
k-vector-collector/collector.py   ← provides K-vector only (no thresholds)
k-aware-orchestrator/*.md         ← documents thresholds
checkpoint-protocol/checkpoint.py ← uses thresholds for checkpoint type
```

**Root cause of drift:** Every skill had its own copy of threshold constants. When `k-aware-orchestrator` v1.1 changed γ from 0.3→0.15, `metrics.py` and `checkpoint-protocol` were left behind.

**Prevention:**

1. **`metrics.py` is the canonical source** — all threshold logic lives here
2. **`test_classifier.py` imports from `metrics.py`** (graceful fallback) — tests the canonical, not a copy
3. **`checkpoint-protocol/checkpoint.py` must manually sync** `GAMMA_SOFT`, `GAMMA_HARD` etc. when `metrics.py` thresholds change
4. **Always run all 4 test suites** after any threshold change:

```powershell
$env:PYTHONIOENCODING='utf-8'
python .hermes/skills/mlops/thm-metrics-engine/scripts/test_metrics.py
python .hermes/skills/mlops/k-vector-collector/scripts/test_collector.py
python .hermes/skills/devops/k-aware-orchestrator/scripts/test_classifier.py
python .hermes/skills/devops/k-aware-orchestrator/scripts/test_integration.py
```

### Threshold Synchronization Checklist

When changing any threshold (e.g., γ from 0.15 to something else):

| # | Location | Action |
|---|----------|--------|
| 1 | `metrics.py` | Update `classify_regime()`, `classify_fallback()`, `estimate_confidence()` |
| 2 | `checkpoint.py` | Update `GAMMA_SOFT`, `GAMMA_HARD`, `GAMMA_EMERGENCY` constants |
| 3 | `k-aware-orchestrator/SKILL.md` | Update priority logic, confidence formulas, checkpoint triggers |
| 4 | `k-aware-orchestrator/references/guardrails.md` | Update threshold documentation |
| 5 | `checkpoint-protocol/SKILL.md` | Update trigger conditions table |
| 6 | All test suites | Add a test case AT the boundary to verify (e.g., if threshold=0.15, test gamma=0.16→Decayed and gamma=0.14→not Decayed) |

### Current Ecosystem State

All 4 skills exist with full implementations and tests:

| Skill | Script | Tests | Coverage |
|-------|--------|-------|----------|
| `thm-metrics-engine` | `metrics.py` | `test_metrics.py` | 36 tests ✅ |
| `k-vector-collector` | `collector.py` | `test_collector.py` | 39 tests ✅ |
| `k-aware-orchestrator` | — (meta-skill) | `test_classifier.py` + `test_integration.py` | 106 tests ✅ |
| `checkpoint-protocol` | `checkpoint.py` | (via integration) | 181 total across ecosystem ✅ |

### Windows-Specific Notes

- **cp874 encoding:** All Python scripts require `$env:PYTHONIOENCODING='utf-8'` before running to avoid UnicodeEncodeError on Thai Windows
- **No `python3`:** Use `python` not `python3` on Windows
- **Path resolution:** Use `os.path.dirname(os.path.abspath(__file__))` — never hardcode `/opt/...`
