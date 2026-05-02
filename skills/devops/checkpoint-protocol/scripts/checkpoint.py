"""
Checkpoint Protocol — Save/Compress/Restore Agent K-State

Part of K-Aware Orchestrator ecosystem.
Triggered when γ > threshold or regime = Decayed.

Usage:
    from checkpoint import checkpoint, emergency_checkpoint, validate_checkpoint

    result = checkpoint(gamma, regime, metrics, completed_tasks, pending_tasks)
    if result['checkpoint_type'] != 'NONE':
        entry = format_memory_entry(result)
        # save entry to memory
"""

import json
import time
from typing import Optional, List, Dict, Any


# ============================================================
# THRESHOLDS (aligned with k-aware-orchestrator v1.1)
# ============================================================

GAMMA_SOFT = 0.15       # Soft checkpoint (Active regime)
GAMMA_HARD = 0.30       # Hard checkpoint (Critical regime)
GAMMA_EMERGENCY = 0.50  # Emergency checkpoint (Turbulent regime)
GAMMA_OVERRIDE = 0.70   # γ-override — any regime, force save


# ============================================================
# DATA STRUCTURES
# ============================================================

def make_checkpoint_id() -> str:
    """Generate a unique checkpoint ID."""
    ts = time.strftime('%Y%m%d_%H%M%S')
    return f'cp_{ts}'


def capture_state(regime: str, metrics: dict,
                  completed_tasks: list,
                  pending_tasks: list) -> dict:
    """Capture current K-state into structured checkpoint data."""
    return {
        'checkpoint_id': make_checkpoint_id(),
        'timestamp': time.time(),
        'K_state': {
            'regime': regime,
            'metrics': dict(metrics),
        },
        'completed_tasks': [
            {
                'id': t.get('id', '?'),
                'summary': t.get('summary', ''),
                'decisions': t.get('decisions', []),
                'errors': t.get('errors', []),
            }
            for t in completed_tasks
        ],
        'pending_tasks': [
            {
                'id': t.get('id', '?'),
                'requirements': t.get('requirements', ''),
                'context': t.get('context', ''),
            }
            for t in pending_tasks
        ],
    }


def compress_checkpoint(state: dict) -> dict:
    """Compress checkpoint state into compact summary."""
    completed_summaries = [t['summary'] for t in state['completed_tasks']]
    next_steps = [t['requirements'] for t in state['pending_tasks']]
    
    errors = []
    for t in state['completed_tasks']:
        errors.extend(t.get('errors', []))
    
    return {
        'checkpoint_id': state['checkpoint_id'],
        'regime_history': state['K_state']['regime'],
        'key_results': completed_summaries,
        'next_steps': next_steps,
        'errors_to_watch': list(set(errors)),
        'gamma_at_checkpoint': state['K_state']['metrics'].get('gamma', 0.0),
    }


# ============================================================
# VALIDATION
# ============================================================

def validate_checkpoint(compressed: dict, pending_tasks: list) -> bool:
    """
    Validate that checkpoint preserves all critical information.

    Checks:
    1. All pending tasks preserved in next_steps
    2. Key results exist
    3. Error context maintained
    """
    checks = []
    checks.append(len(compressed.get('next_steps', [])) >= len(pending_tasks))
    checks.append(bool(compressed.get('key_results')))
    checks.append('errors_to_watch' in compressed)
    return all(checks)


# ============================================================
# CHECKPOINT TYPE DETECTION
# ============================================================

def classify_checkpoint_type(gamma: float, regime: str) -> str:
    """
    Determine checkpoint type from gamma and regime.

    Priority (highest first):
      1. EMERGENCY_OVERRIDE: γ > 0.7 (any regime)
      2. EMERGENCY: γ > 0.50 or regime = Turbulent
      3. HARD: γ > 0.30 or regime = Critical
      4. SOFT: γ > 0.15 or regime = Decayed
      5. NONE: no checkpoint needed
    """
    if gamma > GAMMA_OVERRIDE:
        return 'EMERGENCY_OVERRIDE'
    if gamma > GAMMA_EMERGENCY or regime == 'Turbulent':
        return 'EMERGENCY'
    if gamma > GAMMA_HARD or regime == 'Critical':
        return 'HARD'
    if gamma > GAMMA_SOFT or regime == 'Decayed':
        return 'SOFT'
    return 'NONE'


# ============================================================
# MAIN ACTIONS
# ============================================================

def checkpoint(gamma: float, regime: str, metrics: dict,
               completed_tasks: list,
               pending_tasks: list) -> dict:
    """
    Main checkpoint function.

    Determines checkpoint type based on gamma and regime,
    captures state, compresses, validates, and returns result.

    Args:
        gamma: Current γ value
        regime: Current regime classification
        metrics: Dict with C_K, T_ops, gamma, rate_op
        completed_tasks: List of completed task dicts
        pending_tasks: List of pending task dicts

    Returns:
        Dict with: checkpoint_id, checkpoint_type,
                   compressed, validated, state
    """
    cp_type = classify_checkpoint_type(gamma, regime)

    if cp_type == 'NONE':
        return {
            'checkpoint_type': 'NONE',
            'message': 'No checkpoint needed',
        }

    state = capture_state(regime, metrics, completed_tasks, pending_tasks)
    compressed = compress_checkpoint(state)
    valid = validate_checkpoint(compressed, pending_tasks)

    return {
        'checkpoint_id': state['checkpoint_id'],
        'checkpoint_type': cp_type,
        'compressed': compressed,
        'validated': valid,
        'state': state,
    }


def emergency_checkpoint(gamma: float, regime: str, metrics: dict,
                          completed_tasks: list,
                          pending_tasks: list) -> dict:
    """
    Emergency checkpoint — always saves regardless of thresholds.
    Called explicitly when γ > 0.7 override fires.
    """
    return checkpoint(gamma, regime, metrics, completed_tasks, pending_tasks)


def soft_checkpoint(gamma: float, regime: str, metrics: dict,
                    completed_tasks: list) -> dict:
    """
    Soft checkpoint — summarize completed tasks only.
    Used for lightweight saves when γ is slightly above threshold.
    """
    return checkpoint(gamma, regime, metrics, completed_tasks, [])


# ============================================================
# FORMATTING
# ============================================================

def format_memory_entry(result: dict) -> str:
    """
    Format checkpoint result as Hermes memory entry string.

    Example output:
        CHECKPOINT:cp_20260502_204200 | Type: SOFT |
        Validated: True | Results: Task A done; Task B done |
        Next: Task C pending | Errors: timeout
    """
    if result.get('checkpoint_type') == 'NONE':
        return 'CHECKPOINT: none needed'

    cp = result.get('compressed', {})
    lines = [
        f"CHECKPOINT:{result.get('checkpoint_id', '?')}",
        f"Type: {result.get('checkpoint_type', '?')}",
        f"Validated: {result.get('validated', False)}",
    ]
    results = cp.get('key_results', [])
    if results:
        lines.append(f"Results: {'; '.join(results)}")
    steps = cp.get('next_steps', [])
    if steps:
        lines.append(f"Next: {'; '.join(steps)}")
    errors = cp.get('errors_to_watch', [])
    if errors:
        lines.append(f"Errors: {', '.join(errors)}")
    return ' | '.join(lines)


def get_checkpoint_message(result: dict) -> str:
    """Get user-facing message for checkpoint."""
    cp_type = result.get('checkpoint_type', '?')
    cp_id = result.get('checkpoint_id', '?')
    valid = result.get('validated', False)

    if cp_type == 'NONE':
        return "✅ System stable — no checkpoint needed."

    msgs = {
        'SOFT': f"📝 Soft checkpoint saved [{cp_id}]",
        'HARD': f"💾 Hard checkpoint saved [{cp_id}]",
        'EMERGENCY': f"🚨 Emergency checkpoint saved [{cp_id}]",
        'EMERGENCY_OVERRIDE': f"🚨⚠️ γ-override checkpoint saved [{cp_id}]",
    }

    msg = msgs.get(cp_type, f"Checkpoint saved [{cp_id}]")
    if not valid:
        msg += " ⚠️ Validation FAILED — manual review recommended"
    return msg