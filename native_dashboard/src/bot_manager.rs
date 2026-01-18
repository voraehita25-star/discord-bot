use serde::{Deserialize, Serialize};
use std::fs;
use std::io::{BufRead, BufReader};
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
}

impl BotManager {
    pub fn new(base_path: PathBuf) -> Self {
        Self { base_path }
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
    fn is_dev_watcher_running(&self) -> bool {
        if let Some(pid) = self.get_dev_watcher_pid() {
            let mut sys = System::new();
            sys.refresh_processes(sysinfo::ProcessesToUpdate::All);
            sys.process(sysinfo::Pid::from_u32(pid)).is_some()
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

    #[allow(dead_code)]
    fn log_file(&self) -> PathBuf {
        self.base_path.join("logs").join("bot.log")
    }

    pub fn get_pid(&self) -> Option<u32> {
        fs::read_to_string(self.pid_file())
            .ok()?
            .trim()
            .parse()
            .ok()
    }

    pub fn is_running(&self) -> bool {
        if let Some(pid) = self.get_pid() {
            let mut sys = System::new();
            sys.refresh_processes(sysinfo::ProcessesToUpdate::All);
            sys.process(sysinfo::Pid::from_u32(pid)).is_some()
        } else {
            false
        }
    }

    pub fn get_uptime(&self) -> String {
        let pid_file = self.pid_file();
        if !pid_file.exists() || !self.is_running() {
            return "-".to_string();
        }

        if let Ok(metadata) = fs::metadata(&pid_file) {
            if let Ok(modified) = metadata.modified() {
                let start: DateTime<Local> = modified.into();
                let now = Local::now();
                let duration = now.signed_duration_since(start);

                let hours = duration.num_hours();
                let mins = duration.num_minutes() % 60;
                let secs = duration.num_seconds() % 60;

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

    pub fn get_memory_mb(&self) -> f64 {
        if let Some(pid) = self.get_pid() {
            let mut sys = System::new();
            sys.refresh_processes(sysinfo::ProcessesToUpdate::All);
            if let Some(process) = sys.process(sysinfo::Pid::from_u32(pid)) {
                return process.memory() as f64 / 1024.0 / 1024.0;
            }
        }
        0.0
    }

    pub fn get_mode(&self) -> String {
        // Check if dev_watcher.pid exists and the watcher is running
        if let Some(pid) = self.get_dev_watcher_pid() {
            let mut sys = System::new();
            sys.refresh_processes(sysinfo::ProcessesToUpdate::All);
            if sys.process(sysinfo::Pid::from_u32(pid)).is_some() {
                return "Dev".to_string();
            }
        }
        if self.is_running() {
            "Normal".to_string()
        } else {
            "-".to_string()
        }
    }

    pub fn get_status(&self) -> BotStatus {
        BotStatus {
            is_running: self.is_running(),
            pid: self.get_pid(),
            uptime: self.get_uptime(),
            memory_mb: self.get_memory_mb(),
            mode: self.get_mode(),
        }
    }

    pub fn start(&self) -> Result<String, String> {
        if self.is_running() {
            return Err("Bot is already running".to_string());
        }

        let bot_script = self.base_path.join("bot.py");
        
        Command::new("python")
            .arg(&bot_script)
            .current_dir(&self.base_path)
            .creation_flags(CREATE_NO_WINDOW)
            .spawn()
            .map_err(|e| format!("Failed to start bot: {}", e))?;

        std::thread::sleep(std::time::Duration::from_secs(2));

        if self.is_running() {
            Ok("Bot started successfully".to_string())
        } else {
            Err("Bot failed to start".to_string())
        }
    }

    pub fn start_dev(&self) -> Result<String, String> {
        if self.is_running() {
            return Err("Bot is already running".to_string());
        }

        // Stop any existing dev watcher first
        self.stop_dev_watcher();

        let dev_watcher = self.base_path.join("scripts").join("dev_watcher.py");
        
        // Dev mode: run dev_watcher.py hidden with CREATE_NO_WINDOW
        let child = Command::new("python")
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

    pub fn stop(&self) -> Result<String, String> {
        let pid = self.get_pid().ok_or("Bot is not running")?;
        
        if !self.is_running() {
            return Err("Bot is not running".to_string());
        }

        // IMPORTANT: Stop dev_watcher FIRST so it doesn't restart the bot
        self.stop_dev_watcher();

        // Windows: taskkill (hidden) with /T to kill child processes too
        Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/F", "/T"])
            .creation_flags(CREATE_NO_WINDOW)
            .output()
            .map_err(|e| format!("Failed to stop bot: {}", e))?;

        // Delete PID file
        let _ = fs::remove_file(self.pid_file());

        Ok("Bot stopped".to_string())
    }

    pub fn restart(&self) -> Result<String, String> {
        if self.is_running() {
            self.stop()?;
            std::thread::sleep(std::time::Duration::from_secs(1));
        }
        self.start()
    }
}

pub fn read_recent_logs(count: usize) -> Vec<String> {
    let log_path = PathBuf::from(r"C:\Users\ME\BOT\logs\bot.log");
    
    if !log_path.exists() {
        return vec![];
    }

    let file = match fs::File::open(&log_path) {
        Ok(f) => f,
        Err(_) => return vec![],
    };

    let reader = BufReader::new(file);
    let lines: Vec<String> = reader.lines().filter_map(|l| l.ok()).collect();
    
    lines.into_iter().rev().take(count).rev().collect()
}
