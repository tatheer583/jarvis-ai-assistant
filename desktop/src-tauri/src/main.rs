#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
use serde_json::{json, Value};
use std::{collections::HashMap, io::{BufRead, BufReader, Write}, path::PathBuf,
    process::{Child, ChildStdin, Command, Stdio}, sync::{Arc, Mutex, atomic::{AtomicBool, AtomicU64, Ordering}}, time::Duration};
use tauri::{Emitter, Manager, State, WebviewUrl, WebviewWindowBuilder, PhysicalPosition, PhysicalSize};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};
use tokio::sync::oneshot;

#[derive(Default)]
struct EngineInner {
    input: Mutex<Option<ChildStdin>>,
    child: Mutex<Option<Child>>,
    pending: Mutex<HashMap<u64, oneshot::Sender<Value>>>,
    sequence: AtomicU64,
    generation: AtomicU64,
    close_to_tray: AtomicBool,
}
#[derive(Clone, Default)]
struct Engine(Arc<EngineInner>);
impl Engine {
    fn send(&self, request: &Value) -> Result<(), String> {
        let mut input = self.0.input.lock().map_err(|_| "Engine is busy")?;
        let pipe = input.as_mut().ok_or("The local engine is not running. Use Reconnect.")?;
        writeln!(pipe, "{}", request).and_then(|_| pipe.flush()).map_err(|e| format!("Local engine disconnected: {e}"))
    }
    fn stop(&self) {
        let _ = self.send(&json!({"op":"quit"}));
        self.0.input.lock().unwrap().take();
        if let Some(mut child) = self.0.child.lock().unwrap().take() {
            std::thread::sleep(Duration::from_millis(250));
            if child.try_wait().ok().flatten().is_none() { let _ = child.kill(); }
            let _ = child.wait();
        }
        self.0.pending.lock().unwrap().clear();
    }
}

fn show_main(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show(); let _ = window.unminimize(); let _ = window.set_focus();
    }
}
fn handle_result(app: &tauri::AppHandle, data: &Value) {
    if let Some(grid) = data.get("data").and_then(|d| d.get("grid")) {
        if grid.is_null() {
            if let Some(window) = app.get_webview_window("grid") { let _ = window.hide(); }
        } else if let Some(bounds) = grid.get("bounds").and_then(|v| v.as_array()) {
            if bounds.len() == 4 {
                let left = bounds[0].as_i64().unwrap_or(0) as i32;
                let top = bounds[1].as_i64().unwrap_or(0) as i32;
                let width = (bounds[2].as_i64().unwrap_or(1) as i32 - left).max(1) as u32;
                let height = (bounds[3].as_i64().unwrap_or(1) as i32 - top).max(1) as u32;
                let window = app.get_webview_window("grid").or_else(|| {
                    WebviewWindowBuilder::new(app, "grid", WebviewUrl::App("index.html?overlay=grid".into()))
                        .title("Jarvis mouse grid").decorations(false).transparent(true).always_on_top(true)
                        .skip_taskbar(true).focused(false).visible(false).build().ok()
                });
                if let Some(window) = window {
                    let _ = window.set_ignore_cursor_events(true);
                    let _ = window.set_position(PhysicalPosition::new(left, top));
                    let _ = window.set_size(PhysicalSize::new(width, height));
                    if let Some(main) = app.get_webview_window("main") { let _ = main.hide(); }
                    let _ = window.show();
                }
            }
        }
    }
    if let Some(action) = data.get("data").and_then(|d| d.get("interface")).and_then(Value::as_str) {
        if action == "show" { show_main(app); }
        else if let Some(window) = app.get_webview_window("main") { let _ = window.hide(); }
    }
}
fn engine_command(app: &tauri::AppHandle) -> Result<Command, String> {
    let resource_candidate = app.path().resource_dir().ok().map(|p| p.join("engine/jarvis-engine.exe"));
    let exe_candidate = std::env::current_exe().ok().and_then(|p| p.parent().map(|d| d.join("engine/jarvis-engine.exe")));
    let bundled = resource_candidate.into_iter().chain(exe_candidate).find(|p| p.is_file());
    let mut command;
    if let Some(bundled) = bundled {
        command = Command::new(bundled);
    } else if cfg!(debug_assertions) {
        let root = std::env::var_os("JARVIS_PROJECT_DIR").map(PathBuf::from).unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().parent().unwrap().to_path_buf());
        let python = std::env::var_os("JARVIS_PYTHON").map(PathBuf::from).unwrap_or_else(||
            PathBuf::from(std::env::var_os("LOCALAPPDATA").unwrap_or_default()).join("Jarvis/runtime/Scripts/python.exe"));
        if !python.is_file() { return Err("The Python engine is missing. Run scripts/setup_local.ps1.".into()); }
        command = Command::new(python);
        command.arg("-u").arg(root.join("Main.py"));
        command.current_dir(root);
    } else {
        return Err("The bundled engine is missing. Reinstall Jarvis with its engine folder.".into());
    }
    command.arg("--engine").env("PYTHONUTF8", "1").env("HF_HUB_OFFLINE", "1")
        .stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped());
    #[cfg(windows)] {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    Ok(command)
}
fn start_engine(app: &tauri::AppHandle, engine: &Engine) -> Result<(), String> {
    let generation = engine.0.generation.fetch_add(1, Ordering::SeqCst) + 1;
    let mut child = engine_command(app)?.spawn().map_err(|e| format!("Could not start local engine: {e}"))?;
    let output = child.stdout.take().ok_or("Missing engine output")?;
    let errors = child.stderr.take().ok_or("Missing engine error stream")?;
    *engine.0.input.lock().unwrap() = child.stdin.take();
    *engine.0.child.lock().unwrap() = Some(child);
    let copy = engine.clone();
    let handle = app.clone();
    std::thread::spawn(move || {
        for line in BufReader::new(output).lines().map_while(Result::ok) {
            if copy.0.generation.load(Ordering::SeqCst) != generation { break; }
            if let Ok(event) = serde_json::from_str::<Value>(&line) {
                let kind = event.get("event").and_then(Value::as_str).unwrap_or("");
                let data = &event["data"];
                if kind == "response" {
                    if let Some(id) = data["id"].as_u64() {
                        if let Some(sender) = copy.0.pending.lock().unwrap().remove(&id) { let _ = sender.send(data.clone()); }
                    }
                } else {
                    if kind == "result" { handle_result(&handle, data); }
                    if kind == "quit" { handle.exit(0); }
                    let _ = handle.emit("engine-event", &event);
                }
            }
        }
        if copy.0.generation.load(Ordering::SeqCst) == generation {
            copy.0.input.lock().unwrap().take();
            copy.0.pending.lock().unwrap().clear();
            let _ = handle.emit("engine-event", json!({"event":"disconnected","data":"The local engine stopped. Use Reconnect to restart it."}));
        }
    });
    let log_dir = std::env::var_os("JARVIS_DATA_DIR").map(PathBuf::from).unwrap_or_else(||
        PathBuf::from(std::env::var_os("LOCALAPPDATA").unwrap_or_default()).join("Jarvis"));
    std::thread::spawn(move || {
        let _ = std::fs::create_dir_all(&log_dir);
        if let Ok(mut file) = std::fs::OpenOptions::new().create(true).append(true).open(log_dir.join("desktop-engine.log")) {
            for line in BufReader::new(errors).lines().map_while(Result::ok) { let _ = writeln!(file, "{line}"); }
        }
    });
    Ok(())
}

#[tauri::command]
async fn engine_request(state: State<'_, Engine>, request: Value) -> Result<Value, String> {
    request_engine(&state, request).await
}
async fn request_engine(state: &Engine, mut request: Value) -> Result<Value, String> {
    let id = state.0.sequence.fetch_add(1, Ordering::SeqCst) + 1;
    let object = request.as_object_mut().ok_or("Request must be an object")?;
    object.insert("id".into(), json!(id));
    if object.get("op").and_then(Value::as_str) == Some("connect") {
        object.insert("shell_pid".into(), json!(std::process::id()));
        if std::env::args().any(|s| s == "--no-listen") { object.insert("no_listen".into(), json!(true)); }
    }
    let (sender, receiver) = oneshot::channel();
    state.0.pending.lock().unwrap().insert(id, sender);
    if let Err(error) = state.send(&request) {
        state.0.pending.lock().unwrap().remove(&id);
        return Err(error);
    }
    let response = tokio::time::timeout(Duration::from_secs(30), receiver).await;
    state.0.pending.lock().unwrap().remove(&id);
    let value = response.map_err(|_| "The local engine took too long. Try again.".to_string())?
        .map_err(|_| "The local engine disconnected.".to_string())?;
    if let Some(error) = value.get("error").and_then(Value::as_str) { return Err(error.into()); }
    let result = value["value"].clone();
    if let Some(flag) = result.get("settings").and_then(|s| s.get("close_to_tray")).or_else(|| result.get("close_to_tray")).and_then(Value::as_bool) {
        state.0.close_to_tray.store(flag, Ordering::SeqCst);
    }
    Ok(result)
}
#[tauri::command]
fn restart_engine(app: tauri::AppHandle, state: State<'_, Engine>) -> Result<(), String> {
    state.0.generation.fetch_add(1, Ordering::SeqCst);
    state.stop();
    start_engine(&app, &state)
}
#[tauri::command]
fn quit_app(app: tauri::AppHandle) { app.exit(0); }
#[tauri::command]
async fn set_autostart(app: tauri::AppHandle, enabled: bool) -> Result<(), String> {
    let state = app.state::<Engine>();
    let approval = request_engine(&state, json!({"op":"autostart_authorize","enabled":enabled})).await?;
    let ticket = approval["ticket"].as_str().ok_or("Native action was not authorized")?;
    let result = apply_autostart(enabled);
    let audit = request_engine(&state, json!({"op":"autostart_result","ticket":ticket,"success":result.is_ok()})).await;
    result?;
    audit.map_err(|_| "Windows startup was changed but its audit result could not be saved. Check Settings before retrying.".to_string())?;
    Ok(())
}
fn apply_autostart(enabled: bool) -> Result<(), String> {
    #[cfg(windows)] {
        use winreg::{RegKey, enums::HKEY_CURRENT_USER};
        let (key, _) = RegKey::predef(HKEY_CURRENT_USER).create_subkey("Software\\Microsoft\\Windows\\CurrentVersion\\Run").map_err(|e| e.to_string())?;
        if enabled {
            let path = std::env::current_exe().map_err(|e| e.to_string())?;
            key.set_value("JarvisDesktop", &format!("\"{}\" --minimized", path.display())).map_err(|e| e.to_string())?;
        } else if let Err(error) = key.delete_value("JarvisDesktop") {
            if error.kind() != std::io::ErrorKind::NotFound { return Err(error.to_string()); }
        }
    }
    Ok(())
}
fn main() {
    let engine = Engine::default();
    engine.0.close_to_tray.store(true, Ordering::SeqCst);
    let shutdown = engine.clone();
    let app = tauri::Builder::default()
        .manage(engine)
        .plugin(tauri_plugin_single_instance::init(|app, _, _| show_main(app)))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().with_handler(|app, shortcut, event| {
            if event.state() != ShortcutState::Pressed { return; }
            let request = if shortcut.key == Code::Escape { json!({"op":"emergency"}) }
                else { json!({"op":"listen","enabled":true,"once":true}) };
            let _ = app.state::<Engine>().send(&request);
        }).build())
        .invoke_handler(tauri::generate_handler![engine_request, restart_engine, quit_app, set_autostart])
        .setup(|app| {
            use tauri::{menu::{Menu, MenuItem}, tray::{TrayIconBuilder, TrayIconEvent}};
            let show = MenuItem::with_id(app, "show", "Open Jarvis", true, None::<&str>)?;
            let listen = MenuItem::with_id(app, "listen", "Activate voice", true, None::<&str>)?;
            let pause = MenuItem::with_id(app, "pause", "Pause microphone", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit Jarvis", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &listen, &pause, &quit])?;
            TrayIconBuilder::new().icon(app.default_window_icon().unwrap().clone())
                .tooltip("Jarvis · Local desktop assistant").menu(&menu).show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => show_main(app),
                    "listen" => { let _ = app.state::<Engine>().send(&json!({"op":"listen","enabled":true})); },
                    "pause" => { let _ = app.state::<Engine>().send(&json!({"op":"emergency"})); },
                    "quit" => app.exit(0), _ => ()
                })
                .on_tray_icon_event(|tray, event| { if matches!(event, TrayIconEvent::DoubleClick { .. }) { show_main(tray.app_handle()); } })
                .build(app)?;
            for key in [Code::KeyJ, Code::Escape] {
                let shortcut = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), key);
                if let Err(error) = app.global_shortcut().register(shortcut) { eprintln!("Shortcut unavailable: {error}"); }
            }
            let state = app.state::<Engine>();
            if let Err(error) = start_engine(app.handle(), &state) {
                eprintln!("{error}");
            }
            if std::env::args().any(|s| s == "--minimized") {
                if let Some(window) = app.get_webview_window("main") { let _ = window.hide(); }
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if window.label() == "main" {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    if window.state::<Engine>().0.close_to_tray.load(Ordering::SeqCst) { let _ = window.hide(); }
                    else { window.app_handle().exit(0); }
                }
            }
        })
        .build(tauri::generate_context!()).expect("Could not create the Jarvis desktop window");
    app.run(move |_, event| { if matches!(event, tauri::RunEvent::Exit) { shutdown.stop(); } });
}
