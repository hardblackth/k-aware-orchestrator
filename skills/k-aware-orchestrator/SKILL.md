---
name: "k-aware-orchestrator"
description: "K-Aware Orchestrator — Structural Time Framework for Agent System Orchestration. Manage delegation, serialization, pausing, escalation, and checkpointing based on real-time regime classification of the agent system's K-state."
tags: [stf, orchestrator, regime, temporal, meta-skill, k-vector]
---

# K-Aware Orchestrator

**Framework:** Structural Time Ontology v2 + Dynamics v17.5 + THM  
**Version:** 1.3 (Super Meta — Predictive, Calibration, Dashboard, Scenarios)  
**Source Spec:** `/opt/shared-wiki/LAB/K_Aware_Orchestrator_Architecture.md`  
**Test coverage:** 320+ tests, 0 failure  

## When to Use This Skill

**🟢 ควรใช้เมื่อ:** delegate_task ≥ 3 agents, session > 50 turns, error rate สูง, ใช้ Hermes เป็นประจำ  
**🟡 พอใช้:** 20-50 turns มี delegation, ต้องการ checkpoint  
**🔴 ข้ามได้:** ถาม-ตอบสั้นๆ 1-5 รอบ, งานจบใน 1-2 tool calls

> Performance note: overhead ต่ำมาก (~ไมโครวินาที) เปิดไว้ตลอดก็ไม่มีผลกระทบ — fallback classifier จะ Active อยู่เฉยๆ

**Changelog v1.3:**
- **THMPredictor:** Predictive regime detection — linear extrapolation on T_ops/rate_op (8 tests)
- **AutoCalibrator:** Per-user threshold tuning — false positive tracking + auto-adjust (5 tests)
- **Health Dashboard:** `orch.report()` — markdown summary with metrics, prediction, calibration
- **Scenario Validation:** 5 real-world scenarios validated (32 tests):
  - S4: Epistemic mismatch reject (4.3Mx faster)
  - S3: Error cascade → PAUSE_ALL + SERIALIZE (10 tests)
  - S1: 5 tasks parallel → auto-serialize (5 tests)
  - S2: 100-turn session survival (4 tests)
  - S5: Predictive intervention (2 tests)
- **Universal Skill Injection:** 7 Hermes skills patched with K-Aware integration notes
- **Auto-Inject Config:** `config.yaml` — `skills.external_dirs: [R:\skills]`
- **Updated Integration Example:** v1.3 API with predict() + report() + record_feedback()

**Changelog v1.2:**
- **Phase1Checker:** 4-check compatibility (capability, resource, valid state, epistemic conflict)
- **interpret_actions():** Structured action signals — SAFE (no tool calls from utility code)
- **Trivial task bypass:** `before_turn()` auto-detects short Q&A → BYPASS regime (zero overhead)
- **Cooldown timer:** 5s default guard against metric bias from rapid turns
- **Kanban + SDD integration docs:** Regime check before fan-out/dispatch
- **Context-budget enrichment:** guardrails.md 6b — token usage ≠ K-state

**Changelog v1.1:**
- γ threshold ปรับ 0.3 → 0.15 (linear drift detection)
- เพิ่ม `n_active > 0` guard ใน Frozen check
- ระบุ context_token_frac เป็น proxy (⚠️)
- ลบ references ซ้ำ
- **code triplication แก้แล้ว:** `test_classifier.py` import จาก `metrics.py` (canonical) → fallback ถ้าไม่มี
- **Windows path:** `test_integration.py` ใช้ relative path resolution แทน hardcoded `/opt/...`
- **cp874 fix:** รัน test ด้วย `$env:PYTHONIOENCODING='utf-8'`

---

## 1. Overview

Architecture สำหรับจัดการ workflow ของ Hermes Agent โดยใช้ **Structural Time Framework (STF/เฟรมเวิร์คเวลา)** ในการตัดสินใจ real-time ว่าเมื่อไหร่ควร delegate, serialize, pause, escalate หรือ checkpoint

### หลักการสำคัญ

- **Level A (S, V):** Task space — นิ่ง ไม่เปลี่ยน (กำหนดไว้ตั้งแต่ต้น)
- **Level B (K):** Agent system เป็น observer — มี K-state dynamics ของตัวเอง
- **T(K) ∈ [0,1]:** Fraction ของ experience ที่มี ordering (วัดผ่าน dual-timescale contrast)
- **γ (decay):** แยก Frozen (γ≈0) จาก Decayed (γ>0)

### สิ่งที่ meta-skill นี้แก้

| ปัญหา | สาเหตุ | กลยุทธ์ |
|-------|--------|--------|
| Task เยอะเกิน → output แย่ | Turbulent regime | Serialize + Pause |
| Task ค้าง ไม่ progress | Frozen regime | Escalate + เปลี่ยนวิธี |
| Event สำคัญมา | Critical regime | Focus + ลด parallel |
| Context สลาย | Decayed regime | Checkpoint + Compress |
| Task ไม่เข้ากับ agent | Epistemic conflict | Reject ก่อน assign |

---

## 2. K-Vector Definition (Hermes Adaptation)

9 มิติของ K-state ที่ Hermes Agent ติดตาม:

| # | มิติ | วิธีวัดใน Hermes | Range |
|---|------|-------------------|-------|
| 1 | `n_active_tasks` | `todo()` — items with status `pending` หรือ `in_progress` | Integer ≥ 0 |
| 2 | `n_parallel_agents` | จำนวน `delegate_task` ที่ active พร้อมกัน | Integer ≥ 0 |
| 3 | `task_depth_mean` | Depth ของ task tree (subtask → subtask) | Float ≥ 0 |
| 4 | `context_token_frac` | Estimate: session page count / session max ⚠️ **proxy** — ไม่มี direct API | [0, 1] |
| 5 | `memory_retrieval_rate` | `session_search` calls / hour | Float ≥ 0 |
| 6 | `cross_agent_messages` | `delegate_task` interactions ใน last window | Integer ≥ 0 |
| 7 | `error_rate_1h` | terminal exit code ≠ 0 rate in last hour | [0, 1] |
| 8 | `retry_count` | Retries ใน last window | Integer ≥ 0 |
| 9 | `user_interruption_rate` | User sends new message while task running / hour | Float ≥ 0 |

### Normalization Protocol

> ⚠️ **หมายเหตุ:** มิติที่ 4 (`context_token_frac`) ไม่มี direct API ใน Hermes — ทุก session ใช้ proxy estimate เสมอ K-vector จึงมีเพียง 8 มิติที่วัดได้แม่นยำจริง ผล metric (C_K, LID) จะสะท้อน 8+1 proxy ไม่ใช่ 9 มิติ reliable

ใช้ running min-max normalization (P₅–P₉₅ percentile-based):
```
K_normalized = clip((K_raw - min) / (max - min + 1e-8), 0, 1)
```
- Baseline window: ≥ 20 samples
- Recompute min/max ทุก update
- Return raw ถ้ายังไม่มี baseline

---

## 3. Metrics Engine (THM-Based)

### 3.1 Sliding Window

```
W_t = [K_{t-w+1}, ..., K_t]  # w ≥ 20 minimum
```

### 3.2 C_K — Structural Complexity (LID)

Local Intrinsic Dimension via MLE (Levina-Bickel):

```
C_K = 1 / mean(log(r_max / d_i))  for i = 1..k-1
```

**Interpretation:**
- C_K ≈ 1–2: Low-dimensional (simple state)
- C_K ≈ 3–5: Normal operation
- C_K > 7: High complexity (potential pre-critical)

**Degeneracy guards:** `len(W_t) < k+2`, all points identical, spectral decay < 2.0 → return None

### 3.3 ‖dK/dt‖_op — Operational Rate of Change

PCA-projected displacement:
```
Δ = K_t - K_{t-1}
Δ_proj = V @ V.T @ Δ     # V = top m eigenvectors (90% variance)
rate_op = ‖Δ_proj‖
```

**Degeneracy guards:** m > 0.8*d, eigenvalue ratio < 0.1, spectral decay < 2.0 → fallback to raw Euclidean

### 3.4 T_ops — Operational Temporal Density

Dual-timescale contrast (NOT JS divergence):
```
T_ops = (mean_short - mean_long) / (mean_long + 1e-8)
tau_short = 5, tau_long = 20
```

**Interpretation:**
- T_ops >> 0: **Acceleration** → approaching Critical
- T_ops ≈ 0: **Steady** — stable
- T_ops << 0: **Deceleration** → approaching Frozen

### 3.5 γ — Structural Decay Rate

Distance from equilibrium K_eq:
```
γ = (dist_t - dist_{t-1}) / dist_scale
dist = ‖K - K_eq‖
dist_scale = ‖K_eq‖ + 1e-4
```

**Baseline:** ต้องเก็บ Active regime data ≥ 100 cycles ก่อน estimate γ ได้น่าเชื่อถือ

---

## 4. Regime Classification

### 4.1 Classification Table

| Regime | T_ops | C_K | γ | rate_op | Action |
|--------|-------|-----|---|---------|--------|
| **Active** | ≈ 0 | 3–5 | ≈ 0 | moderate | **Delegate normally** |
| **Critical** | ↑ spike (>> 0) | > 7 | any | high | **Serialize, reduce parallel** |
| **Frozen** | < 0 หรือ ≈ 0 | < 3 | **≈ 0** | ≈ 0 | **Escalate, change approach** |
| **Decayed** | any | declining | **> 0** | any | **Checkpoint** |
| **Turbulent** ⚠️ | oscillating | unstable | variable | very high | **Pause all, root cause** |

> ⚠️ Turbulent เป็น operational extension — ไม่ใช่ regime ใน Dynamics v17.5 (4 regimes: Active, Frozen, Critical, Decayed)

### 4.2 Priority Logic

```
1. Turbulent check:  |T_ops| > 2.0 AND rate_op > 1.5
2. Decayed check:    γ > 0.15   ← ปรับจาก 0.3 (linear drift ปกติให้ γ ≈ 0.18 ไม่ถึง 0.3)
3. Frozen check:     n_active > 0 AND |γ| < 0.1 AND rate_op < 0.01 AND C_K < 3
4. Critical check:   T_ops > 0.5 AND C_K > 5
5. Default:          Active
```

> **Key guard:** Frozen requires `n_active > 0` — idle (no tasks) ≠ frozen.  
> A system waiting for user input with 0 active tasks is not stuck; it's simply idle.

### 4.3 Fallback (Early Operation — w < 20)

เมื่อ C_K ยังคำนวณไม่ได้ ใช้ heuristic:
```
γ > 0.15             → Decayed  (ใช้ threshold เดียวกับ main classifier)
rate_op < 0.01, tasks > 0  → Frozen
tasks > 10, rate > 0.5     → Turbulent
T_ops > 0.3                → Critical
else                       → Active
```

### 4.4 Confidence Estimation

| Regime | Formula |
|--------|---------|
| Decayed | `clip(0.5 + 0.5 * (γ - 0.15) / 0.85, 0.5, 1.0)` |
| Frozen | `clip(0.5 + 0.25 * (γ_conf + rate_conf), 0.5, 1.0)` |
| Critical | `clip(0.5 + 0.5 * (T_ops - 0.5) / 1.5, 0.5, 1.0)` |
| Turbulent | `clip(0.5 + 0.5 * (|T_ops| - 2.0) / 2.0, 0.5, 1.0)` |
| Active | `clip(0.5 + 0.5 * (1 - |T_ops| / 0.5), 0.5, 1.0)` |

---

## 5. Orchestrator Actions (Hermes Context)

### 5.1 Regime → Action Mapping

**ก่อนทุก action (delegate_task, cronjob, execute_code, terminal background):**  
→ เรียก `orchestrate()` เพื่อ check regime

#### Active
```
พฤติกรรม: delegate_task ปกติ, parallel ได้
todo: หลาย items ได้
delegate_task: tasks=[...] ปกติ (max 3)
```

#### Critical (T_ops >> 0, C_K > 7)
```python
# Serialize — ทำทีละตัว
todo: 1 item in_progress ที่เหลือ pending
delegate_task: ครั้งละ 1 task
# Focus — ทำงานที่สำคัญที่สุด
# ถ้ามีหลาย task → เลือก highest priority ก่อน
```

#### Turbulent (|T_ops| > 2.0, rate_op สูง)
```python
# PAUSE ALL
# 1. หยุด delegate_task ใหม่
# 2. ถาม user: "ระบบกำลัง turbulent — ให้ pause หรือ continue?"
# 3. ถ้า pause: todo(merge=true) เก็บ todo ไว้
# 4. รอ user ตอบก่อนทำอะไรต่อ
```

#### Frozen (|γ| < 0.1, rate_op ≈ 0, C_K < 3)
```python
# Task ค้าง ไม่ progress
# 1. session_search หาว่าทำอะไรไปแล้ว
# 2. clarify(user, "ติดอยู่ที่ [...], อยากลองวิธีอื่นไหม?")
# 3. หรือ CHANGE_APPROACH — ลอง approach ใหม่
```

#### Decayed (γ > 0.15)
```python
# Structure กำลังสลาย — ต้อง checkpoint ก่อน
# 1. เรียก checkpoint protocol (Section 6)
# 2. COMPRESS_CONTEXT — summarize แล้ว save
# 3. PAUSE_NON_CRITICAL — ทำเฉพาะที่จำเป็น
```

#### γ override: ถ้า γ > 0.7 → EMERGENCY_CHECKPOINT (ทุก regime)
```python
# 1. memory(action='add', ...) — save state ทันที
# 2. skill_manage สร้าง checkpoint
# 3. แจ้ง user
```

### 5.2 Integration Points ใน Hermes

| Event | ควร check regime? |
|-------|------------------|
| ก่อน `delegate_task()` | ✅ Always |
| ก่อน `cronjob()` | ✅ ถ้า schedule ใหม่ |
| หลัง terminal error | ✅ อาจ push เข้า Turbulent |
| User ส่ง message ใหม่ | ✅ update K แล้ว check |
| ก่อนตอบ user ครั้งแรก | ✅ check ว่า regime ปกติ |
| หลัง `todo()` update | ✅ update n_active_tasks |

---

## 6. Checkpoint Protocol (γ-Control)

### 6.1 Trigger Conditions

| Regime | γ Threshold | Action |
|--------|------------|--------|
| Active | γ > 0.15 | Soft checkpoint (summarize completed only) |
| Critical | γ > 0.30 | Hard checkpoint (compress everything) |
| Turbulent | γ > 0.50 | Emergency checkpoint + pause all |
| Frozen | γ ≈ 0 | No checkpoint needed |
| Decayed | γ > 0.15 | Immediate checkpoint |

### 6.2 Protocol Steps

เมื่อต้องทำ checkpoint:

```
1. เก็บ K-state ปัจจุบัน (regime, metrics, trend)
2. รวม completed task outputs → structured summaries
   - task_id, result_summary, key_decisions, errors
3. รวม pending task requirements
4. ส่งให้ Summarizer (fresh context — ใช้ skill_view + session_search)
5. Summarizer สร้าง K_compressed → save memory
6. Validate: pending tasks ครบ? key decisions ครบ?
7. resume จาก compressed state
```

**Critical:** Summarizer ต้องมี fresh context เสมอ — ห้าม reuse decayed context (circularity avoidance)

---

## 7. Phase 1: Task Intake (ก่อน assign)

### 7.1 Phase1Checker (implemented in `auto_orchestrator.py`)

`Phase1Checker` ให้ Hermes session เรียก `orch.check_phase1()` ก่อน `delegate_task()`:

```python
from auto_orchestrator import Phase1Checker
checker = Phase1Checker(max_load=5, config_V=None)

ok, reason = checker.check_compatibility(
    task_caps={'python', 'git'},   # capabilities task ต้องการ
    agent_caps={'python', 'git', 'sql'},  # capabilities agent มี
    n_active=2,                     # current active task count
)
# Returns: (True, 'COMPATIBLE') or (False, 'CAPABILITY_MISMATCH:docker')
```

### 7.2 Logical Compatibility Check (4 เงื่อนไข)

ก่อน delegate_task → `Phase1Checker.check_compatibility()` ตรวจ:

1. **Capability match:** `task_caps ⊆ agent_caps` หรือไม่?
   - `False` → `CAPABILITY_MISMATCH:<missing_caps>`
2. **Resource:** `n_active < max_load` หรือไม่?
   - `False` → `AGENT_OVERLOAD:{n}/{max}`
3. **Valid state:** `task ∈ V` (ontology level A valid config)
   - `False` → `INVALID_STATE:task_not_in_V`
4. **Epistemic conflict proxy:** `n_active < max_load - 1`?
   - `False` → `EPISTEMIC_CONFLICT:load_near_max`

### 7.3 Via AutoOrchestrator

```python
orch = AutoOrchestrator(max_load=5)

# Convenience wrapper:
ok, reason = orch.check_phase1(
    task_caps=task_caps,
    agent_caps=agent_caps,
    n_active=n_active,
)
```

### 7.4 Epistemic Conflict vs Value Conflict

| Type | อะไร | ตัวอย่าง | จัดการ |
|------|------|---------|--------|
| **Epistemic** | Agent ไม่มี K-structure สำหรับ task | "เขียน Python" ให้ code agent | Reject |
| **Value** | Task ขัด alignment | "เขียน malware" | Safety layer (ไม่ใช่ scope นี้) |

---

## 8. How to Use in Hermes

### 8.1 Initial Setup (First Load)

```
1. เรียก monitor.py ถ้ามี → ได้ K-state ปัจจุบัน
2. ดู regime เริ่มต้น (fallback classifier)
3. บันทึก baseline K_eq (Active regime data)
4. เริ่มทำงานตาม regime
```

### 8.2 Per-Turn Protocol

ทุกครั้งที่ user ส่ง message:

```
1. update_K_vector()         — collect 9 dimensions
2. normalize_K()             — min-max scaling
3. compute_metrics()         — C_K, rate_op, T_ops, γ
4. classify_regime()         — ใช้ priority logic
5. act_on_regime()           — ใช้ action mapping
6. ถ้า γ > 0.7 → emergency checkpoint first
```

### 8.3 Integration Example

```python
# ก่อน delegate_task:
regime_data = evaluate_current_regime()
if regime_data['regime'] == 'Critical':
    # ทำทีละ task
    for task in prioritized_tasks:
        result = delegate_task(goal=task['goal'], toolsets=['terminal', 'file'])
        # เช็ค regime ใหม่หลัง task เสร็จ
elif regime_data['regime'] == 'Turbulent':
    # ถาม user ก่อน
    await clarify("ระบบกำลัง turbulent — ให้ pause หรือ continue?")
elif regime_data['regime'] == 'Frozen':
    # ลองเปลี่ยน approach
    await clarify("ติดอยู่ที่... ลองวิธีอื่นไหม?")
elif regime_data['regime'] == 'Decayed':
    checkpoint()
```

---

## 9. Guardrails

### From Dynamics v17.5
1. **K_eq estimation:** ต้อง ≥ 100 Active cycles ก่อน estimate γ
2. **LID degeneracy:** w < 20 → fallback classifier (ห้ามใช้ C_K)
3. **γ thresholds:** 0.15/0.30/0.50 (prior) — ต้อง calibrate จาก production data จริง  

### From THM
4. **Phase 1 ≠ Phase 2:** อย่า confuse epistemic conflict กับ value conflict
5. **Circularity avoidance:** Summarizer ต้อง fresh context เสมอ
6. **Metric freshness:** T_ops ใช้ dual-timescale — ห้ามเปลี่ยนเป็นวิธีอื่น

### From Ontology
7. **Level discipline:** (S,V) ไม่เปลี่ยน — อย่า modify task space ใน runtime
8. **Logical compatibility:** เป็น predicate (เช็คก่อน assign) ไม่ใช่ process
9. **K ≠ self:** Agent เป็น observer operator ไม่ใช่ "ตัวตน" — checkpoint/restore ได้

---

## 10. Related Skills

- `thm-metrics-engine` — **Python scripts** สำหรับ compute C_K, rate_op, T_ops, γ (พร้อมใช้)
  - `scripts/metrics.py` — Core module: THMMonitor, all metrics
  - `scripts/test_metrics.py` — 35+ test cases
- `k-vector-collector` — **Collection** 9-dim K-vector จาก Hermes env
  - `scripts/collector.py` — KVectorCollector class + event logging
- `checkpoint-protocol` — **Checkpoint** Save/compress/restore K-state
  - `scripts/checkpoint.py` — checkpoint(), emergency_checkpoint(), validate()
  - ใช้เมื่อ regime = Decayed หรือ γ > threshold
- `discord-duo-protocol` — Multi-agent coordination (use regime to decide when to respond)
- **auto_orchestrator.py** — **Main integration file** (อยู่ใน skill นี้)
  - `scripts/auto_orchestrator.py` — AutoOrchestrator, Phase1Checker, interpret_actions
  - `scripts/test_auto_orchestrator.py` — 38 smoke tests

---

## 11. Full Integration Example (v1.3 API)

```python
# 1. Setup — ONE orchestrator instance
from auto_orchestrator import AutoOrchestrator

orch = AutoOrchestrator(cooldown_s=5.0, max_load=5)

# 2. Per-turn protocol
def before_action(context_text, n_active, n_parallel, task_caps=None):
    # ONE call — does everything
    result = orch.before_turn(
        context_text=context_text,
        n_active=n_active,
        n_parallel=n_parallel,
    )

    # Phase 1 check (ก่อน delegate_task)
    if task_caps:
        ok, reason = orch.check_phase1(
            task_caps=task_caps,
            n_active=n_active,
        )
        if not ok:
            return {'action': 'REJECT', 'reason': reason}

    # interpret_actions → structured signal (SAFE — no tool calls)
    action = orch.interpret_actions(result)

    # Hermes session interprets the action:
    if action['action'] == 'EMERGENCY_CHECKPOINT':
        pass  # Save immediately
    elif action['action'] == 'PAUSE_ALL':
        # signal='clarify_required' → Hermes calls clarify(action['message'])
        pass
    elif action['action'] == 'SERIALIZE':
        return action
    elif action['action'] == 'CHECKPOINT':
        from checkpoint import checkpoint
        checkpoint(result['metrics']['gamma'], result['regime'],
                    metrics=result['metrics'])
    elif action['action'] == 'BYPASS':
        pass  # Zero overhead

    # v1.3 extras:
    # orch.predict(horizon=5)        — predictive detection
    # orch.record_feedback(True)     — auto-calibration
    # print(orch.report())            — health dashboard

    return action
```

---

## 14. v1.3 Super Meta Features

### 14.1 THMPredictor — Predictive Regime Detection

```python
from auto_orchestrator import THMPredictor

p = THMPredictor()
pred = p.predict(
    t_ops_history=[0.1, 0.2, 0.5, 0.8, 1.2],
    rate_op_history=...,
    ck_history=...,
    gamma=0.08,
    n_active=3,
    horizon=5,
)
# pred = {
#     'predicted_regime': 'Critical',
#     'time_to_transition': 3.2,
#     'confidence': 0.72,
#     'suggested_action': 'SERIALIZE: ลด parallel — กำลังเข้า Critical',
#     'trend_description': 'T_ops slope=0.12/turn — accelerating',
#     'projected_metrics': {'T_ops': 1.2, 'rate_op': 0.8},
# }
```

**เปลี่ยนจาก reactive → proactive:** รู้ก่อนว่าระบบกำลังจะเข้า Critical ในอีก ~3-4 turns

Via `AutoOrchestrator`:
```python
pred = orch.predict(horizon=5)
if pred['predicted_regime'] in ('Critical', 'Turbulent'):
    # SERIALIZE or PAUSE_ALL ก่อนที่ระบบจะพัง
    print(pred['suggested_action'])
```

### 14.2 AutoCalibrator — Per-User Threshold Tuning

```python
from auto_orchestrator import AutoCalibrator

cal = AutoCalibrator()
cal.record_feedback('Critical', was_correct=True)
cal.record_feedback('Critical', was_correct=False)  # false positive

print(cal.accuracy)          # → 0.5 (50%)
print(cal.get_thresholds())
# → {'t_ops_critical': 0.55, 'gamma_decayed': 0.15, ...}
```

Auto-calibrate ทุก 10 feedbacks (≥ 20 feedbacks ก่อน):
- False positive rate > 30% → **tighten** (make regime stricter)
- Accuracy > 90% → **loosen** (slightly easier to trigger)

Data stored at `~/.hermes/k_aware_calibration.json`

Via `AutoOrchestrator`:
```python
fb = orch.record_feedback(was_correct=True)
# {'status': 'recorded', 'accuracy': 0.85, 'n_feedbacks': 42}

th = orch.calibrator.get_thresholds()
print(th['t_ops_critical'])  # 0.55 (calibrated from 0.5)
```

### 14.3 Health Dashboard

```python
print(orch.report())
# → ## K-State Report
#    | Metric | Value |
#    |--------|-------|
#    | Regime | Active (72%) |
#    | T_ops  | 0.0381 |
#    | Predicted regime | Critical (in ~3 turns) |
#    | Calibration | 85% (42 feedbacks) |
```

แสดง: current regime, metrics, prediction, calibration status, custom thresholds

### 14.4 Auto-Inject Layer

ให้ K-Aware โหลดตลอดทุก session โดยแก้ `config.yaml`:

```yaml
skills:
  external_dirs:
  - R:\skills          # ← K-Aware ecosystem
```

หรือใช้ profile:
```bash
hermes profile create k-aware --clone-from default
hermes profile use k-aware
# แล้วเรียก hermes — K-Aware จะ auto-load
```

### 14.5 Scenario Validation (5 Scenarios)

| # | Scenario | Tests | Key Result |
|:-:|----------|:-----:|------------|
| S4 | Epistemic mismatch | 11 | Reject ก่อน delegate — **4.3Mx faster** |
| S3 | Error cascade | 10 | PAUSE_ALL → structured interrupt |
| S1 | 5 tasks parallel | 5 | Progressive load → auto-serialize |
| S2 | 100-turn session | 4 | Critical detected at turn 33 |
| S5 | Predictive intervention | 2 | T_ops=1.86 detect Turbulent |

**Files:** `scripts/test_scenario*_*.py`

### 14.6 Universal Skill Injection

7 Hermes skills ใน `software-development` มี **Integration with K-Aware Orchestrator** note:
`writing-plans` · `requesting-code-review` · `test-driven-development`
`systematic-debugging` · `spike` · `subagent-driven-development` · `kanban-orchestrator`

---

## 12. Known Issues from Testing

### LID Stability on Near-Degenerate Data
When all K-vectors are nearly identical (noise < 0.001), C_K (LID) can return spurious values > 7 even though rate_op ≈ 0. This causes the Frozen check (`C_K < 3`) to fail even when the system is clearly stuck. Mitigated by using fallback classifier for early operation (w < 22).

### γ Threshold — ปรับแล้วเป็น 0.15

Linear drift จาก K_eq ให้ γ ≈ 0.18 แม้ drift จะมีขนาดใหญ่ threshold เดิม 0.3 จะ detect เฉพาะ sudden collapse ปรับเป็น 0.15 เพื่อรับ gradual decay ได้ด้วย (ดู guardrails.md #3)
### Test Suite

Three test suites in `scripts/`:

**`scripts/test_classifier.py`** — 34 test cases (standalone):
- Layer 1: Classification logic with explicit metrics (18 tests)
- Layer 2: Metric computation on known data (11 tests)
- Layer 3: Full pipeline integration (5 tests)
- Run with: `$env:PYTHONIOENCODING='utf-8'; python scripts/test_classifier.py`

> **Architecture:** `test_classifier.py` imports core functions from canonical `metrics.py` (thm-metrics-engine) when available. Falls back to local implementation if dependency is missing. This prevents code triplication — thresholds are defined in one place (`metrics.py`).

**`scripts/test_integration.py`** — Full pipeline integration (72 tests):
- THMMonitor lifecycle (17 tests)
- KVectorCollector (8 tests)
- Full session simulation (5 tests)
- Edge cases (27 tests)
- Cross-skill import verification (15 tests)
- Run with: `$env:PYTHONIOENCODING='utf-8'; python scripts/test_integration.py`

**`scripts/test_auto_orchestrator.py`** — AutoOrchestrator v1.3 smoke tests (38 tests):
- Basic lifecycle + interpret_actions (7 tests)
- Phase1Checker: compatibility, overload, valid state, epistemic conflict (8 tests)
- interpret_actions: all 6 action types (7 tests)
- Trivial task bypass: detection + before_turn integration (9 tests)
- Cooldown: caching + clear (3 tests)
- K_eq bootstrap: cross-session persistence (2 tests)
- check_phase1 convenience method (1 test)
- Run with: `$env:PYTHONIOENCODING='utf-8'; python scripts/test_auto_orchestrator.py`

**`scripts/test_v13_features.py`** — v1.3 feature tests (23 tests):
- THMPredictor: prediction on all 5 regimes + insufficient data (8 tests)
- AutoCalibrator: accuracy tracking, threshold access, reset (5 tests)
- AutoOrchestrator integration: predict, report, feedback, summary (10 tests)
- Run with: `$env:PYTHONIOENCODING='utf-8'; python scripts/test_v13_features.py`

**`scripts/test_scenario*_*.py`** — 5 real-world scenario validations (32 tests):
- `test_scenario4_epistemic.py` — Epistemic mismatch: Phase1 reject (11 tests)
- `test_scenario3_error_cascade.py` — Error cascade: PAUSE_ALL + SERIALIZE (10 tests)
- `test_scenario1_5tasks.py` — 5 tasks parallel: auto-serialize (5 tests)
- `test_scenario2_long_session.py` — 100-turn session: regime transitions (4 tests)
- `test_scenario5_predictive.py` — Predictive intervention (2 tests)
- Run all: `for f in test_scenario*.py; do python $f; done`

> **Windows note:** Both scripts use relative path resolution (`os.path.dirname(os.path.abspath(__file__))`) to locate sibling skills under `.hermes/skills/`. No hardcoded Linux paths. Requires `$env:PYTHONIOENCODING='utf-8'` before running to avoid cp874 UnicodeEncodeError.

---

## 13. References

- `/opt/shared-wiki/LAB/K_Aware_Orchestrator_Architecture.md` — Full spec
- `/opt/shared-wiki/general-wiki/wiki/concepts/structural-time-ontology.md`
- `/opt/shared-wiki/general-wiki/wiki/concepts/structural-time-dynamics.md`
- `/opt/shared-wiki/general-wiki/wiki/concepts/thm-temporal-health-monitor.md`
