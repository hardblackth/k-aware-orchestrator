# Orchestration Log

ใช้ติดตาม K-state และ regime classification ใน session

---

## Log Template

```
## [timestamp] K-Aware Orchestrator Log

### K-Vector
| มิติ | ค่า | Normalized |
|------|-----|-----------|
| n_active_tasks | 3 | 0.45 |
| n_parallel_agents | 2 | 0.33 |
| task_depth_mean | 1.5 | 0.25 |
| context_token_frac | 0.6 | 0.60 |
| memory_retrieval_rate | 0.5 | 0.10 |
| cross_agent_messages | 4 | 0.40 |
| error_rate_1h | 0.1 | 0.10 |
| retry_count | 1 | 0.15 |
| user_interruption_rate | 2 | 0.20 |

### Metrics
| Metric | ค่า | Interpretation |
|--------|-----|---------------|
| C_K (LID) | 4.2 | Moderate complexity |
| rate_op | 0.35 | Normal movement |
| T_ops | 0.12 | Slight acceleration |
| γ | 0.05 | Stable near equilibrium |

### Classification
| Regime | Confidence | Trend |
|--------|-----------|-------|
| Active | 0.85 | STABLE |

### Actions Taken
- delegate_task: 3 tasks → serialized (2 done, 1 running)
- checkpoint: none needed

### Notes
- γ threshold still prior — log for calibration
```

---

## Quick Log (Minimal)

ถ้าอยาก log แบบสั้น:
```
[14:23] K=[3,2,1.5,0.6,0.5,4,0.1,1,2] → Active (0.85) | CK=4.2 ro=0.35 T=0.12 γ=0.05
```

Format:
```
[เวลา] K=[dim1,dim2,...,dim9] → Regime (confidence%) | CK=... ro=... T=... γ=...
```
