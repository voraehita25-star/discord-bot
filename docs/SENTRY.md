# Sentry Error Tracking Guide

## Dashboard Access

**URL:** <https://sentry.io>

### Login

1. ไป <https://sentry.io/auth/login/>
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

## Configuration

### .env

```ini
SENTRY_DSN=https://xxx@xxx.ingest.sentry.io/xxx
SENTRY_ENVIRONMENT=production       # optional — read by bot.py at startup
```

### ปรับแต่ง (optional)

แก้ไขใน `utils/monitoring/sentry_integration.py`:

```python
init_sentry(
    dsn=os.getenv("SENTRY_DSN"),
    environment="production",  # หรือ "staging", "development"
    sample_rate=1.0,           # 1.0 = 100% errors
    traces_sample_rate=0.1,    # 0.1 = 10% performance traces
)
```

### Opt-out

วางไฟล์ว่าง `data/telemetry_optout.flag` เพื่อปิด Sentry ทั้งหมด — `init_sentry()` จะ
ตรวจไฟล์นี้ตอนเริ่มและ skip การ initialize ถ้าพบ ทำให้ไม่ต้องลบ DSN ออกจาก `.env`

---

## 📝 Manual Usage

```python
from utils.monitoring.sentry_integration import (
    capture_exception,
    capture_message,
    set_user_context,
    add_breadcrumb,
)

# จับ exception (signature: capture_exception(error, context=None, user_id=None, guild_id=None))
try:
    risky_operation()
except Exception as e:
    capture_exception(e, user_id=123, guild_id=456)

# ส่ง message (signature: capture_message(message, level="info", context=None))
capture_message("Something happened", level="warning")

# ผูก user identity เข้ากับเหตุการณ์ทั้งหมดของ session นี้
set_user_context(user_id=123, username="me_no_you")

# เก็บ breadcrumb สำหรับ debug ลำดับเหตุการณ์ก่อน error
add_breadcrumb(
    "user invoked /play",
    category="command",
    level="info",
    data={"query": "song-name"},
)
```

---

## 🔔 Alerts (Optional)

1. ไป Settings → Alerts
2. Create Alert Rule
3. ตั้งเงื่อนไข เช่น: ส่ง email เมื่อมี error ใหม่

---

## 📈 Performance Monitoring

ดูได้ที่ **Performance** tab - แสดง response times และ throughput
