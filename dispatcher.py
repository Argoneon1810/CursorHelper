import queue
import threading
import traceback
from abc import ABC, abstractmethod

# =============================================================================
# [Interface Definition]
# =============================================================================

class Runnable(ABC):
    @abstractmethod
    def __call__(self):
        pass

# =============================================================================
# [Dispatcher Logic]
# =============================================================================

class MainThreadDispatcher:
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        if MainThreadDispatcher._instance is not None:
            raise RuntimeError("Use MainThreadDispatcher.instance()")
        self._action_queue = queue.Queue()

    @classmethod
    def instance(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def enqueue(self, task: Runnable):
        if not isinstance(task, Runnable) and not callable(task):
            print(f"!! [Dispatcher] Warning: Task object {task} is not a valid Runnable or callable.")
        self._action_queue.put(task)

    def start_ipc_bridge(self, ipc_queue):
        def _bridge_worker():
            print(">> [Dispatcher] Starting IPC Bridge Thread...")
            while True:
                try:
                    task = ipc_queue.get()
                    if task is None:
                        print("   [Dispatcher] IPC Bridge received stop signal.")
                        break
                    self.enqueue(task)
                except Exception as e:
                    print(f"!! [Dispatcher] IPC Bridge Error: {e}")
                    traceback.print_exc()
                    break

        t = threading.Thread(target=_bridge_worker, daemon=True, name="IPC_Bridge_Thread")
        t.start()

    def process_pending_tasks(self):
        while not self._action_queue.empty():
            try:
                task = self._action_queue.get_nowait()
                task()
            except queue.Empty:
                break
            except Exception as e:
                print(f"!! [Dispatcher] Action Execution Failed: {e}")
                traceback.print_exc()