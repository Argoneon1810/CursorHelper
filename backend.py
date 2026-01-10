import os
import ctypes
import winreg
import locale
import traceback

from dispatcher import Runnable

# =============================================================================
# [Command Pattern Tasks] Callable Objects for Queue
# =============================================================================

_CALLBACK_REFRESH_MENU = None

def register_refresh_callback(func):
    global _CALLBACK_REFRESH_MENU
    _CALLBACK_REFRESH_MENU = func

class LogTask(Runnable):
    def __init__(self, source, msg):
        self.source = source
        self.msg = msg

    def __call__(self):
        print(f"[{self.source}] {self.msg}")

class RefreshMenuTask(Runnable):
    def __call__(self):
        if _CALLBACK_REFRESH_MENU:
            print(">> [Backend] Executing RefreshMenuTask...")
            _CALLBACK_REFRESH_MENU()
        else:
            print("!! [Backend] RefreshMenuTask requested but no callback registered.")

# =============================================================================
# [Constants & Globals]
# =============================================================================

DEBUG_MODE = False

def set_debug(mode: bool):
    global DEBUG_MODE
    DEBUG_MODE = mode

def log(msg):
    if DEBUG_MODE:
        print(f"[Backend] {msg}")

# 윈도우 레지스트리 표준 순서
CURSOR_ROLES = [
    "Arrow", "Help", "AppStarting", "Wait", "Crosshair", "IBeam",
    "NWPen", "No", "SizeNS", "SizeWE", "SizeNWSE", "SizeNESW",
    "SizeAll", "UpArrow", "Hand", "Pin", "Person"
]

# main.cpl 리소스 ID
RESOURCE_IDS = {
    "Arrow"         : 207,
    "Wait"          : 208,
    "AppStarting"   : 209,
    "No"            : 210,
    "IBeam"         : 211,
    "Crosshair"     : 212,
    "SizeNS"        : 213,
    "SizeWE"        : 214,
    "SizeNWSE"      : 215,
    "SizeNESW"      : 216,
    "SizeAll"       : 217,
    "Help"          : 218,
    "NWPen"         : 219,
    "UpArrow"       : 220,
    "Hand"          : 225,
    "Pin"           : 226,
    "Person"        : 227
}

LOCALIZED_NAME_CACHE = {}

SPI_SETCURSORS = 0x0057
SPIF_UPDATEINIFILE = 0x01
SPIF_SENDCHANGE = 0x02

# =============================================================================
# [Core Logic] OS Translation & Registry Manager
# =============================================================================

def get_os_localized_name(role):
    if role in LOCALIZED_NAME_CACHE:
        return LOCALIZED_NAME_CACHE[role]

    res_id = RESOURCE_IDS.get(role)
    if res_id is None:
        LOCALIZED_NAME_CACHE[role] = None
        return None

    result = None
    libs_to_free = []

    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32

    if not getattr(kernel32.LoadLibraryExW, 'argtypes', None):
        kernel32.LoadLibraryExW.restype = ctypes.c_void_p
        kernel32.LoadLibraryExW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_uint]

    if not getattr(kernel32.FreeLibrary, 'argtypes', None):
        kernel32.FreeLibrary.argtypes = [ctypes.c_void_p]
        kernel32.FreeLibrary.restype = ctypes.c_int

    if not getattr(user32.LoadStringW, 'argtypes', None):
        user32.LoadStringW.restype = ctypes.c_int
        user32.LoadStringW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_wchar_p,
            ctypes.c_int
        ]

    if not getattr(kernel32.GetUserDefaultUILanguage, 'restype', None):
        kernel32.GetUserDefaultUILanguage.restype = ctypes.c_ushort

    target_libs = ['main.cpl', 'user32.dll', 'imageres.dll']

    try:
        sys_root = os.environ['SystemRoot']
        system32 = os.path.join(sys_root, 'System32')

        lang_tag = None
        try:
            user_lcid = kernel32.GetUserDefaultUILanguage()
            lang_code = locale.windows_locale.get(user_lcid)
            if lang_code:
                lang_tag = lang_code.replace('_', '-')
        except: pass

        found = False
        for lib_name in target_libs:
            if found: break

            paths_to_try = []
            if lang_tag:
                paths_to_try.append(os.path.join(system32, lang_tag, f"{lib_name}.mui"))
            paths_to_try.append(os.path.join(system32, lib_name))

            for path in paths_to_try:
                if not os.path.exists(path): continue

                lib = kernel32.LoadLibraryExW(path, None, 0x00000022)

                if lib:
                    libs_to_free.append(lib)
                    buf = ctypes.create_unicode_buffer(1024)

                    ret = user32.LoadStringW(lib, res_id, buf, 1024)

                    if ret > 0:
                        result = buf.value
                        found = True
                        # log(f"      [Localization] Found '{role}' -> '{result}' in {os.path.basename(path)}")
                        break

    except Exception as e:
        log(f"!! [Exception] get_os_localized_name: {e}")

    finally:
        for lib in libs_to_free:
            kernel32.FreeLibrary(lib)

    LOCALIZED_NAME_CACHE[role] = result
    return result

def apply_scheme_by_data(scheme_name, scheme_data_str):
    log(f">> [apply_scheme_by_data] Request to apply scheme: '{scheme_name}'")
    files = scheme_data_str.split(",")
    count = min(len(files), len(CURSOR_ROLES))

    try:
        key_path = r"Control Panel\Cursors"
        log(f"   [Registry] Opening HKCU\\{key_path}...")
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            for i in range(count):
                role = CURSOR_ROLES[i]
                path = os.path.expandvars(files[i].strip())
                # log(f"      [Registry] Setting {role} = {path}")

                winreg.SetValueEx(key, role, 0, winreg.REG_SZ, path)

            winreg.SetValueEx(key, None, 0, winreg.REG_SZ, scheme_name)
            winreg.SetValueEx(key, "Scheme Source", 0, winreg.REG_DWORD, 1)

        log("   [Registry] Values updated successfully.")
        log("   [System] Calling SPI_SETCURSORS...")

        user32 = ctypes.windll.user32
        user32.SystemParametersInfoW.restype = ctypes.c_bool

        res = ctypes.windll.user32.SystemParametersInfoW(SPI_SETCURSORS, 0, None, SPIF_UPDATEINIFILE | SPIF_SENDCHANGE)
        if res:
            log(f"   [System] Result: {res} (Success). Cursors should match '{scheme_name}'.")
        else:
            err = ctypes.get_last_error()
            log(f"!! [System] Result: {res} (Failed). Error Code: {err}")

    except Exception as e:
        log(f"!! [Error] apply_scheme failed: {e}")
        traceback.print_exc()

def get_all_schemes():
    schemes = {}
    log(">> [get_all_schemes] Querying Registry for existing schemes...")
    for root_key, root_name in [(winreg.HKEY_LOCAL_MACHINE, "HKLM"), (winreg.HKEY_CURRENT_USER, "HKCU")]:
        base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Control Panel\Cursors\Schemes" \
                    if root_key == winreg.HKEY_LOCAL_MACHINE \
                    else r"Control Panel\Cursors\Schemes"
        try:
            with winreg.OpenKey(root_key, base) as key:
                i = 0
                while True:
                    try:
                        n, v, _ = winreg.EnumValue(key, i)
                        schemes[n] = v
                        i += 1
                    except OSError: break
        except FileNotFoundError:
            # log(f"      [Info] {root_name} scheme key not found.")
            pass
        except Exception as e:
            log(f"!! [Error] accessing {root_name}: {e}")
    log(f"   [get_all_schemes] Found {len(schemes)} unique schemes.")
    return schemes

def get_current_cursor_paths():
    paths = {}
    log(">> [get_current_cursor_paths] Reading current cursor config...")
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Cursors") as key:
            for role in CURSOR_ROLES:
                try:
                    val, _ = winreg.QueryValueEx(key, role)
                    paths[role] = os.path.expandvars(val)
                except: paths[role] = ""
    except Exception as e:
        log(f"!! [Error] Failed to read current config: {e}")
    return paths

def register_scheme(scheme_name, scheme_data_str):
    log(f">> [register_scheme] Attempting to save scheme '{scheme_name}' to Registry.")
    try:
        key_path = r"Control Panel\Cursors\Schemes"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, scheme_name, 0, winreg.REG_SZ, scheme_data_str)
        log("   [Success] Registry write complete.")
        return True, None
    except Exception as e:
        log(f"!! [Error] register_scheme failed: {e}")
        return False, str(e)