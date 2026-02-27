# adb-auto-provision
ADB Auto Provision is a Python-based automation tool that continuously detects Android devices connected via ADB and runs predefined provisioning commands in parallel. It supports up to six devices, checks for full boot completion, improves efficiency for factory and test environments.
pyinstaller code>>>>>>pyinstaller --onefile --windowed --add-binary "adb/adb.exe;adb" --add-binary "adb/AdbWinApi.dll;adb"  --add-binary "adb/AdbWinUsbApi.dll;adb" main.py
