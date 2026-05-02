# Ecosystem Maintenance Guide

## The 4-Skill Architecture

```
skills/
└── mlops/
    ├── thm-metrics-engine/      ← CANONICAL source of truth
    │   ├── scripts/metrics.py       (all thresholds + math)
    │   └── scripts/test_metrics.py
    └── k-vector-collector/
        └── scripts/collector.py     (K-vector collection)
└── devops/
    ├── k-aware-orchestrator/    ← Orchestration meta-skill
    │   ├── scripts/test_classifier.py   (imports from canonical)
    │   └── scripts/test_integration.py  (imports from canonical)
    └── checkpoint-protocol/
        └── scripts/checkpoint.py       (imports thresholds)
```

## Single Source of Truth: `metrics.py`

All thresholds are **defined once** in `thm-metrics-engine/scripts/metrics.py`:

| Threshold | Variable in metrics.py |
|-----------|----------------------|
| γ Decayed | `gamma > 0.15` in `classify_regime()` |
| γ Emergency override | `gamma > 0.7` in `get_actions()` |
| Checkpoint Soft | `GAMMA_SOFT = 0.15` (in checkpoint.py, must match) |
| Checkpoint Hard | `GAMMA_HARD = 0.30` |
| Checkpoint Emergency | `GAMMA_EMERGENCY = 0.50` |
| Frozen rate_op | `rate_op < 0.01` |
| Critical T_ops | `T_ops > 0.5` |
| Turbulent \|T_ops\| | `\|T_ops\| > 2.0` |

## How Tests Import Canonical

`test_classifier.py` uses **graceful fallback import**:

```python
try:
    from metrics import (compute_C_K, classify_regime, ...)
    _CANONICAL = True
except ImportError:
    _CANONICAL = False
    # define local fallback ...

if not _CANONICAL:
    def compute_C_K(...): ...
```

This means:
- When `thm-metrics-engine` is present → tests the **real** canonical code
- When standalone → uses local fallback (tests the same logic)

## When Changing a Threshold

**Check ALL of these files:**

1. `thm-metrics-engine/scripts/metrics.py` — the canonical, 4 locations:
   - `classify_regime()` — γ Decayed threshold
   - `classify_fallback()` — same threshold for early operation
   - `estimate_confidence()` — formula uses threshold value
   - `get_actions()` — γ > 0.7 emergency override

2. `k-aware-orchestrator/SKILL.md` — priority logic, checkpoint table, action mappings

3. `devops/checkpoint-protocol/SKILL.md` — trigger conditions table

4. `devops/checkpoint-protocol/scripts/checkpoint.py` — GAMMA_SOFT/HARD/EMERGENCY constants

5. `k-aware-orchestrator/references/guardrails.md` — threshold documentation

6. All test files — update test data if it depends on exact threshold values

## Cross-Skill Dependency Graph

```
thm-metrics-engine/metrics.py
    ↑ imports         ↑ imports
    |                  |
test_classifier.py   test_integration.py
(k-aware-orch.)       (k-aware-orch.)
    ↑ imports         ↑ imports
    |                  |
collector.py -------- checkpoint.py
(k-vector-coll.)      (checkpoint-protocol)
```

## Runbook: Full Ecosystem Health Check

```powershell
$env:PYTHONIOENCODING='utf-8'
python .\skills\mlops\thm-metrics-engine\scripts\test_metrics.py
python .\skills\mlops\k-vector-collector\scripts\test_collector.py
python .\skills\devops\k-aware-orchestrator\scripts\test_classifier.py
python .\skills\devops\k-aware-orchestrator\scripts\test_integration.py
```

Expected: 181 tests, 0 failures.
