# Startup Scripts

สำหรับเริ่มต้น Discord Bot ในโหมดต่างๆ

## Quick Start

```powershell
# Production Mode
.\start.bat

# Dev Mode (Hot Reload)
.\dev.bat

# Bot Manager Console
.\manager.bat
```

## Files

| File | Description |
|------|-------------|
| `start.ps1` | Main bot launcher - auto-restart, health checks, crash reports |
| `start_dev.ps1` | Dev mode - hot reload เมื่อแก้ไขไฟล์ |
| `manager.ps1` | Interactive console สำหรับจัดการ bot |
| `_common.psm1` | Shared module - logging, health checks, display functions |
| `startup.json` | Configuration file |

## Configuration

แก้ไข `startup.json`:

```json
{
    "bot": {
        "max_restarts": 50,        // จำนวน restart สูงสุดก่อนหยุด
        "restart_delay_seconds": 10 // รอกี่วินาทีก่อน restart
    },
    "health": {
        "min_disk_space_gb": 1,    // Minimum disk space
        "min_memory_mb": 1024      // Minimum RAM
    }
}
```

## Features

- ✅ **Health Checks** - ตรวจสอบ Python, disk, memory, dependencies
- ✅ **Auto-Restart** - Restart อัตโนมัติเมื่อ crash
- ✅ **Crash Reports** - บันทึก crash log ไปที่ `logs/crashes/`
- ✅ **Hot Reload** - (Dev mode) Restart เมื่อแก้ไขไฟล์

## Logs

- `logs/startup.log` - Startup/shutdown events
- `logs/crashes/` - Crash reports
