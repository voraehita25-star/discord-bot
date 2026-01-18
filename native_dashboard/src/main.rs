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

#[tauri::command]
fn get_status(state: State<AppState>) -> BotStatus {
    let manager = state.bot_manager.lock().unwrap();
    manager.get_status()
}

#[tauri::command]
fn start_bot(state: State<AppState>) -> Result<String, String> {
    let manager = state.bot_manager.lock().unwrap();
    manager.start()
}

#[tauri::command]
fn stop_bot(state: State<AppState>) -> Result<String, String> {
    let manager = state.bot_manager.lock().unwrap();
    manager.stop()
}

#[tauri::command]
fn restart_bot(state: State<AppState>) -> Result<String, String> {
    let manager = state.bot_manager.lock().unwrap();
    manager.restart()
}

#[tauri::command]
fn start_dev_bot(state: State<AppState>) -> Result<String, String> {
    let manager = state.bot_manager.lock().unwrap();
    manager.start_dev()
}

#[tauri::command]
fn get_logs(count: usize) -> Vec<String> {
    bot_manager::read_recent_logs(count)
}

#[tauri::command]
fn get_db_stats(state: State<AppState>) -> DbStats {
    let db = state.db_service.lock().unwrap();
    db.get_stats()
}

#[tauri::command]
fn get_recent_channels(state: State<AppState>, limit: i32) -> Vec<ChannelInfo> {
    let db = state.db_service.lock().unwrap();
    db.get_recent_channels(limit)
}

#[tauri::command]
fn get_top_users(state: State<AppState>, limit: i32) -> Vec<UserInfo> {
    let db = state.db_service.lock().unwrap();
    db.get_top_users(limit)
}

#[tauri::command]
fn clear_history(state: State<AppState>) -> Result<i32, String> {
    let db = state.db_service.lock().unwrap();
    db.clear_history()
}

#[tauri::command]
fn open_folder(path: String) {
    let _ = std::process::Command::new("explorer")
        .arg(&path)
        .spawn();
}

fn main() {
    // Base path for the bot files
    let base_path = std::path::PathBuf::from(r"C:\Users\ME\BOT");

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
                .tooltip("Discord Bot Dashboard")
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
                
                // Use confirm dialog with callback
                tauri_plugin_dialog::DialogExt::dialog(&app_handle)
                    .message("กด OK เพื่อปิดโปรแกรม หรือ Cancel เพื่อซ่อนไปที่ System Tray")
                    .title("ปิดโปรแกรม")
                    .blocking_show();
                
                // For simplicity: always hide on close, user can quit from tray menu
                let _ = window_clone.hide();
            }
        })
        .invoke_handler(tauri::generate_handler![
            get_status,
            start_bot,
            start_dev_bot,
            stop_bot,
            restart_bot,
            get_logs,
            get_db_stats,
            get_recent_channels,
            get_top_users,
            clear_history,
            open_folder
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
