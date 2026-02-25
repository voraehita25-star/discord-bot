#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod bot_manager;
mod database;

use bot_manager::{BotManager, BotStatus};
use database::{DatabaseService, DbStats, ChannelInfo, UserInfo};
use std::sync::{Arc, Mutex};
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, State, WindowEvent,
};

struct AppState {
    bot_manager: Arc<Mutex<BotManager>>,
    db_service: Mutex<DatabaseService>,
}

// Helper macro to safely lock mutex and handle poisoned state
macro_rules! lock_bot_manager {
    ($state:expr) => {
        $state.bot_manager.lock()
            .map_err(|e| format!("Failed to acquire bot manager lock: {}", e))
    };
}

macro_rules! lock_db_service {
    ($state:expr) => {
        $state.db_service.lock()
            .map_err(|e| format!("Failed to acquire database lock: {}", e))
    };
}

#[tauri::command]
fn get_status(state: State<AppState>) -> Result<BotStatus, String> {
    match state.bot_manager.try_lock() {
        Ok(mut manager) => Ok(manager.get_status()),
        Err(_) => {
            // Lock is held by start/stop/restart — return busy status
            // so the UI doesn't freeze waiting for the mutex
            Ok(BotStatus {
                is_running: false,
                pid: None,
                uptime: "...".to_string(),
                memory_mb: 0.0,
                mode: "Updating...".to_string(),
            })
        }
    }
}

#[tauri::command]
async fn start_bot(state: State<'_, AppState>) -> Result<String, String> {
    let manager = state.bot_manager.clone();
    
    tauri::async_runtime::spawn_blocking(move || {
        let mut mgr = manager.lock()
            .map_err(|e| format!("Failed to acquire bot manager lock: {}", e))?;
        mgr.start()
    })
    .await
    .map_err(|e| format!("Task failed: {}", e))?
}

#[tauri::command]
async fn stop_bot(state: State<'_, AppState>) -> Result<String, String> {
    let manager = state.bot_manager.clone();
    
    tauri::async_runtime::spawn_blocking(move || {
        let mut mgr = manager.lock()
            .map_err(|e| format!("Failed to acquire bot manager lock: {}", e))?;
        mgr.stop()
    })
    .await
    .map_err(|e| format!("Task failed: {}", e))?
}

#[tauri::command]
async fn restart_bot(state: State<'_, AppState>) -> Result<String, String> {
    let manager = state.bot_manager.clone();
    
    tauri::async_runtime::spawn_blocking(move || {
        let mut mgr = manager.lock()
            .map_err(|e| format!("Failed to acquire bot manager lock: {}", e))?;
        mgr.restart()
    })
    .await
    .map_err(|e| format!("Task failed: {}", e))?
}

#[tauri::command]
async fn start_dev_bot(state: State<'_, AppState>) -> Result<String, String> {
    let manager = state.bot_manager.clone();
    
    tauri::async_runtime::spawn_blocking(move || {
        let mut mgr = manager.lock()
            .map_err(|e| format!("Failed to acquire bot manager lock: {}", e))?;
        mgr.start_dev()
    })
    .await
    .map_err(|e| format!("Task failed: {}", e))?
}

#[tauri::command]
fn get_logs(state: State<AppState>, count: usize) -> Result<Vec<String>, String> {
    let count = count.min(10_000); // Cap at 10k lines to prevent abuse
    match state.bot_manager.try_lock() {
        Ok(manager) => Ok(manager.read_logs(count)),
        Err(_) => Ok(vec!["[Dashboard] Bot manager busy — retrying...".to_string()]),
    }
}

#[tauri::command]
fn clear_logs(state: State<AppState>) -> Result<String, String> {
    let manager = lock_bot_manager!(state)?;
    manager.clear_logs()
}

#[tauri::command]
fn get_base_path(state: State<AppState>) -> Result<String, String> {
    let manager = lock_bot_manager!(state)?;
    Ok(manager.base_path().to_string_lossy().to_string())
}

#[tauri::command]
fn get_logs_path(state: State<AppState>) -> Result<String, String> {
    let manager = lock_bot_manager!(state)?;
    Ok(manager.logs_dir().to_string_lossy().to_string())
}

#[tauri::command]
fn get_data_path(state: State<AppState>) -> Result<String, String> {
    let manager = lock_bot_manager!(state)?;
    Ok(manager.data_dir().to_string_lossy().to_string())
}

#[tauri::command]
fn get_db_stats(state: State<AppState>) -> Result<DbStats, String> {
    let db = lock_db_service!(state)?;
    Ok(db.get_stats())
}

#[tauri::command]
fn get_recent_channels(state: State<AppState>, limit: i32) -> Result<Vec<ChannelInfo>, String> {
    let limit = limit.clamp(1, 100); // Cap to prevent abuse
    let db = lock_db_service!(state)?;
    Ok(db.get_recent_channels(limit))
}

#[tauri::command]
fn get_top_users(state: State<AppState>, limit: i32) -> Result<Vec<UserInfo>, String> {
    let limit = limit.clamp(1, 100); // Cap to prevent abuse
    let db = lock_db_service!(state)?;
    Ok(db.get_top_users(limit))
}

#[tauri::command]
fn clear_history(state: State<AppState>) -> Result<i32, String> {
    let db = lock_db_service!(state)?;
    db.clear_history()
}

#[tauri::command]
fn show_confirm_dialog(app: tauri::AppHandle, message: String) -> bool {
    use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
    app.dialog()
        .message(&message)
        .title("Confirm")
        .kind(MessageDialogKind::Warning)
        .buttons(MessageDialogButtons::OkCancelCustom("Yes".into(), "No".into()))
        .blocking_show()
}

#[tauri::command]
fn delete_channels_history(state: State<AppState>, channel_ids: Vec<String>) -> Result<i32, String> {
    if channel_ids.is_empty() {
        return Ok(0);
    }
    if channel_ids.len() > 100 {
        return Err("Too many channels (max 100)".to_string());
    }
    // Parse string IDs to i64 (avoids JavaScript Number precision loss for Discord Snowflake IDs)
    let parsed_ids: Vec<i64> = channel_ids
        .iter()
        .map(|id| id.parse::<i64>().map_err(|e| format!("Invalid channel ID '{}': {}", id, e)))
        .collect::<Result<Vec<_>, _>>()?;
    let db = lock_db_service!(state)?;
    db.delete_channels_history(&parsed_ids)
}

#[tauri::command]
fn open_folder(path: String, state: State<AppState>) -> Result<(), String> {
    let path_obj = std::path::Path::new(&path);
    if !path_obj.exists() {
        return Err(format!("Path does not exist: {}", path));
    }
    
    // Canonicalize to resolve symlinks and .. traversal
    let canonical = path_obj.canonicalize()
        .map_err(|e| format!("Failed to resolve path: {}", e))?;
    
    // Only allow opening directories (not arbitrary files)
    if !canonical.is_dir() {
        return Err("Path is not a directory".to_string());
    }

    // Security: restrict to known subdirectories of the bot base path
    let manager = lock_bot_manager!(state)?;
    let base_path = manager.base_path().canonicalize()
        .map_err(|e| format!("Failed to resolve base path: {}", e))?;
    if !canonical.starts_with(&base_path) {
        return Err("Access denied: path is outside the bot directory".to_string());
    }
    
    std::process::Command::new("explorer")
        .arg(canonical.as_os_str())
        .spawn()
        .map_err(|e| format!("Failed to open folder: {}", e))?;
    
    Ok(())
}

#[tauri::command]
fn log_frontend_error(state: State<AppState>, error_type: String, message: String, stack: Option<String>) -> Result<String, String> {
    use std::io::Write;
    
    // Sanitize inputs to prevent log injection (strip newlines from type, limit length)
    let error_type = error_type.replace('\n', " ").replace('\r', " ").chars().take(256).collect::<String>();
    let message = message.chars().take(4096).collect::<String>(); // Limit message size
    
    let manager = lock_bot_manager!(state)?;
    let log_dir = manager.logs_dir();
    let error_log_path = log_dir.join("dashboard_errors.log");
    
    // Ensure logs directory exists
    if !log_dir.exists() {
        let _ = std::fs::create_dir_all(&log_dir);
    }
    
    let timestamp = chrono::Local::now().format("%Y-%m-%d %H:%M:%S").to_string();
    let stack_trace = stack
        .unwrap_or_else(|| "No stack trace".to_string())
        .chars().take(16384).collect::<String>(); // Limit stack trace size
    
    let log_entry = format!(
        "\n[{}] {}\nMessage: {}\nStack: {}\n{}",
        timestamp, error_type, message, stack_trace, "=".repeat(80)
    );
    
    // Append to error log file
    let mut file = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&error_log_path)
        .map_err(|e| format!("Failed to open error log: {}", e))?;
    
    file.write_all(log_entry.as_bytes())
        .map_err(|e| format!("Failed to write error log: {}", e))?;
    
    Ok(format!("Error logged to: {}", error_log_path.display()))
}

#[tauri::command]
fn get_dashboard_errors(state: State<AppState>, count: usize) -> Result<Vec<String>, String> {
    let count = count.min(500); // Cap to prevent abuse
    let manager = lock_bot_manager!(state)?;
    let error_log_path = manager.logs_dir().join("dashboard_errors.log");
    
    if !error_log_path.exists() {
        return Ok(vec!["No errors logged yet.".to_string()]);
    }

    // Cap file read to 10 MB to prevent OOM on huge log files
    let metadata = std::fs::metadata(&error_log_path)
        .map_err(|e| format!("Failed to read error log metadata: {}", e))?;
    if metadata.len() > 10 * 1024 * 1024 {
        return Err("Error log too large (>10 MB). Please clear it first.".to_string());
    }
    
    match std::fs::read_to_string(&error_log_path) {
        Ok(content) => {
            // Split by separator and take last N entries
            let entries: Vec<&str> = content.split("=".repeat(80).as_str()).collect();
            Ok(entries.iter()
                .rev()
                .filter(|s| !s.trim().is_empty())
                .take(count)
                .map(|s| s.trim().to_string())
                .collect())
        }
        Err(_) => Ok(vec!["Failed to read error log.".to_string()])
    }
}

#[tauri::command]
fn clear_dashboard_errors(state: State<AppState>) -> Result<String, String> {
    let manager = lock_bot_manager!(state)?;
    let error_log_path = manager.logs_dir().join("dashboard_errors.log");
    
    if error_log_path.exists() {
        std::fs::write(&error_log_path, "")
            .map_err(|e| format!("Failed to clear error log: {}", e))?;
    }
    
    Ok("Dashboard errors cleared".to_string())
}

#[tauri::command]
fn get_ws_token(state: State<AppState>) -> Result<String, String> {
    let manager = lock_bot_manager!(state)?;
    let env_path = manager.base_path().join(".env");
    if !env_path.exists() {
        return Ok(String::new());
    }
    let content = std::fs::read_to_string(&env_path)
        .map_err(|e| format!("Failed to read .env: {}", e))?;
    for line in content.lines() {
        let line = line.trim();
        if let Some(val) = line.strip_prefix("DASHBOARD_WS_TOKEN=") {
            // Strip surrounding quotes (dotenv convention) and whitespace
            let val = val.trim().trim_matches('"').trim_matches('\'');
            if !val.is_empty() {
                return Ok(val.to_string());
            }
        }
    }
    Ok(String::new())
}

fn main() {
    // Base path for the bot files - use BOT_BASE_PATH env var or default
    let base_path = std::env::var("BOT_BASE_PATH")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|_| {
            // Check if we're in dev mode (executable is in target/debug or target/release)
            let exe_path = std::env::current_exe().ok();
            let is_dev = exe_path.as_ref()
                .and_then(|p| p.to_str())
                .map(|s| s.contains("target\\debug") || s.contains("target\\release") || s.contains("target/debug") || s.contains("target/release"))
                .unwrap_or(false);
            
            if is_dev {
                // Dev mode: go up from native_dashboard/target/debug to BOT folder
                exe_path
                    .and_then(|p| p.parent().map(|p| p.to_path_buf())) // debug/
                    .and_then(|p| p.parent().map(|p| p.to_path_buf())) // target/
                    .and_then(|p| p.parent().map(|p| p.to_path_buf())) // native_dashboard/
                    .and_then(|p| p.parent().map(|p| p.to_path_buf())) // BOT/
                    .unwrap_or_else(|| {
                        eprintln!("WARNING: Could not determine bot base path, using current directory");
                        std::env::current_dir().unwrap_or_else(|_| std::path::PathBuf::from("."))
                    })
            } else {
                // Production: executable is in BOT folder
                exe_path
                    .and_then(|p| p.parent().map(|p| p.to_path_buf()))
                    .unwrap_or_else(|| {
                        eprintln!("WARNING: Could not determine bot base path, using current directory");
                        std::env::current_dir().unwrap_or_else(|_| std::path::PathBuf::from("."))
                    })
            }
        });

    let bot_manager = BotManager::new(base_path.clone());
    let db_service = DatabaseService::new(base_path.join("data").join("bot_database.db"));

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(AppState {
            bot_manager: Arc::new(Mutex::new(bot_manager)),
            db_service: Mutex::new(db_service),
        })
        .setup(|app| {
            // Create tray menu
            let show_item = MenuItem::with_id(app, "show", "แสดง Dashboard", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "ปิดโปรแกรม", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show_item, &quit_item])?;

            // Build tray icon
            // WARNING: DO NOT MODIFY THE TOOLTIP TEXT BELOW!
            // The Korean text "디스코드 봇 대시보드" is INTENTIONAL.
            // This is a design choice by the owner - DO NOT CHANGE IT!
            // ห้ามแก้ไข tooltip นี้เด็ดขาด! ตั้งใจให้เป็นภาษาเกาหลี
            let _tray = TrayIconBuilder::new()
                .icon(app.default_window_icon()
                    .ok_or("Default window icon not configured in tauri.conf.json")?
                    .clone())
                .menu(&menu)
                .show_menu_on_left_click(false)
                .tooltip("디스코드 봇 대시보드")
                .on_menu_event(|app, event| {
                    match event.id.as_ref() {
                        "show" => {
                            if let Some(window) = app.get_webview_window("main") {
                                let _ = window.show();
                                let _ = window.set_focus();
                            }
                        }
                        "quit" => {
                            app.exit(0);
                        }
                        _ => {}
                    }
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                })
                .build(app)?;

            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                // Prevent default close
                api.prevent_close();
                
                let window_clone = window.clone();
                let app_handle = window.app_handle().clone();
                
                // Use non-blocking callback-based dialog to avoid starving the async runtime
                use tauri_plugin_dialog::{DialogExt, MessageDialogKind, MessageDialogButtons};
                
                app_handle
                    .dialog()
                    .message("กด Yes เพื่อปิดโปรแกรม หรือ No เพื่อซ่อนไปที่ System Tray")
                    .title("ปิดโปรแกรม")
                    .kind(MessageDialogKind::Info)
                    .buttons(MessageDialogButtons::YesNo)
                    .show(move |confirmed| {
                        if confirmed {
                            // User clicked Yes - quit the app
                            app_handle.exit(0);
                        } else {
                            // User clicked No - hide to tray
                            let _ = window_clone.hide();
                        }
                    });
            }
        })
        .invoke_handler(tauri::generate_handler![
            get_status,
            start_bot,
            start_dev_bot,
            stop_bot,
            restart_bot,
            get_logs,
            clear_logs,
            get_base_path,
            get_logs_path,
            get_data_path,
            get_db_stats,
            get_recent_channels,
            get_top_users,
            clear_history,
            show_confirm_dialog,
            delete_channels_history,
            open_folder,
            log_frontend_error,
            get_dashboard_errors,
            clear_dashboard_errors,
            get_ws_token
        ])
        .run(tauri::generate_context!())
        .unwrap_or_else(|e| {
            eprintln!("Error while running tauri application: {}", e);
            std::process::exit(1);
        });
}
