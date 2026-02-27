# pyinstaller --onefile --windowed --add-binary "adb/adb.exe;adb" --add-binary "adb/AdbWinApi.dll;adb"  --add-binary "adb/AdbWinUsbApi.dll;adb" main.py



import sys
import os
import subprocess
import time

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout,
    QPushButton, QPlainTextEdit,
    QLabel, QDialog, QFormLayout,
    QSpinBox, QDialogButtonBox
)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import (
    Qt, QThread, QRunnable, QThreadPool,
    QObject, pyqtSignal, pyqtSlot, QSettings
)

# =====================================================
# ADB RESOLVER (WORKS FOR DEV + PYINSTALLER)
# =====================================================

def get_bundled_adb():
    """
    Returns adb.exe path.
    - Uses embedded adb when packaged
    - Uses system adb when running from source
    """
    if getattr(sys, "frozen", False):
        base_dir = sys._MEIPASS
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    adb_path = os.path.join(base_dir, "adb", "adb.exe")
    return adb_path if os.path.exists(adb_path) else "adb"


# =====================================================
# SIGNALS
# =====================================================

class Signals(QObject):
    log = pyqtSignal(str)
    device_count = pyqtSignal(int)


# =====================================================
# DEVICE WORKER (ALWAYS RUNS COMMANDS)
# =====================================================

class DeviceWorker(QRunnable):
    def __init__(self, serial, signals):
        super().__init__()
        self.serial = serial
        self.signals = signals
        self.adb = get_bundled_adb()

    @pyqtSlot()
    def run(self):
        self.signals.log.emit(f"[+] Processing {self.serial}")

        # ---- Wait for boot ----
        try:
            r = subprocess.run(
                [self.adb, "-s", self.serial, "shell", "getprop", "sys.boot_completed"],
                capture_output=True,
                text=True,
                timeout=120
            )
            if r.stdout.strip() != "1":
                self.signals.log.emit(f"[!] {self.serial} boot timeout")
                return
        except Exception as e:
            self.signals.log.emit(f"[!] Boot check failed: {e}")
            return

        # ---- Wake device ----
        subprocess.run(
            [self.adb, "-s", self.serial, "shell", "input", "keyevent", "82"],
            capture_output=True
        )
        #replace ussd with actual ussd you want to run 
        # ---- Provisioning commands ----
        commands = [
            [self.adb, "-s", self.serial, "shell", "pm", "disable-user",
             "--user", "0", "com.google.android.setupwizard"],

            [self.adb, "-s", self.serial, "shell", "am", "broadcast",
             "-a", "android.provider.Telephony.SECRET_CODE",
             "-d", "android_secret_code://ussd"]
        ]

        for cmd in commands:
            subprocess.run(cmd, capture_output=True)

        self.signals.log.emit(f"[✓] Done {self.serial}")


# =====================================================
# MONITOR THREAD
# =====================================================

class MonitorThread(QThread):
    def __init__(self, max_devices, signals):
        super().__init__()
        self.adb = get_bundled_adb()
        self.max_devices = max_devices
        self.signals = signals
        self.running = False

        self.threadpool = QThreadPool()
        self.threadpool.setMaxThreadCount(max_devices)

    def run(self):
        self.running = True
        self.signals.log.emit(f"Monitoring started (max {self.max_devices} devices)")

        while self.running:
            try:
                r = subprocess.run(
                    [self.adb, "devices"],
                    capture_output=True,
                    text=True
                )

                devices = []
                for line in r.stdout.splitlines()[1:]:
                    if line.strip().endswith("\tdevice"):
                        devices.append(line.split("\t")[0])

                self.signals.device_count.emit(len(devices))

                for serial in devices:
                    worker = DeviceWorker(serial, self.signals)
                    self.threadpool.start(worker)

                self.msleep(2000)

            except Exception as e:
                self.signals.log.emit(f"[!] Poll error: {e}")
                self.msleep(1000)

    def stop(self):
        self.running = False
        self.threadpool.clear()
        self.threadpool.waitForDone(3000)
        self.quit()
        self.wait(5000)


# =====================================================
# SETTINGS DIALOG (ONLY MAX DEVICES)
# =====================================================

class SettingsDialog(QDialog):
    def __init__(self, max_devices, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setFixedSize(300, 150)

        layout = QFormLayout()

        self.max_spin = QSpinBox()
        self.max_spin.setRange(1, 120)
        self.max_spin.setValue(max_devices)
        layout.addRow("Max Devices:", self.max_spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addRow(buttons)
        self.setLayout(layout)


# =====================================================
# MAIN WINDOW
# =====================================================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self.settings = QSettings("MyCompany", "ADB_AutoProvision")
        self.max_devices = int(self.settings.value("max_devices", 6))

        self.monitor_thread = None

        self.setWindowTitle("ADB Auto-Provision v2.3")
        self.setGeometry(100, 100, 900, 700)

        self.create_menu_bar()
        self.build_ui()

        self.signals = Signals()
        self.signals.log.connect(self.append_log)
        self.signals.device_count.connect(self.update_device_count)

    # ---------------- UI ----------------
    def build_ui(self):
        widget = QWidget()
        self.setCentralWidget(widget)
        layout = QVBoxLayout()

        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("▶ Start")
        self.stop_btn = QPushButton("⏹ Stop")

        self.start_btn.setFixedSize(120, 50)
        self.stop_btn.setFixedSize(120, 50)
        self.stop_btn.setEnabled(False)

        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        btn_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        layout.addLayout(btn_layout)

        self.status_label = QLabel("Ready")
        self.device_label = QLabel("Devices: 0")

        layout.addWidget(self.status_label)
        layout.addWidget(self.device_label)

        layout.addWidget(QLabel("Live Log:"))
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumBlockCount(1000)

        layout.addWidget(self.log_edit)
        widget.setLayout(layout)

        self.start_btn.clicked.connect(self.start_monitoring)
        self.stop_btn.clicked.connect(self.stop_monitoring)

    # ---------------- MENU ----------------
    def create_menu_bar(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("&File")
        settings_action = QAction("Settings", self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self.show_settings)
        file_menu.addAction(settings_action)

        file_menu.addSeparator()
        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        help_menu = menubar.addMenu("&Help")
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    # ---------------- ACTIONS ----------------
    def show_settings(self):
        dialog = SettingsDialog(self.max_devices, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.max_devices = dialog.max_spin.value()
            self.settings.setValue("max_devices", self.max_devices)
            self.append_log(f"Settings saved: Max Devices = {self.max_devices}")

    def show_about(self):
        self.append_log("ADB Auto-Provisioner v2.3 — Embedded ADB")

    # ---------------- LOGGING ----------------
    def append_log(self, text):
        ts = time.strftime("%H:%M:%S")
        if any(k in text.lower() for k in ["!", "error", "failed", "timeout"]):
            html = f"[{ts}] <span style='color:#ff4444;font-weight:bold'>{text}</span>"
        else:
            html = f"[{ts}] <span style='color:#44ff44'>{text}</span>"

        self.log_edit.appendHtml(html)
        sb = self.log_edit.verticalScrollBar()
        sb.setValue(sb.maximum())

    def update_device_count(self, count):
        self.device_label.setText(f"Devices: {count}")

    # ---------------- CONTROL ----------------
    def start_monitoring(self):
        if self.monitor_thread and self.monitor_thread.isRunning():
            return

        self.monitor_thread = MonitorThread(self.max_devices, self.signals)
        self.monitor_thread.start()

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.status_label.setText("Provisioning active")

        self.append_log("ADB provisioning started (embedded ADB)")

    def stop_monitoring(self):
        if self.monitor_thread:
            self.monitor_thread.stop()
            self.monitor_thread = None

        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText("Stopped")

        self.append_log("Provisioning stopped")


# =====================================================
# ENTRY POINT
# =====================================================

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
