import os
import sys
import zipfile
import struct

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QScrollArea, QMessageBox, QGroupBox, QFrame,
    QSplitter, QListWidget, QTextEdit, QAbstractItemView
)

from PySide6.QtGui import QPixmap, QTextCursor
from PySide6.QtCore import Qt

import backend
import logic

# =============================================================================
# [Queue & Logging] Strict Callable Only
# =============================================================================

DEBUG_MODE = False
IPC_QUEUE = None

def set_debug(mode: bool):
    global DEBUG_MODE
    DEBUG_MODE = mode

def log(msg):
    if DEBUG_MODE:
        print(f"[GUI_Local] {msg}")

    if IPC_QUEUE:
        try:
            task = backend.LogTask("GUI", msg)
            IPC_QUEUE.put(task)
        except:
            pass

# =============================================================================
# [GUI Class]
# =============================================================================

class SchemeEditor(QMainWindow):
    def __init__(self, mode="create", zip_path=None):
        log(f">> [Editor] Initialing Window. Mode={mode}, ZipPath={zip_path}")
        super().__init__()
        self.setWindowTitle("마우스 커서 구성표 편집기")
        self.resize(550, 750)
        self.mode = mode
        self.cursor_map = {role: "" for role in backend.CURSOR_ROLES}

        self.setup_ui()

        if mode == "export":
            log("   [Editor] Export Mode: Loading current system scheme.")
            self.load_current_scheme()

        elif mode == "create" and zip_path:
            log(f"   [Editor] Create Mode: Auto-loading zip={zip_path}")
            self.load_from_zip(zip_path)

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(15)

        if self.mode == "create":
            load_group = QGroupBox("1. 소스 불러오기")
            load_layout = QHBoxLayout(load_group)

            self.btn_load_folder = QPushButton("📂 폴더에서 자동 매칭")
            self.btn_load_folder.setFixedHeight(35)
            self.btn_load_folder.clicked.connect(self.load_from_folder)
            load_layout.addWidget(self.btn_load_folder)

            self.btn_load_zip = QPushButton("📦 ZIP 파일 불러오기")
            self.btn_load_zip.setFixedHeight(35)
            self.btn_load_zip.clicked.connect(self.load_from_zip)
            load_layout.addWidget(self.btn_load_zip)

            main_layout.addWidget(load_group)

        list_group = QGroupBox("2. 커서 매핑 확인 및 수정")
        list_layout = QVBoxLayout(list_group)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll_content = QWidget()
        self.form_layout = QVBoxLayout(scroll_content)
        self.form_layout.setContentsMargins(0, 0, 0, 0)
        self.form_layout.setSpacing(5)

        self.path_edits = {}
        self.preview_labels = {}

        for role in backend.CURSOR_ROLES:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 2, 0, 2)

            local_hint = backend.get_os_localized_name(role)
            display_name = f"{role}\n({local_hint})" if local_hint else role

            lbl_name = QLabel(display_name)
            lbl_name.setFixedWidth(120)
            lbl_name.setStyleSheet("font-size: 11px;")

            lbl_preview = QLabel()
            lbl_preview.setFixedSize(32, 32)
            lbl_preview.setStyleSheet("background-color: #B0B0B0; border: 1px solid #999; border-radius: 4px;")
            lbl_preview.setAlignment(Qt.AlignCenter)
            self.preview_labels[role] = lbl_preview

            edit = QLineEdit()
            edit.setPlaceholderText("미지정")
            edit.setReadOnly(True)
            self.path_edits[role] = edit

            btn_find = QPushButton("찾기")
            btn_find.setFixedWidth(50)
            btn_find.clicked.connect(lambda _, r=role: self.browse_file(r))

            row_layout.addWidget(lbl_name)
            row_layout.addWidget(lbl_preview)
            row_layout.addWidget(edit)
            row_layout.addWidget(btn_find)

            self.form_layout.addWidget(row_widget)

        scroll.setWidget(scroll_content)
        list_layout.addWidget(scroll)
        main_layout.addWidget(list_group)

        if self.mode == "create":
            save_group = QGroupBox("3. 저장 및 적용")
            save_layout = QVBoxLayout(save_group)

            name_row = QHBoxLayout()
            name_row.addWidget(QLabel("구성표 이름:"))
            self.name_input = QLineEdit()
            self.name_input.setPlaceholderText("예: MyCustomTheme")
            name_row.addWidget(self.name_input)

            btn_apply = QPushButton("저장 후 적용")
            btn_apply.setFixedHeight(40)
            btn_apply.setStyleSheet("font-weight: bold; font-size: 13px;")
            btn_apply.clicked.connect(self.save_and_apply)

            save_layout.addLayout(name_row)
            save_layout.addWidget(btn_apply)
            main_layout.addWidget(save_group)

        elif self.mode == "export":
            export_group = QGroupBox("내보내기")
            export_layout = QVBoxLayout(export_group)

            name_row = QHBoxLayout()
            name_row.addWidget(QLabel("파일 이름:"))
            self.name_input = QLineEdit()
            name_row.addWidget(self.name_input)

            btn_export = QPushButton("ZIP으로 내보내기")
            btn_export.setFixedHeight(40)
            btn_export.clicked.connect(self.do_export_zip)

            export_layout.addLayout(name_row)
            export_layout.addWidget(btn_export)
            main_layout.addWidget(export_group)

    # -------------------------------------------------------------------------
    # [Helper] Image Loading Logic
    # -------------------------------------------------------------------------

    def extract_ani_icon(self, path):
        try:
            with open(path, 'rb') as f:
                data = f.read()
            if data[:4] != b'RIFF': return None
            tag_index = data.find(b'icon')
            if tag_index == -1: return None
            size_offset = tag_index + 4
            if size_offset + 4 > len(data): return None
            chunk_size = struct.unpack('<I', data[size_offset:size_offset+4])[0]
            data_start = size_offset + 4
            data_end = data_start + chunk_size
            if data_end > len(data): return None
            return data[data_start:data_end]
        except Exception: return None

    def set_role_file(self, role, file_path):
        # log(f"      [UI] Setting {role} <= {os.path.basename(file_path)}")

        self.cursor_map[role] = file_path
        self.path_edits[role].setText(file_path)

        pixmap = QPixmap()

        if file_path and os.path.exists(file_path):
            ext = os.path.splitext(file_path)[1].lower()

            if ext == '.ani':
                icon_data = self.extract_ani_icon(file_path)
                if icon_data: pixmap.loadFromData(icon_data)

            if pixmap.isNull(): pixmap.load(file_path)

            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    self.preview_labels[role].size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                self.preview_labels[role].setPixmap(scaled)
            else:
                self.preview_labels[role].clear()
                self.preview_labels[role].setText("X")
        else:
            self.preview_labels[role].clear()

    # -------------------------------------------------------------------------
    # [Event Handlers]
    # -------------------------------------------------------------------------

    def browse_file(self, role):
        log(f">> [User] Browse file for role: {role}")
        fname, _ = QFileDialog.getOpenFileName(self, f"{role} 커서 선택", "", "Cursor Files (*.ani *.cur)")
        if fname:
            log(f"   [User] Selected: {fname}")
            self.set_role_file(role, fname)

    def apply_directory_mapping(self, folder_path, scheme_name):
        log(f">> [Logic] apply_directory_mapping. Name='{scheme_name}'")

        matched_dict = logic.parse_scheme_ini(folder_path)
        if not matched_dict:
            log("   [Logic] No valid scheme.ini found. Falling back to heuristic scan.")
            matched_dict = logic.scan_cursor_files(folder_path)
        else:
            log("   [Logic] Applied mapping from scheme.ini.")
            
        mapped_count = 0
        for role, fpath in matched_dict.items():
            self.set_role_file(role, fpath)
            mapped_count += 1

        self.name_input.setText(scheme_name)
        log(f"   [Logic] Mapping complete. Mapped {mapped_count} roles.")
        QMessageBox.information(self, "로드 완료", f"'{scheme_name}' 설정으로 {mapped_count}개의 파일을 매칭했습니다.")

    def load_from_folder(self):
        log(">> [User] Clicked Load from Folder")
        folder = QFileDialog.getExistingDirectory(self, "커서 파일이 있는 폴더 선택")
        if not folder:
            log("   [User] Cancelled folder selection.")
            return
        folder_name = os.path.basename(os.path.normpath(folder))
        self.apply_directory_mapping(folder, folder_name)

    def load_from_zip(self, zip_path=None):
        target_zip = zip_path
        if not target_zip:
            log(">> [User] Clicked Load from ZIP")
            target_zip, _ = QFileDialog.getOpenFileName(self, "ZIP 파일 선택", "", "Zip Files (*.zip)")

        if not target_zip:
            log("   [User] Cancelled ZIP selection.")
            return

        try:
            scheme_name = os.path.splitext(os.path.basename(target_zip))[0]
            base_dir = os.path.join(os.path.expanduser("~"), "MouseCursorSchemes")
            target_dir = os.path.join(base_dir, scheme_name)

            if not os.path.exists(target_dir): os.makedirs(target_dir)

            log(f"   [Action] Extracting ZIP to: {target_dir}")
            with zipfile.ZipFile(target_zip, 'r') as zf:
                zf.extractall(target_dir)

            self.apply_directory_mapping(target_dir, scheme_name)

        except Exception as e:
            log(f"!! [Error] ZIP Load Error: {e}")
            QMessageBox.critical(self, "오류", f"ZIP 파일 로드 실패:\n{e}")

    def save_and_apply(self):
        name = self.name_input.text().strip()
        log(f">> [User] Clicked Save & Apply. Name='{name}'")
        if not name:
            QMessageBox.warning(self, "오류", "구성표 이름을 입력하세요.")
            return

        log(f"   [Validation] Checking for duplicate names...")
        try:
            existing_schemes = backend.get_all_schemes()
            if name in existing_schemes:
                log(f"!! [Validation] Name '{name}' already exists.")
                QMessageBox.warning(self, "이름 중복", f"구성표 이름 '{name}'은(는) 이미 존재합니다.\n다른 이름을 사용해주세요.")
                return
        except Exception as e:
            log(f"!! [Error] Validation check failed: {e}")
            return

        data_list = [self.cursor_map[role] for role in backend.CURSOR_ROLES]
        data_str = ",".join(data_list)

        try:
            log(f"   [Action] Registering scheme to Registry...")
            success, err = backend.register_scheme(name, data_str)
            if not success: raise Exception(f"Registry Write Failed: {err}")

            log("   [Action] Applying scheme via Backend...")
            backend.apply_scheme_by_data(name, data_str)

            if IPC_QUEUE:
                log("   [IPC] Sending RefreshMenuTask...")
                IPC_QUEUE.put(backend.RefreshMenuTask())

            QMessageBox.information(self, "성공", f"구성표 '{name}'이(가) 적용되었습니다.")
            self.close()
        except Exception as e:
            log(f"!! [Error] Save/Apply failed: {e}")
            QMessageBox.critical(self, "오류", str(e))

    def load_current_scheme(self):
        log(">> [Editor] Loading current system configuration...")
        current = backend.get_current_cursor_paths()
        count = 0
        for role, path in current.items():
            self.set_role_file(role, path)
            if path: count += 1
        self.name_input.setText("MyCursorScheme")
        log(f"   [Editor] Loaded {count} cursor paths.")

    def do_export_zip(self):
        name = self.name_input.text().strip()
        log(f">> [User] Clicked Export ZIP. Name='{name}'")
        if not name: name = "BackupScheme"

        fname, _ = QFileDialog.getSaveFileName(self, "ZIP으로 저장", f"{name}.zip", "Zip Files (*.zip)")
        if fname:
            try:
                logic.export_current_to_zip(fname)
                QMessageBox.information(self, "성공", "내보내기 완료")
                self.close()
            except Exception as e:
                log(f"!! [Error] Export Failed: {e}")
                QMessageBox.critical(self, "오류", str(e))
        else:
            log("   [User] Export cancelled.")

# =============================================================================
# [Process Entry Points]
# =============================================================================

def run_editor_process(mode="create", zip_path=None, ipc_queue=None, debug_mode=False):
    global IPC_QUEUE
    IPC_QUEUE = ipc_queue
    set_debug(debug_mode)
    if IPC_QUEUE:
        logic.register_log_callback(lambda msg: IPC_QUEUE.put(backend.LogTask("Logic_GUI", msg)))
    log(f">> [Process] Editor Process Started. PID: {os.getpid()}, Mode={mode}")
    app = QApplication(sys.argv)
    window = SchemeEditor(mode=mode, zip_path=zip_path)
    window.show()
    exit_code = app.exec()
    log(f">> [Process] Editor Terminating (Code: {exit_code})")
    sys.exit(exit_code)

def run_zip_import_process(ipc_queue=None, debug_mode=False):
    global IPC_QUEUE
    IPC_QUEUE = ipc_queue
    set_debug(debug_mode)
    if IPC_QUEUE:
        logic.register_log_callback(lambda msg: IPC_QUEUE.put(backend.LogTask("Logic_GUI", msg)))
    log(">> [Process] ZIP Import Process Started.")
    app = QApplication(sys.argv)
    dummy = QWidget()
    fname, _ = QFileDialog.getOpenFileName(
        dummy,
        "가져올 ZIP 파일 선택",
        "",
        "Zip Files (*.zip)"
    )
    if fname:
        log(f"   [Selection] User selected: {fname}")
        window = SchemeEditor(mode="create", zip_path=fname)
        window.show()
        app.exec()
    else:
        log("   [Selection] Cancelled.")
    sys.exit()

# =============================================================================
# [License Dialog]
# =============================================================================

class LicenseViewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("오픈소스 라이선스")
        self.resize(700, 500)
        self.setup_ui()
        self.load_data()

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(5)
        
        info_label = QLabel("이 소프트웨어에 사용된 오픈소스 라이선스 고지:")
        info_label.setStyleSheet("font-weight: bold; margin-bottom: 2px;")
        layout.addWidget(info_label)

        splitter = QSplitter(Qt.Horizontal)
        
        self.list_widget = QListWidget()
        self.list_widget.setFixedWidth(200)
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.list_widget.currentItemChanged.connect(self.on_item_changed)
        splitter.addWidget(self.list_widget)

        self.text_viewer = QTextEdit()
        self.text_viewer.setReadOnly(True)
        self.text_viewer.setFontFamily("Consolas")
        splitter.addWidget(self.text_viewer)

        layout.addWidget(splitter, 1)
        
        btn_close = QPushButton("닫기")
        btn_close.clicked.connect(self.close)
        layout.addWidget(btn_close, alignment=Qt.AlignRight)

    def load_data(self):
        self.license_data = logic.get_license_data()
        
        self.list_widget.clear()
        if not self.license_data:
            self.text_viewer.setText("라이선스 파일을 찾을 수 없습니다.\n(licenses 폴더를 확인하세요)")
            return

        sorted_keys = sorted(self.license_data.keys())
        for name in sorted_keys:
            self.list_widget.addItem(name)
        
        if sorted_keys:
            self.list_widget.setCurrentRow(0)

    def on_item_changed(self, current, previous):
        if not current:
            return
        filename = current.text()
        content = self.license_data.get(filename, "")
        self.text_viewer.setText(content)
        self.text_viewer.moveCursor(QTextCursor.Start)

def run_license_process(ipc_queue=None, debug_mode=False):
    global IPC_QUEUE
    IPC_QUEUE = ipc_queue
    set_debug(debug_mode)
    
    log(">> [Process] License Viewer Process Started.")
    app = QApplication(sys.argv)
    
    window = LicenseViewer()
    window.show()
    
    exit_code = app.exec()
    log(f">> [Process] License Viewer Terminating (Code: {exit_code})")
    sys.exit(exit_code)