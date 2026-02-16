use serde::{Deserialize, Serialize};
use std::fs;
use std::io::{Read, Seek, SeekFrom};
use std::path::PathBuf;
use std::process::Command;
use std::os::windows::process::CommandExt;
use sysinfo::System;
use chrono::{DateTime, Local};

const CREATE_NO_WINDOW: u32 = 0x08000000;

#[derive(Debug, Serialize, Deserialize)]
pub struct BotStatus {
    pub is_running: bool,
    pub pid: Option<u32>,
    pub uptime: String,
    pub memory_mb: f64,
    pub mode: String,
}

pub struct BotManager {
    base_path: PathBuf,
    sys: System,
    python_cmd: String,
}

#[allow(dead_code)]
impl BotManager {
    pub fn new(base_path: PathBuf) -> Self {
        let mut sys = System::new();
        sys.refresh_processes(sysinfo::ProcessesToUpdate::All);
        // Use PYTHON_CMD env var or default to "python"
        let python_cmd = std::env::var("PYTHON_CMD").unwrap_or_else(|_| "python".to_string());
        Self { base_path, sys, python_cmd }
    }

    fn pid_file(&self) -> PathBuf {
        self.base_path.join("bot.pid")
    }

    fn dev_watcher_pid_file(&self) -> PathBuf {
        self.base_path.join("dev_watcher.pid")
    }

    fn get_dev_watcher_pid(&self) -> Option<u32> {
        fs::read_to_string(self.dev_watcher_pid_file())
            .ok()?
            .trim()
            .parse()
            .ok()
    }

    #[allow(dead_code)]
    fn is_dev_watcher_running(&mut self) -> bool {
        if let Some(pid) = self.get_dev_watcher_pid() {
            self.sys.refresh_processes(sysinfo::ProcessesToUpdate::All);
            self.sys.process(sysinfo::Pid::from_u32(pid)).is_some()
        } else {
            false
        }
    }

    fn stop_dev_watcher(&self) {
        if let Some(pid) = self.get_dev_watcher_pid() {
            let _ = Command::new("taskkill")
                .args(["/PID", &pid.to_string(), "/F", "/T"])
                .creation_flags(CREATE_NO_WINDOW)
                .output();
            let _ = fs::remove_file(self.dev_watcher_pid_file());
        }
    }

    pub fn log_file(&self) -> PathBuf {
        self.base_path.join("logs").join("bot.log")
    }

    pub fn logs_dir(&self) -> PathBuf {
        self.base_path.join("logs")
    }

    pub fn data_dir(&self) -> PathBuf {
        self.base_path.join("data")
    }

    pub fn base_path(&self) -> &PathBuf {
        &self.base_path
    }

    pub fn read_logs(&self, count: usize) -> Vec<String> {
        let log_path = self.log_file();
        
        if !log_path.exists() {
            return vec![];
        }

        let file = match fs::File::open(&log_path) {
            Ok(f) => f,
            Err(_) => return vec![],
        };

        // Read from end of file to avoid loading entire file into memory
        let metadata = match file.metadata() {
            Ok(m) => m,
            Err(_) => return vec![],
        };
        
        let file_size = metadata.len();
        if file_size == 0 {
            return vec![];
        }
        
        // Read at most 1MB from end of file (enough for ~count lines)
        let max_read: u64 = std::cmp::min(file_size, (count as u64).saturating_mul(1024)); // ~1KB per line estimate
        let max_read = std::cmp::min(max_read, 1024 * 1024); // Cap at 1MB
        let start_pos = file_size.saturating_sub(max_read);
        
        let mut file = file;
        if file.seek(SeekFrom::Start(start_pos)).is_err() {
            return vec![];
        }
        
        // Read as raw bytes and convert with lossy UTF-8 to avoid
        // corruption when seek lands on a multi-byte character boundary
        let mut raw_bytes = Vec::new();
        if file.read_to_end(&mut raw_bytes).is_err() {
            return vec![];
        }
        let buffer = String::from_utf8_lossy(&raw_bytes);
        
        let lines: Vec<String> = buffer.lines()
            .map(|l| l.to_string())
            .collect();
        
        // If we started mid-file, skip potentially partial first line
        let skip = if start_pos > 0 { 1 } else { 0 };
        lines.into_iter()
            .skip(skip)
            .rev()
            .take(count)
            .collect::<Vec<_>>()
            .into_iter()
            .rev()
            .collect()
    }

    /// Rotate logs if file exceeds max_size_mb
    pub fn rotate_logs_if_needed(&self, max_size_mb: f64) -> Result<(), String> {
        let log_path = self.log_file();
        
        if !log_path.exists() {
            return Ok(());
        }

        let metadata = fs::metadata(&log_path)
            .map_err(|e| format!("Failed to get log metadata: {}", e))?;
        
        let size_mb = metadata.len() as f64 / 1024.0 / 1024.0;
        
        if size_mb > max_size_mb {
            // Rotate: rename current to .old and create new
            let old_log = log_path.with_extension("log.old");
            let _ = fs::remove_file(&old_log); // Remove old backup if exists
            fs::rename(&log_path, &old_log)
                .map_err(|e| format!("Failed to rotate logs: {}", e))?;
        }
        
        Ok(())
    }

    /// Health check - verify bot process is actually responsive
    pub fn health_check(&mut self) -> bool {
        if !self.is_running() {
            return false;
        }
        
        // Check if process exists and is not zombie
        if let Some(pid) = self.get_pid() {
            self.sys.refresh_processes(sysinfo::ProcessesToUpdate::All);
            if let Some(process) = self.sys.process(sysinfo::Pid::from_u32(pid)) {
                // Check memory > 0 indicates process is alive
                return process.memory() > 0;
            }
        }
        
        false
    }

    pub fn clear_logs(&self) -> Result<String, String> {
        let log_path = self.log_file();
        
        if !log_path.exists() {
            return Ok("No logs to clear".to_string());
        }

        // Truncate the file instead of deleting (keeps file but empties content)
        fs::write(&log_path, "")
            .map_err(|e| format!("Failed to clear logs: {}", e))?;
        
        Ok("Logs cleared".to_string())
    }

    pub fn get_pid(&self) -> Option<u32> {
        fs::read_to_string(self.pid_file())
            .ok()?
            .trim()
            .parse()
            .ok()
    }

    pub fn is_running(&mut self) -> bool {
        if let Some(pid) = self.get_pid() {
            self.sys.refresh_processes(sysinfo::ProcessesToUpdate::All);
            self.sys.process(sysinfo::Pid::from_u32(pid)).is_some()
        } else {
            false
        }
    }

    pub fn get_uptime(&mut self) -> String {
        let pid_file = self.pid_file();
        if !pid_file.exists() || !self.is_running() {
            return "-".to_string();
        }

        if let Ok(metadata) = fs::metadata(&pid_file) {
            if let Ok(modified) = metadata.modified() {
                let start: DateTime<Local> = modified.into();
                let now = Local::now();
                let duration = now.signed_duration_since(start);

                // Clamp to 0 to prevent negative uptime from clock skew
                let total_secs = duration.num_seconds().max(0);
                let hours = total_secs / 3600;
                let mins = (total_secs % 3600) / 60;
                let secs = total_secs % 60;

                if hours > 0 {
                    return format!("{}h {}m {}s", hours, mins, secs);
                } else if mins > 0 {
                    return format!("{}m {}s", mins, secs);
                } else {
                    return format!("{}s", secs);
                }
            }
        }
        "-".to_string()
    }

    pub fn get_memory_mb(&mut self) -> f64 {
        if let Some(pid) = self.get_pid() {
            self.sys.refresh_processes(sysinfo::ProcessesToUpdate::All);
            if let Some(process) = self.sys.process(sysinfo::Pid::from_u32(pid)) {
                return process.memory() as f64 / 1024.0 / 1024.0;
            }
        }
        0.0
    }

    pub fn get_mode(&mut self) -> String {
        // Check if dev_watcher.pid exists and the watcher is running
        if let Some(pid) = self.get_dev_watcher_pid() {
            self.sys.refresh_processes(sysinfo::ProcessesToUpdate::All);
            if self.sys.process(sysinfo::Pid::from_u32(pid)).is_some() {
                return "Dev".to_string();
            }
        }
        if self.is_running() {
            "Normal".to_string()
        } else {
            "-".to_string()
        }
    }

    pub fn get_status(&mut self) -> BotStatus {
        // Single process refresh for all status fields (instead of 3-5 separate refreshes)
        self.sys.refresh_processes(sysinfo::ProcessesToUpdate::All);
        
        let pid = self.get_pid();
        let is_running = pid.map(|p| self.sys.process(sysinfo::Pid::from_u32(p)).is_some()).unwrap_or(false);
        
        let uptime = if is_running { self.get_uptime_no_refresh() } else { "-".to_string() };
        let memory_mb = if is_running {
            pid.and_then(|p| self.sys.process(sysinfo::Pid::from_u32(p)))
                .map(|proc| proc.memory() as f64 / 1024.0 / 1024.0)
                .unwrap_or(0.0)
        } else { 0.0 };
        
        let mode = {
            let dev_running = self.get_dev_watcher_pid()
                .map(|p| self.sys.process(sysinfo::Pid::from_u32(p)).is_some())
                .unwrap_or(false);
            if dev_running { "Dev".to_string() }
            else if is_running { "Normal".to_string() }
            else { "-".to_string() }
        };
        
        BotStatus {
            is_running,
            pid,
            uptime,
            memory_mb,
            mode,
        }
    }
    
    /// Get uptime without refreshing processes (used by get_status which already refreshed)
    fn get_uptime_no_refresh(&self) -> String {
        let pid_file = self.pid_file();
        if !pid_file.exists() {
            return "-".to_string();
        }

        if let Ok(metadata) = fs::metadata(&pid_file) {
            if let Ok(modified) = metadata.modified() {
                let start: DateTime<Local> = modified.into();
                let now = Local::now();
                let duration = now.signed_duration_since(start);

                // Clamp to 0 to prevent negative uptime from clock skew
                let total_secs = duration.num_seconds().max(0);
                let hours = total_secs / 3600;
                let mins = (total_secs % 3600) / 60;
                let secs = total_secs % 60;

                if hours > 0 {
                    return format!("{}h {}m {}s", hours, mins, secs);
                } else if mins > 0 {
                    return format!("{}m {}s", mins, secs);
                } else {
                    return format!("{}s", secs);
                }
            }
        }
        "-".to_string()
    }

    pub fn start(&mut self) -> Result<String, String> {
        if self.is_running() {
            return Err("Bot is already running".to_string());
        }

        // Remove old PID file first
        let _ = fs::remove_file(self.pid_file());

        let bot_script = self.base_path.join("bot.py");
        
        let child = Command::new(&self.python_cmd)
            .arg(&bot_script)
            .current_dir(&self.base_path)
            .creation_flags(CREATE_NO_WINDOW)
            .spawn()
            .map_err(|e| format!("Failed to start bot: {}", e))?;

        // Get the spawned process ID
        let spawned_pid = child.id();

        // Wait for bot to fully start (up to 10 seconds)
        for _ in 0..20 {
            std::thread::sleep(std::time::Duration::from_millis(500));
            
            // Check if PID file exists and bot is running
            if self.pid_file().exists() && self.is_running() {
                return Ok("Bot started successfully".to_string());
            }
            
            // Check if spawned process died
            self.sys.refresh_processes(sysinfo::ProcessesToUpdate::All);
            if self.sys.process(sysinfo::Pid::from_u32(spawned_pid)).is_none() {
                // Process died - but check if bot.pid was written (bot may have restarted itself)
                if self.is_running() {
                    return Ok("Bot started successfully".to_string());
                }
                return Err("Bot process exited - check logs".to_string());
            }
        }

        // After 10 seconds, check final state
        if self.is_running() {
            Ok("Bot started successfully".to_string())
        } else {
            Ok("Bot starting... (taking longer than usual)".to_string())
        }
    }

    pub fn start_dev(&mut self) -> Result<String, String> {
        if self.is_running() {
            return Err("Bot is already running".to_string());
        }

        // Stop any existing dev watcher first
        self.stop_dev_watcher();

        let dev_watcher = self.base_path.join("scripts").join("dev_watcher.py");
        
        // Dev mode: run dev_watcher.py hidden with CREATE_NO_WINDOW
        let child = Command::new(&self.python_cmd)
            .arg(&dev_watcher)
            .current_dir(&self.base_path)
            .creation_flags(CREATE_NO_WINDOW)
            .spawn()
            .map_err(|e| format!("Failed to start dev watcher: {}", e))?;

        // Save dev_watcher PID for later cleanup
        let _ = fs::write(self.dev_watcher_pid_file(), child.id().to_string());

        std::thread::sleep(std::time::Duration::from_secs(3));

        if self.is_running() {
            Ok("Dev Watcher started (hot reload enabled)".to_string())
        } else {
            // Dev watcher takes time to start bot, check again
            std::thread::sleep(std::time::Duration::from_secs(2));
            if self.is_running() {
                Ok("Dev Watcher started (hot reload enabled)".to_string())
            } else {
                Ok("Dev Watcher launched - bot starting...".to_string())
            }
        }
    }

    pub fn stop(&mut self) -> Result<String, String> {
        let pid = self.get_pid().ok_or("Bot is not running")?;
        
        if !self.is_running() {
            return Err("Bot is not running".to_string());
        }

        // IMPORTANT: Stop dev_watcher FIRST so it doesn't restart the bot
        self.stop_dev_watcher();

        // Try graceful shutdown first (taskkill without /F sends WM_CLOSE)
        let _ = Command::new("taskkill")
            .args(["/PID", &pid.to_string()])
            .creation_flags(CREATE_NO_WINDOW)
            .output();

        // Wait up to 5 seconds for graceful exit
        let mut exited = false;
        for _ in 0..10 {
            std::thread::sleep(std::time::Duration::from_millis(500));
            self.sys.refresh_processes(sysinfo::ProcessesToUpdate::All);
            if self.sys.process(sysinfo::Pid::from_u32(pid)).is_none() {
                exited = true;
                break;
            }
        }

        // Force kill if still running
        if !exited {
            Command::new("taskkill")
                .args(["/PID", &pid.to_string(), "/F", "/T"])
                .creation_flags(CREATE_NO_WINDOW)
                .output()
                .map_err(|e| format!("Failed to stop bot: {}", e))?;
        }

        // Delete PID file
        let _ = fs::remove_file(self.pid_file());

        Ok("Bot stopped".to_string())
    }

    pub fn restart(&mut self) -> Result<String, String> {
        if self.is_running() {
            self.stop()?;
            // Wait for process to fully exit before restarting
            std::thread::sleep(std::time::Duration::from_secs(5));
        }
        self.start()
    }
}

// Legacy function removed - use BotManager::read_logs() instead
