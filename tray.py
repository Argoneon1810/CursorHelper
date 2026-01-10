import subprocess
import types
import traceback
from PIL import Image, ImageDraw
import pystray

import backend
from dispatcher import MainThreadDispatcher

# =============================================================================
# [Tray Logic]
# =============================================================================

class TrayIconManager:
    def __init__(self, exit_callback, ui_launcher_callback, ipc_queue, debug_mode):
        self.exit_callback = exit_callback
        self.ui_launcher_callback = ui_launcher_callback
        self.ipc_queue = ipc_queue
        self.debug_mode = debug_mode
        self.icon = None

    def log(self, msg):
        task = backend.LogTask("Tray", msg)
        MainThreadDispatcher.instance().enqueue(task)

    def create_image(self):
        image = Image.new('RGB', (64, 64), (30, 30, 30))
        dc = ImageDraw.Draw(image)
        dc.polygon([(16, 16), (48, 32), (32, 32), (32, 48), (24, 48), (24, 32)], fill=(200, 200, 255))
        return image

    def on_click_scheme(self, name, data):
        def _handler(icon, item):
            self.log(f">> [Menu] User selected scheme: '{name}'")
            backend.apply_scheme_by_data(name, data)
        return _handler

    def build_menu(self):
        items = []
        try:
            mtd = MainThreadDispatcher.instance()
            schemes = backend.get_all_schemes()

            # self.log(f"      [MenuBuild] Found {len(schemes)} schemes.")

            if schemes:
                for name in sorted(schemes.keys()):
                    items.append(pystray.MenuItem(name, self.on_click_scheme(name, schemes[name])))
            else:
                items.append(pystray.MenuItem("저장된 구성표 없음", lambda i, t: None, enabled=False))
            items.append(pystray.Menu.SEPARATOR)
            items.append(pystray.MenuItem("목록 새로고침", lambda icon, item: icon.update_menu()))
            items.append(pystray.MenuItem(
                "커서 등록 (GUI)...",
                lambda i, t: mtd.enqueue(
                    lambda: self.ui_launcher_callback("create")
                )
            ))
            backup_sub_items = [
                pystray.MenuItem(
                    "ZIP 가져오기...",
                    lambda i, t: mtd.enqueue(
                        lambda: self.ui_launcher_callback("import_zip")
                    )
                ),
                pystray.MenuItem(
                    "ZIP 내보내기...",
                    lambda i, t: mtd.enqueue(
                        lambda: self.ui_launcher_callback("export")
                    )
                )
            ]
            items.append(pystray.MenuItem("백업 및 복원", pystray.Menu(*backup_sub_items)))
            items.append(pystray.Menu.SEPARATOR)
            items.append(
                pystray.MenuItem(
                    "Windows 마우스 설정...",
                    lambda i, t: subprocess.Popen("control main.cpl")
                )
            )

        except Exception as e:
            self.log(f"!! [MenuBuild] Error: {e}")
            traceback.print_exc()
            items.append(pystray.Menu.SEPARATOR)
            items.append(pystray.MenuItem("Menu Error", lambda i, t: None))

        finally:
            items.append(pystray.Menu.SEPARATOR)
            items.append(
                pystray.MenuItem(
                    "오픈소스 라이선스...",
                    lambda i, t: MainThreadDispatcher.instance().enqueue(
                        lambda: self.ui_launcher_callback("license")
                    )
                )
            )
            items.append(pystray.MenuItem("종료 (Exit)", lambda i, t: self.exit_callback(i)))
            return items

    def run(self):
        self.log(">> [Tray] Initializing Tray Icon...")

        class LazyMenu(pystray.Menu):
            def __init__(self, builder_func):
                self._builder = builder_func
                super().__init__()

            def __iter__(self):
                return iter(self._builder())

            def __bool__(self):
                return True

        self.icon = pystray.Icon(
            "CursorHelper",
            self.create_image(),
            "마우스 관리자",
            menu=LazyMenu(self.build_menu)
        )

        self.icon.update_menu_old = self.icon.update_menu
        def update_menu_with_log(icon_self):
            icon_self.update_menu_old()
            self.log("   [Tray] Menu structure refreshed.")
        self.icon.update_menu = types.MethodType(update_menu_with_log, self.icon)

        backend.register_refresh_callback(
            lambda: MainThreadDispatcher.instance().enqueue(self.icon.update_menu)
        )

        self.log(">> [Tray] Starting pystray loop...")
        try:
            self.icon.run()
        except Exception as e:
            self.log(f"!! [Tray] Run Failed: {e}")
            traceback.print_exc()

    def stop(self):
        if self.icon:
            self.log(">> [Tray] Stop requested.")
            self.icon.stop()