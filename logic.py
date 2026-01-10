import os
import csv
import glob
import zipfile
import backend

# =============================================================================
# [Constants & Globals]
# =============================================================================

DEBUG_MODE = False
ALIAS_FILE = "cursor_aliases.csv"
CUSTOM_ALIASES = {}

_LOG_CALLBACK = None

def set_debug(mode: bool):
    global DEBUG_MODE
    DEBUG_MODE = mode

def register_log_callback(func):
    global _LOG_CALLBACK
    _LOG_CALLBACK = func

def log(msg):
    if _LOG_CALLBACK:
        _LOG_CALLBACK(msg)
    elif DEBUG_MODE:
        print(f"[Logic] {msg}")

# =============================================================================
# [Business Logic] Alias & Matching
# =============================================================================

def load_custom_aliases():
    global CUSTOM_ALIASES
    CUSTOM_ALIASES.clear()
    log(f">> [load_custom_aliases] Reading alias file: {ALIAS_FILE}")

    if not os.path.exists(ALIAS_FILE):
        log("   [Info] Alias file does not exist. Using defaults only.")
        return

    try:
        count = 0
        with open(ALIAS_FILE, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            for row in reader:
                if not row: continue
                role_key = row[0].strip()
                if role_key not in backend.CURSOR_ROLES:
                    log(f"      [Skip] Unknown role key in CSV: {role_key}")
                    continue

                if role_key not in CUSTOM_ALIASES:
                    CUSTOM_ALIASES[role_key] = []

                for alias in row[1:]:
                    cleaned = alias.strip()
                    if cleaned:
                        CUSTOM_ALIASES[role_key].append(cleaned)
                        count += 1

        log(f"   [Done] Loaded {count} aliases for {len(CUSTOM_ALIASES)} roles.")
    except Exception as e:
        log(f"!! [Error] Failed to load alias csv: {e}")

def smart_match_file(filename, role):
    fname_lower = filename.lower().replace(" ", "")
    role_lower = role.lower()

    if role_lower in fname_lower:
        log(f"      [Match] Primary (English Key): {filename} -> {role}")
        return True

    local_name = backend.get_os_localized_name(role)
    if local_name:
        local_clean = local_name.lower().replace(" ", "")
        if local_clean in fname_lower:
            log(f"      [Match] Primary (Localized): {filename} -> {local_name} ({role})")
            return True

    aliases = CUSTOM_ALIASES.get(role, [])
    if aliases:
        for alias in aliases:
            alias_clean = alias.lower().replace(" ", "")
            if alias_clean in fname_lower:
                log(f"      [Match] Secondary (Alias '{alias}'): {filename} -> {role}")
                return True

    return False

# =============================================================================
# [Business Logic] Backup & Restore
# =============================================================================

def export_current_to_zip(zip_path):
    log(f">> [export_current_to_zip] Starting export to: {zip_path}")
    current_paths = backend.get_current_cursor_paths()
    count_ok = 0
    count_skip = 0

    try:
        with zipfile.ZipFile(zip_path, 'w') as zf:
            config_lines = ["[Schemes]\nName=BackupScheme\nData="]
            data_parts = []

            for role in backend.CURSOR_ROLES:
                original_path = current_paths.get(role, "")

                if os.path.exists(original_path):
                    filename = os.path.basename(original_path)
                    log(f"      [Archive] {role}: {filename}")
                    zf.write(original_path, filename)
                    data_parts.append(filename)
                    count_ok += 1
                else:
                    log(f"      [Skip] {role}: File '{original_path}' not found")
                    data_parts.append("")
                    count_skip += 1

            config_str = ",".join(data_parts)
            config_lines.append(config_str)
            zf.writestr("scheme.ini", "\n".join(config_lines))
        log(f"   [Done] Export successful. Packed {count_ok} files (Skipped {count_skip}).")
    except Exception as e:
        log(f"!! [Error] Export failed: {e}")
        raise e

def import_zip_scheme(zip_path):
    log(f">> [import_zip_scheme] Processing ZIP: {zip_path}")
    base_dir = os.path.join(os.path.expanduser("~"), "MouseCursorSchemes")
    scheme_name = os.path.splitext(os.path.basename(zip_path))[0]
    target_dir = os.path.join(base_dir, scheme_name)

    log(f"   [Config] Scheme Name: {scheme_name}")
    log(f"   [Info] Extract target: {target_dir}")

    if not os.path.exists(target_dir):
        log(f"   [Action] Creating directory...")
        os.makedirs(target_dir)

    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(target_dir)
            log(f"   [Unzip] Extracted {len(zf.namelist())} files successfully.")
    except Exception as e:
        log(f"!! [Error] Unzip failed: {e}")
        return False, str(e)

    ini_path = os.path.join(target_dir, "scheme.ini")
    scheme_data_list = [""] * len(backend.CURSOR_ROLES)

    if os.path.exists(ini_path):
        log(f"   [Info] Found scheme.ini. Parsing...")
        try:
            with open(ini_path, 'r') as f:
                content = f.read()
                for line in content.splitlines():
                    if line.startswith("Data="):
                        raw_data = line.replace("Data=", "").strip()
                        parts = raw_data.split(",")
                        scheme_data_list = [os.path.join(target_dir, p) if p else "" for p in parts]
                        log(f"   [Info] Parsed Data from ini (Length: {len(scheme_data_list)})")
                        break
        except Exception as e:
            log(f"!! [Error] Failed to read scheme.ini: {e}")
    else:
        log("   [Info] scheme.ini missing. Initiating Smart Match...")

        matched_dict = scan_cursor_files(target_dir)

        for idx, role in enumerate(backend.CURSOR_ROLES):
            if role in matched_dict:
                scheme_data_list[idx] = matched_dict[role]

        log("   [Info] Smart Match complete.")

    full_data_str = ",".join(scheme_data_list)
    log(f"   [Action] Registering scheme '{scheme_name}' to registry...")

    success, error_msg = backend.register_scheme(scheme_name, full_data_str)

    if success:
        log("   [Action] Applying scheme immediately...")
        backend.apply_scheme_by_data(scheme_name, full_data_str)
        return True, scheme_name
    else:
        log(f"!! [Error] Registration failed: {error_msg}")
        return False, error_msg

def scan_cursor_files(target_dir):
    log(f">> [scan_cursor_files] Root: {target_dir}")
    files = glob.glob(os.path.join(target_dir, "**"), recursive=True)
    log(f"   [Info] Found {len(files)} items in directory.")

    matched_data = {}
    used_files = set()

    for role in backend.CURSOR_ROLES:
        # log(f"      [Loop] Finding match for {role}...")
        for fpath in files:
            if fpath in used_files: continue

            fname = os.path.basename(fpath)

            if not (fname.lower().endswith('.cur') or fname.lower().endswith('.ani')):
                continue

            if smart_match_file(fname, role):
                matched_data[role] = fpath
                used_files.add(fpath)
                break

    log(f"   [Summary] Successfully matched {len(matched_data)} roles out of {len(backend.CURSOR_ROLES)}.")
    return matched_data