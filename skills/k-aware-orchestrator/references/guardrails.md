# Guardrails & Warnings

## From Structural Time: Dynamics v17.5

### 1. K_eq Estimation — ต้องมี Baseline
```
ต้องการ: ≥ 100 cycles ของ Active regime data
ก่อนมี baseline: gamma = None → ไม่ classify Frozen/Decayed
```
**ผลกระทบ:** ช่วงแรก (session ใหม่ๆ) จะใช้ fallback classifier เท่านั้น  
**วิธีแก้:** สะสม K-vector ทุก turn รอให้ครบ 100 cycles

### 2. LID Degeneracy — Early Window
```
w < 20 points: C_K = None (ไม่สามารถคำนวณ LID ได้)
ก่อน w ≥ 20: ใช้ fallback classifier
```
**ผลกระทบ:** ต้น session (20 turn แรก) จะไม่มี C_K  
**วิธีแก้:** fallback classifier ใช้ n_active_tasks + rate_op + T_ops + γ แทน

### 2b. LID Spurious Values on Near-Degenerate Data
```
พบจาก test: noise scale 0.0001 (very small) → LID returns > 7
สาเหตุ: LID มอง noise structure เป็น manifold ที่มี dimensionality
→ ถึงแม้ rate_op ≈ 0.001, C_K ก็ยัง > 3 → Frozen check ล้มเหลว
```
**วิธีแก้:**  
- ใช้ fallback classifier (w < 22) เพื่อหลีกเลี่ยง C_K ในการ classify Frozen  
- หรือเพิ่ม `noise_floor` check: ถ้า `max(rate_ops) < 0.005` → ถือว่า degenerate (ignore C_K)  
- หรือใช้ `classify_fallback()` เสมอสำหรับ Frozen detection

**Architecture Note:** ใน practice, K-vectors จะมี noise จาก tool calls อยู่แล้ว  
(terminal output, session_search results) ทำให้ปัญหานี้ไม่เกิดใน production จริง  
— เจอเฉพาะใน synthetic test data เท่านั้น

### 3. γ Threshold — ปรับแล้ว (0.3 → 0.15)
```
เดิม:  0.3 = Decayed soft, 0.5 = Decayed hard, 0.7 = Emergency
ปัจจุบัน: 0.15 = Decayed soft, 0.30 = Decayed hard, 0.50 = Emergency
เหตุผล: linear drift ปกติ (context เต็ม, error สะสม) ให้ γ ≈ 0.18
         threshold 0.3 จะ detect เฉพาะ sudden collapse — ช้าเกินไป
```

### 3b. γ Dynamics — Linear Drift Confirm
```
ทดสอบยืนยันแล้ว: linear drift 25 steps ไป 8 units → γ ≈ 0.184
threshold 0.15: detect ได้ (0.184 > 0.15) ✅
threshold 0.3: ไม่ detect (0.184 < 0.3) ❌ → นี่คือเหตุผลที่เปลี่ยน
```

**ยังต้อง:** Log ค่า γ ทุกครั้ง → ปรับจาก distribution จริงหลัง 1 สัปดาห์

---

## From THM (Temporal Health Monitor)

### 4. Phase 1 ≠ Phase 2 — อย่าสับสน

| Aspect | Phase 1 (Task Intake) | Phase 2 (Execution) |
|--------|---------------------|-------------------|
| Timing | ก่อน assign | ระหว่าง execute |
| Detect | Epistemic conflict | Operational problem |
| Action | Reject หรือ Route | Regime-based action |
| Failure pattern | "Task นี้ไม่เข้ากับ agent structure" | "Task กำลังมีปัญหา" |

⚠️ **Critical:** epistemic conflict (structural mismatch) ≠ value conflict (alignment)  
— ห้าม reject task เพราะ "มันไม่ดี" — reject เฉพาะเมื่อ agent ทำไม่ได้

### 5. Circularity Avoidance — Summarizer ต้อง Fresh Context
```
อย่า: reuse decayed context → เอา context ที่เต็ม/เสื่อมไป summarize
ต้อง: spawn fresh context → new session หรือ independent skill
```
**Hermes Practice:**  
ใช้ `skill_manage(action='create', ...)` หรือ `memory(action='add', ...)`  
ด้วยข้อมูล structured (ไม่ dump raw context)

### 6. T_ops: Dual-Timescale Only
```
ห้ามเปลี่ยน T_ops เป็น:
- JS divergence (ช้า, high-dim sparsity)
- Simple difference (noise-sensitive)
- Any single-timescale metric

ต้องใช้: dual-timescale EWMA (τ_short=5, τ_long=20) เท่านั้น
```
เหตุผล: dual-timescale contrast ให้ signal-to-noise ratio ที่ดีที่สุด  
สำหรับ acceleration/deceleration detection ใน agent workflow

### 6b. Context-Budget Enrichment (จาก SDD context-budget-discipline.md)

> ⚠️ **สำคัญ:** Token usage ≠ K-state dynamics — อย่า map 1:1

SDD context-budget-discipline.md ใช้ 4 tiers: PEAK / GOOD / DEGRADING / POOR  
ซึ่งวัด **token usage** (resource constraint, level 0)  
ส่วน K-Aware วัด **structural dynamics** (K-state, level B)

| สถานการณ์ | Token Usage | K-State |
|-----------|:-----------:|:-------:|
| ทำงานง่าย 80 turns, smooth | POOR (70%+) | **Active** — T_ops≈0 |
| สั่ง delegate 10 tasks, 5 รอบแรก | PEAK (10%) | **Turbulent** — rate_op สูง |

**วิธีใช้ร่วมกัน (enrichment, ไม่ใช่ replacement):**

```python
# enrichment heuristic: context token pressure → override regime
if context_tier == 'POOR' and regime == 'Active':
    # ถึง Active แต่ context ใกล้เต็ม — ควร checkpoint
    regime = 'Decayed'    # override
    actions.append('CHECKPOINT')
    
if context_tier == 'PEAK' and regime == 'Critical':
    # context ยังว่างมาก — ignore resource constraint, focus on dynamics
    pass  # keep Critical classification
```

**Context budget tier → recommendation (cross-reference):**
| Context Tier | Token % | K-Aware Signal | Recommended Action |
|--------------|:-------:|----------------|--------------------|
| PEAK | 0-30% | Any regime | Use full regime action |
| GOOD | 30-50% | Any regime | Prefer frontmatter reads |
| DEGRADING | 50-70% | Critical+ | Serialize + warn user |
| POOR | 70%+ | Any | **Checkpoint regardless of regime** |

---

## From Structural Time: Ontology v2

### 7. Level Discipline — (S,V) ไม่เปลี่ยนใน Runtime
```
❌ ผิด: เพิ่ม capability ให้ agent กลางคันเพื่อรับ task
❌ ผิด: เปลี่ยน valid configuration rules ขณะ execute
✅ ถูก: Reject task ที่ incompatible → แจ้ง user
```

(S, V) = task space — abstract structure ที่นิ่ง  
การเปลี่ยน (S, V) ขณะ runtime = violation ของ ontological assumption

### 8. Logical Compatibility = Predicate, ไม่ใช่ Process
```
❌ ผิด: ลอง assign task → ถ้า fail ค่อย reject
✅ ถูก: เช็ค compatibility ก่อน assign → 4 checks (capability, resource, valid state, epistemic conflict)
```

### 9. K ≠ Self — Agent เป็น Observer Operator
```
K = operator ที่สร้าง ordering ≤_K จาก (S,V)
K ไม่ใช่ "ตัวตน" ของ agent
```

**ผลเชิงปฏิบัติ:**
- Agent สามารถ checkpoint/restore K-state ได้ — ไม่ใช่ "ตาย"
- Regime change ≠ personality change
- K decay ≠ agent failure — แค่ structure กำลังเปลี่ยน

---

## K-Collector Gotchas

### Dimension 4: context_token_frac
```
ไม่มี API อ่าน context token usage โดยตรงใน Hermes
→ ใช้ proxy: session page count / estimated max
→ หรือ: number of tool calls in last N turns
```

### Dimension 7: error_rate_1h
```
terminal exit code ≠ 0 คือ error
แต่ browser timeout, web_search fail ก็เป็น error
→ นับ tool failures ทั้งหมด
```

### Threshold Tuning Record
เก็บ log ของ metric เขียนลง memory เพื่อ calibration:

```python
# ตัวอย่าง log entry
memory(action='add', target='memory',
    content='K threshold log: T_ops=1.8 when task overload->Turbulent (correct)')
```
