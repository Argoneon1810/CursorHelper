import sys
import multiprocessing
import threading
import time
import ctypes
import traceback

import backend, logic, gui, tray
from dispatcher import MainThreadDispatcher

# =============================================================================
# [Global Config]
# =============================================================================
DEBUG_MODE = False
GUI_PROCESS = None
TRAY_EXIT_STRATEGY = "FORCE_CLOSE"
POLLING_RATE = 60  # Hz

_IPC_QUEUE = multiprocessing.Queue()

def log(msg):
    MainThreadDispatcher.instance().enqueue(backend.LogTask("Main", msg))

def show_native_alert(title, message):
    try:
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x30 | 0x0)
    except Exception as e:
        log(f"!! [Error] Failed to show native alert: {e}")

# =============================================================================
# [Process Management]
# =============================================================================

def handle_ui_request(request_type):
    global GUI_PROCESS, _IPC_QUEUE, DEBUG_MODE

    if GUI_PROCESS and GUI_PROCESS.is_alive():
        pid = GUI_PROCESS.pid
        log(f"!! [Reject] UI Process already running (PID: {pid}). Request '{request_type}' ignored.")

        show_native_alert("실행 오류", "이미 설정 창이 실행 중입니다.\n창을 확인하거나 종료 후 다시 시도하세요.")
        return

    target_func = None
    args = ()

    if request_type == "create":
        target_func = gui.run_editor_process
        args = ("create", None, _IPC_QUEUE, DEBUG_MODE)
    elif request_type == "export":
        target_func = gui.run_editor_process
        args = ("export", None, _IPC_QUEUE, DEBUG_MODE)
    elif request_type == "import_zip":
        target_func = gui.run_zip_import_process
        args = (_IPC_QUEUE, DEBUG_MODE)
    elif request_type == "license":
        target_func = gui.run_license_process
        args = (_IPC_QUEUE, DEBUG_MODE)
    else:
        log(f"!! [Error] Unknown UI request type: {request_type}")
        return

    log(f">> [Main] Spawning UI Process. Target: {target_func.__name__}")
    p = multiprocessing.Process(target=target_func, args=args)
    p.start()
    GUI_PROCESS = p
    log(f"   [Main] Process spawned successfully with PID: {p.pid}")

def on_exit_request(icon):
    global GUI_PROCESS
    log(">> [Main] Exit requested via Tray.")

    if GUI_PROCESS and GUI_PROCESS.is_alive():
        log(f"   [Check] GUI process {GUI_PROCESS.pid} is ALIVE.")

        if TRAY_EXIT_STRATEGY == "BLOCK":
            log("   [Strategy] BLOCK active. Denying exit.")
            icon.notify("GUI 창을 먼저 닫아주세요.", "종료 불가")
            return

        elif TRAY_EXIT_STRATEGY == "FORCE_CLOSE":
            log("   [Strategy] FORCE_CLOSE executing. Terminating child process...")
            GUI_PROCESS.terminate()
            GUI_PROCESS.join(timeout=2)
            log("   [Strategy] Child process terminated.")

    log(">> [Main] Stopping tray icon...")
    icon.stop()

# =============================================================================
# [Main Entry]
# =============================================================================

def main(debug=False):
    global DEBUG_MODE
    DEBUG_MODE = debug
    backend.set_debug(debug)
    logic.set_debug(debug)

    multiprocessing.freeze_support()

    dispatcher = MainThreadDispatcher.instance()
    dispatcher.start_ipc_bridge(_IPC_QUEUE)

    logic.register_log_callback(lambda msg: dispatcher.enqueue(backend.LogTask("Logic", msg)))

    log(f"== CursorHelper Started. Debug={DEBUG_MODE} ==")
    logic.load_custom_aliases()

    tray_manager = tray.TrayIconManager(
        exit_callback=on_exit_request,
        ui_launcher_callback=handle_ui_request,
        ipc_queue=_IPC_QUEUE,
        debug_mode=DEBUG_MODE
    )

    tray_thread = threading.Thread(target=tray_manager.run, name="TrayThread")
    tray_thread.start()
    log(">> [Main] Tray thread launched.")

    log(">> [Main] Entering Event Loop...")
    try:
        refresh_delay = 1.0 / POLLING_RATE
        while tray_thread.is_alive():
            dispatcher.process_pending_tasks()
            time.sleep(refresh_delay)

    except KeyboardInterrupt:
        log(">> [Main] KeyboardInterrupt received.")
    except Exception as e:
        log(f"!! [Critical] Main Loop Crash: {e}")
        traceback.print_exc()
    finally:
        log(">> [Main] Shutting down...")
        tray_manager.stop()
        tray_thread.join(timeout=3)
        sys.exit(0)

if __name__ == "__main__":
    main(debug=True)
