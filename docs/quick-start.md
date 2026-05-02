# Quick Start

## Prerequisites

- [Hermes Agent](https://hermes-agent.nousresearch.com) installed
- Python 3.10+

## Installation

### Option 1: Copy skills directly

```bash
# Clone or copy the skills directory to your Hermes skills folder
cp -r skills/ ~/.hermes/skills/

# Or use external_dirs in config.yaml:
# skills:
#   external_dirs:
#     - /path/to/k-aware-orchestrator/skills
```

### Option 2: Hermes Skill Install (coming soon)

```bash
hermes skills install k-aware-orchestrator
```

## First Use

### 1. Run the smoke test

```bash
cd skills/devops/k-aware-orchestrator/scripts
$env:PYTHONIOENCODING='utf-8'
python test_auto_orchestrator.py
```

Expected output: `ALL TESTS PASSED ✅`

### 2. Load in a Hermes session

```bash
hermes -s k-aware-orchestrator
```

### 3. Use in your Python code

```python
from auto_orchestrator import AutoOrchestrator

# Create orchestrator
orch = AutoOrchestrator(cooldown_s=5.0, max_load=5)

# Every agent turn — one call
result = orch.before_turn(
    context_text=current_conversation,
    n_active=len(pending_todos),
    n_parallel=len(active_delegations),
)

# Get structured action
action = orch.interpret_actions(result)
if action['action'] == 'PAUSE_ALL':
    # signal='clarify_required' — ask user
    pass
elif action['action'] == 'SERIALIZE':
    # One task at a time
    pass

# Check task compatibility before delegation
ok, reason = orch.check_phase1(
    task_caps={'python', 'git'},
    agent_caps={'python', 'sql'},
    n_active=2,
)

# Predict future regime
pred = orch.predict(horizon=5)
if pred['predicted_regime'] in ('Critical', 'Turbulent'):
    print(pred['suggested_action'])

# Get health dashboard
print(orch.report())

# Record feedback for calibration
orch.record_feedback(was_correct=True)
```

## Auto-Inject (Optional)

ให้ K-Aware โหลดตลอดทุก session:

```yaml
# ~/.hermes/config.yaml
skills:
  external_dirs:
  - /path/to/k-aware-orchestrator/skills
```

หรือสร้าง profile:

```bash
hermes profile create k-aware --clone-from default
hermes profile use k-aware
hermes -s k-aware-orchestrator
```

## Run All Tests

```bash
cd skills/devops/k-aware-orchestrator/scripts
$env:PYTHONIOENCODING='utf-8'
python test_classifier.py
python test_integration.py
python test_auto_orchestrator.py
python test_v13_features.py
python test_scenario4_epistemic.py
python test_scenario3_error_cascade.py
python test_scenario1_5tasks.py
python test_scenario2_long_session.py
python test_scenario5_predictive.py
```

Expected: All pass, 0 failure.
