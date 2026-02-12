# KeyBurst

KeyBurst is a Windows keyboard auto-clicker (key repeater) with a clean GUI.
You can configure up to 9 keys with individual intervals, set global start/stop
hotkeys, and save/load JSON configs.

## Features
- Up to 9 key entries (enable toggle, key text, interval in seconds)
- Global start/stop hotkeys (Windows)
- Loops through enabled keys in order
- Save / Save As / Load config
- Responsive GUI (Tkinter + worker thread)

## Requirements
- Windows 10/11
- Python 3.10+ (tested with 3.13)

## Setup (uv)
```powershell
uv venv .venv
uv pip install --python .venv pynput
```

## Run
```powershell
.\.venv\Scripts\python keyburst_clicker.py
```

## Hotkey format
Examples:
- `F1`
- `Ctrl+Alt+S`
- `Shift+F2`

Notes:
- Some laptops require `Fn+F1` to emit real F-keys.
- If a hotkey is already in use by another app, registration will fail.

## Build (single EXE)
```powershell
uv pip install --python .venv pyinstaller
.\.venv\Scripts\pyinstaller.exe --onefile --noconsole --name KeyBurst keyburst_clicker.py
```
The executable will be in `dist\KeyBurst.exe`.
