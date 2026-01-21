# 📋 Release Notes - v3.3.9

**Release Date:** January 22, 2026  
**Type:** Patch Release (Bug Fix + Dependencies)

---

## 🔧 Bug Fixes

### 1. Shutdown Manager Logging Error
- **Issue:** `ValueError: I/O operation on closed file` เกิดขึ้นเมื่อ Python interpreter shutdown
- **Cause:** พยายาม log ข้อความหลังจาก stdout/stderr ถูกปิดแล้วใน atexit handler
- **Fix:** เพิ่ม `logging.raiseExceptions = False` เพื่อ suppress logging errors ระหว่าง shutdown
- **File:** `utils/reliability/shutdown_manager.py`

### 2. Flaky Performance Test
- **Issue:** `test_measure_context_manager` fail บน Windows เพราะ timing ไม่แม่นยำ (9.91ms vs 10ms)
- **Fix:** เพิ่ม tolerance ให้ test (sleep 15ms, assert >= 9ms)
- **File:** `tests/test_performance_tracker.py`

---

## 📦 New Dependencies

เพิ่ม dependencies ที่เป็น optional ก่อนหน้านี้ให้เป็น default:

| Package | Version | Description |
|---------|---------|-------------|
| `winshell` | 0.6 | Windows shell integration (shortcuts) |
| `pywin32` | 311 | Windows COM automation |
| `tiktoken` | 0.12.0 | Accurate token counting สำหรับ AI |
| `prometheus-client` | 0.24.1 | Metrics & monitoring |

---

## 📊 Test Results

```
===================== 452 passed in 2.71s =====================
```

✅ All 452 tests passing

---

## 📝 Files Changed

| File | Change |
|------|--------|
| `version.txt` | 3.3.8 → 3.3.9 |
| `requirements.txt` | เพิ่ม 4 dependencies |
| `README.md` | อัปเดต version และวันที่ |
| `DEVELOPER_GUIDE.md` | อัปเดต version และวันที่ |
| `utils/reliability/shutdown_manager.py` | แก้ไข atexit handler |
| `tests/test_performance_tracker.py` | แก้ไข flaky test |

---

## ⬆️ Upgrade Instructions

```bash
# อัปเดต dependencies
pip install -r requirements.txt

# หรือติดตั้ง packages ใหม่โดยตรง
pip install winshell pywin32 tiktoken prometheus-client
```

---

**Full Changelog:** v3.3.8 → v3.3.9
