# Regime → Action Reference

Cheatsheet สำหรับเลือก action ตาม regime classification

---

## Quick Reference

| Regime | Hermes Action | คำอธิบาย |
|--------|--------------|---------|
| 🟢 **Active** | Delegate ปกติ | todo หลาย items, delegate_task tasks=[...], parallel 3 |
| 🟡 **Critical** | Serialize + Focus | todo 1 item, delegate_task ครั้งละ 1, focus highest priority |
| 🔴 **Turbulent** | Pause + Ask | หยุด delegate_task, ถาม user ก่อน |
| 🔵 **Frozen** | Escalate + Change | ถาม user เปลี่ยนวิธี, session_search หาอะไรที่ค้าง |
| ⚫ **Decayed** | Checkpoint + Compress | Save state → compress → resume |
| 🚨 **γ > 0.7** | Emergency Checkpoint | ใช้ทุก regime — save memory ทันที |

---

## Detailed Decision Trees

### 🟢 Active Regime
```
T_ops ≈ 0, C_K 3–5, γ ≈ 0, rate_op moderate

→ delegate_task ปกติ
  tasks=[...] → parallel สูงสุด 3
→ todo ปกติ
→ ไม่ต้องทำ checkpoint
```

### 🟡 Critical Regime
```
T_ops > 0.5, C_K > 5, rate_op สูง

→ SERIALIZE
  todo: 1 item in_progress, ที่เหลือ pending
→ REDUCE_PARALLEL
  delegate_task ครั้งละ 1 task เท่านั้น
→ FOCUS
  เลือก highest priority task ก่อน
→ MONITOR
  เช็ค regime ทุก task เสร็จ — อาจกลับมา Active หรือแย่ลง
```

### 🔴 Turbulent Regime
```
|T_ops| > 2.0, rate_op > 1.5, C_K unstable

→ PAUSE_ALL
  delegate_task ใหม่ = หยุด
  cronjob ใหม่ = หยุด
→ ASK USER
  clarify("ระบบกำลัง turbulent — ให้ pause หรือ continue?")
→ ROOT_CAUSE
  ถ้า user เลือก continue → session_search หาว่าอะไรผิด
→ WAIT
  รอ user ก่อนทำอะไรต่อ
```

### 🔵 Frozen Regime
```
|γ| < 0.1, rate_op < 0.01, C_K < 3, tasks > 0

→ IDENTIFY
  session_search หา task ที่ค้าง
→ ESCALATE
  clarify("ติดอยู่ที่ [task], อยากลองวิธีอื่นไหม?")
→ CHANGE_APPROACH
  ถ้า user ตอบ → ลอง approach ใหม่
  ถ้าไม่ตอบ → ถามอีกครั้ง หรือ offer ให้ cancel task
```

### ⚫ Decayed Regime
```
γ > 0.3, C_K declining

→ CHECKPOINT
  save: todo state + completed summaries + errors
→ COMPRESS_CONTEXT
  Summarize conversation → skill_manage or memory
→ PAUSE_NON_CRITICAL
  ทำเฉพาะ urgent tasks
→ RESUME
  หลังจาก checkpoint เสร็จ → เริ่มจาก compressed state
```

### 🚨 Emergency (γ > 0.7)
```
ใช้ได้ทุก regime — override

→ memory(action='add', target='memory', content='EMERGENCY CHECKPOINT: ...')
→ แจ้ง user ทันที
→ checkpoint force
```

---

## Scenario Examples

### Scenario 1: User ส่งงานทีเดียว 5 อย่าง
```
K: n_active_tasks=5, n_parallel=0, rate_op=0.3
→ Active (ยังว่าง) → delegate ปกติ 3+2
```

### Scenario 2: delegate_task 3 ตัวทำงาน — error กลับมา 2 ตัว
```
K: error_rate=0.66, retry_count=3, T_ops=1.2
→ Critical → serialize ที่เหลือ
```

### Scenario 3: User ถาม-ตอบ-ถาม-ตอบ เร็วมาก (interruption rate สูง)
```
K: user_interruption_rate=12/hour, rate_op=0.8, T_ops=2.5
→ Turbulent → pause + ask
```

### Scenario 4: delegate_task ค้าง 5 นาที ไม่มี response
```
K: rate_op=0.001, γ=0.01, C_K=1.2
→ Frozen → escalate
```

### Scenario 5: Session ยาว 100+ ข้อความ, memory ใกล้เต็ม
```
K: context_token_frac=0.85, γ=0.4
→ Decayed → checkpoint
```
