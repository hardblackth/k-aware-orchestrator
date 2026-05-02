# Skill Upgrade Workflow

Procedure for upgrading a Hermes skill across versions — used for K-Aware Orchestrator v1.1→v1.3.

## The 6-Step Cycle

```
1. GAP ANALYSIS   → Read existing code + SKILL.md → identify gaps
                     Write proposal to F:\_Ai\temp\review*.md
                     
2. IMPLEMENT      → Edit code files (auto_orchestrator.py, etc.)
                     Do ONE logical change at a time
                     
3. TEST           → Run existing tests first (verify nothing broke)
                     Run new feature tests (verify new code)
                     Target: 0 failure
                     
4. DOCUMENT       → Update SKILL.md (changelog, new sections, test count)
                     Update wiki (Q:\general-wiki\wiki\concepts\...)
                     
5. SYNC           → Copy all changed files to alternate paths
                     C: → R:\skills (Linux path)
                     Verify: import test on destination
                     
6. VALIDATE       → Run scenario tests if applicable
                     Confirm with user
```

## Principles

- **Sequential steps:** ทำ 1 2 3 ตามลำดับ — never skip ahead
- **Test before document:** verify code works before updating docs
- **Review before implement:** write `F:\_Ai\temp\review*.md` proposal first, get user feedback
- **No cascade:** never fix two things in one edit — one change per round
- **Sync both ways:** C: is working, R: is deploy — both must match

## Pitfalls

- **SKILL.md version mismatch:** updating code but forgetting the changelog. Always update Version + Test coverage + Changelog at the end.
- **Cross-skill breakage:** patching one skill (e.g., k-aware-orchestrator) may affect another (e.g., checkpoint-protocol). Run ALL test suites, not just the changed one.
- **Windows path sync:** `R:\skills\` is NOT the same as `C:\Users\ACER\.hermes\skills\`. Relative imports resolve differently. Always test `from auto_orchestrator import ...` on R: after sync.
- **Cooldown masking:** rapid test loops hit the 5s cooldown. Use `AutoOrchestrator(cooldown_s=0.0)` in tests to force fresh updates.
