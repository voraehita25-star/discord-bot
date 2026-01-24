#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod bot_manager;
mod database;

use bot_manager::{BotManager, BotStatus};
use database::{DatabaseService, DbStats, ChannelInfo, UserInfo};
use std::sync::Mutex;
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, State, WindowEvent,
};

struct AppState {
    bot_manager: Mutex<BotManager>,
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
    let manager = lock_bot_manager!(state)?;
    Ok(manager.get_status())
}

#[tauri::command]
fn start_bot(state: State<AppState>) -> Result<String, String> {
    let manager = lock_bot_manager!(state)?;
    manager.start()
}

#[tauri::command]
fn stop_bot(state: State<AppState>) -> Result<String, String> {
    let manager = lock_bot_manager!(state)?;
    manager.stop()
}

#[tauri::command]
fn restart_bot(state: State<AppState>) -> Result<String, String> {
    let manager = lock_bot_manager!(state)?;
    manager.restart()
}

#[tauri::command]
fn start_dev_bot(state: State<AppState>) -> Result<String, String> {
    let manager = lock_bot_manager!(state)?;
    manager.start_dev()
}

#[tauri::command]
fn get_logs(state: State<AppState>, count: usize) -> Result<Vec<String>, String> {
    let manager = lock_bot_manager!(state)?;
    Ok(manager.read_logs(count))
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
    let db = lock_db_service!(state)?;
    Ok(db.get_recent_channels(limit))
}

#[tauri::command]
fn get_top_users(state: State<AppState>, limit: i32) -> Result<Vec<UserInfo>, String> {
    let db = lock_db_service!(state)?;
    Ok(db.get_top_users(limit))
}

#[tauri::command]
fn clear_history(state: State<AppState>) -> Result<i32, String> {
    let db = lock_db_service!(state)?;
    db.clear_history()
}

#[tauri::command]
fn open_folder(path: String) {
    let _ = std::process::Command::new("explorer")
        .arg(&path)
        .spawn();
}

#[tauri::command]
fn log_frontend_error(state: State<AppState>, error_type: String, message: String, stack: Option<String>) -> Result<String, String> {
    use std::io::Write;
    
    let manager = lock_bot_manager!(state)?;
    let log_dir = manager.logs_dir();
    let error_log_path = log_dir.join("dashboard_errors.log");
    
    // Ensure logs directory exists
    if !log_dir.exists() {
        let _ = std::fs::create_dir_all(&log_dir);
    }
    
    let timestamp = chrono::Local::now().format("%Y-%m-%d %H:%M:%S").to_string();
    let stack_trace = stack.unwrap_or_else(|| "No stack trace".to_string());
    
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
    let manager = lock_bot_manager!(state)?;
    let error_log_path = manager.logs_dir().join("dashboard_errors.log");
    
    if !error_log_path.exists() {
        return Ok(vec!["No errors logged yet.".to_string()]);
    }
    
    match std::fs::read_to_string(&error_log_path) {
        Ok(content) => {
            // Split by separator and take last N entries
            let entries: Vec<&str> = content.split("=".repeat(80).as_str()).collect();
            Ok(entries.iter()
                .rev()
                .take(count)
                .filter(|s| !s.trim().is_empty())
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
                    .unwrap_or_else(|| std::path::PathBuf::from(r"C:\Users\ME\BOT"))
            } else {
                // Production: executable is in BOT folder
                exe_path
                    .and_then(|p| p.parent().map(|p| p.to_path_buf()))
                    .unwrap_or_else(|| std::path::PathBuf::from(r"C:\Users\ME\BOT"))
            }
        });

    let bot_manager = BotManager::new(base_path.clone());
    let db_service = DatabaseService::new(base_path.join("data").join("bot_database.db"));

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(AppState {
            bot_manager: Mutex::new(bot_manager),
            db_service: Mutex::new(db_service),
        })
        .setup(|app| {
            // Create tray menu
            let show_item = MenuItem::with_id(app, "show", "แสดง Dashboard", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "ปิดโปรแกรม", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show_item, &quit_item])?;

            // Build tray icon
            let _tray = TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
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
                
                // Use confirm dialog - OK = quit, Cancel = hide to tray  
                tauri::async_runtime::spawn(async move {
                    use tauri_plugin_dialog::{DialogExt, MessageDialogKind, MessageDialogButtons};
                    
                    let confirmed = app_handle
                        .dialog()
                        .message("กด Yes เพื่อปิดโปรแกรม หรือ No เพื่อซ่อนไปที่ System Tray")
                        .title("ปิดโปรแกรม")
                        .kind(MessageDialogKind::Info)
                        .buttons(MessageDialogButtons::YesNo)
                        .blocking_show();
                    
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
            open_folder,
            log_frontend_error,
            get_dashboard_errors,
            clear_dashboard_errors
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
