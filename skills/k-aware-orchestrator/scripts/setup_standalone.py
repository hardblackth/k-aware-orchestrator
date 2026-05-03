#!/usr/bin/env python3
"""
Standalone setup for K-Aware Orchestrator outside the Hermes skill tree.

Resolves paths so auto_orchestrator.py can find its sibling skills
(thm-metrics-engine, k-vector-collector, checkpoint-protocol)
without depending on the `skills/devops/...` directory structure.

Usage:
    python setup_standalone.py

Then in your code:
    import setup_standalone  # run once at import time
    from auto_orchestrator import AutoOrchestrator

Or add to PYTHONPATH directly.
"""
import sys
import os

# Resolve paths from this script's location
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_SCRIPT_DIR)  # scripts/ → k-aware-orchestrator/

# Canonical structure: .../skills/devops/k-aware-orchestrator/scripts/
# We search upward for a `skills` directory
current = _PARENT
for _ in range(5):  # search up to 5 levels
    parent = os.path.dirname(current)
    skills_dir = os.path.join(parent, 'skills')
    if os.path.isdir(skills_dir):
        # Found skills/ → add sibling paths
        paths = [
            os.path.join(skills_dir, 'mlops', 'thm-metrics-engine', 'scripts'),
            os.path.join(skills_dir, 'mlops', 'k-vector-collector', 'scripts'),
            os.path.join(skills_dir, 'devops', 'checkpoint-protocol', 'scripts'),
        ]
        for p in paths:
            if os.path.isdir(p) and p not in sys.path:
                sys.path.insert(0, p)
                print(f"  [K-Aware] Added: {p}")
        paths_added = sum(1 for p in paths if os.path.isdir(p))
        if paths_added == 3:
            print("  [K-Aware] ✓ All sibling skills resolved")
        else:
            print(f"  [K-Aware] ⚠️ {paths_added}/3 sibling skills found")
        break
    current = parent
else:
    print("  [K-Aware] ⚠️ Could not locate skills/ directory")
    print("  HINT: Add each skill path manually to PYTHONPATH:")
    print("    export PYTHONPATH=/path/to/thm-metrics-engine/scripts:$PYTHONPATH")

if __name__ == '__main__':
    print("K-Aware Orchestrator — Standalone Setup")
    print("Paths now in sys.path:")
    for p in reversed(sys.path[:3]):
        print(f"  • {p}")
    print("\nImport test:")
    try:
        from auto_orchestrator import AutoOrchestrator
        orch = AutoOrchestrator()
        print(f"  ✓ AutoOrchestrator loaded (K_eq={orch.k_eq_bootstrapped})")
    except Exception as e:
        print(f"  ✗ {e}")
