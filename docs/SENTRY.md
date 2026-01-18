# Sentry Error Tracking Guide

## 📊 Dashboard Access

**URL:** https://sentry.io

### Login
1. ไป https://sentry.io/auth/login/
2. Login ด้วย account ที่สมัครไว้

### ดู Errors
1. เลือก Project: `discord-bot`
2. คลิก **Issues** ที่เมนูซ้าย
3. จะเห็น error ทั้งหมดพร้อม:
   - Error type และ message
   - จำนวนครั้งที่เกิด
   - Users ที่ได้รับผลกระทบ
   - Stack trace

---

## 🔧 Configuration

### .env
```ini
SENTRY_DSN=https://xxx@xxx.ingest.sentry.io/xxx
```

### ปรับแต่ง (optional)
แก้ไขใน `utils/monitoring/sentry_integration.py`:

```python
init_sentry(
    environment="production",  # หรือ "staging", "development"
    sample_rate=1.0,          # 1.0 = 100% errors
    traces_sample_rate=0.1    # 0.1 = 10% performance traces
)
```

---

## 📝 Manual Usage

```python
from utils.sentry_integration import capture_exception, capture_message

# จับ exception
try:
    risky_operation()
except Exception as e:
    capture_exception(e, user_id=123, guild_id=456)

# ส่ง message
capture_message("Something happened", level="warning")
```

---

## 🔔 Alerts (Optional)

1. ไป Settings → Alerts
2. Create Alert Rule
3. ตั้งเงื่อนไข เช่น: ส่ง email เมื่อมี error ใหม่

---

## 📈 Performance Monitoring

ดูได้ที่ **Performance** tab - แสดง response times และ throughput
