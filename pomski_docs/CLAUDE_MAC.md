# POMSKI — macOS Build Instructions for Claude

This file is a briefing for Claude Code running on a Mac to produce a distributable
macOS build of POMSKI. Read the whole file before starting work.

---

## What POMSKI is

POMSKI is a live-coding music environment. The user writes Python pattern functions
in a browser at `http://localhost:8080` and they play back as MIDI in real time.

Key components:
- **`subsequence/`** — core Python library (pattern sequencer, MIDI, web UI)
- **`examples/pomski_template.py`** — the entry point; 16 MIDI channels, Ableton Link, live REPL
- **`examples/aalink_bridge.py`** — Ableton Link subprocess (see below)
- **`examples/live_bridge.py`** — AbletonOSC bridge
- **`examples/api_feeds.py`** — data feed helpers
- **`subsequence/assets/web/index.html`** — full browser UI (served at port 8080)

The Windows build is fully working and distributed via itch.io:
https://thinkinsound.itch.io/pomski

---

## Architecture

```
pomski_template.py
  └─ composition.play()          # asyncio event loop
       ├─ web_ui (port 8080)     # WebSocket + HTTP server
       ├─ live_server (port 5555) # REPL — exec() incoming code
       └─ sequencer              # MIDI clock + pattern scheduling
            └─ live_bridge       # AbletonOSC (port 11000/11001)
```

On Windows, Ableton Link runs in a detached subprocess (`aalink_bridge.py` /
`aalink_bridge.exe`) because `aalink.Link()` crashes in PyInstaller frozen Windows
processes due to SxS DLL redirection. **This issue is Windows-specific.**

---

## macOS vs Windows: key differences

### 1. aalink bridge — probably not needed on macOS

On Windows, `aalink.Link()` crashes inside a frozen exe due to Windows SxS DLL
redirection — a Windows-only mechanism. On macOS, PyInstaller frozen apps don't have
this issue. Try importing aalink directly in the main process first.

**First, test this before building:**
```python
import aalink, asyncio
loop = asyncio.new_event_loop()
link = aalink.Link(120.0, loop)
link.enabled = True
print("aalink works:", link.tempo, link.num_peers)
```
If this works in a standard Python environment on macOS, it will likely work in the
frozen app too, and the bridge subprocess approach is unnecessary.

**If aalink DOES work directly:** implement a simpler `_LinkProxy` that holds a real
`aalink.Link` object instead of a TCP socket to a subprocess.

**If aalink STILL crashes in the frozen app:** the bridge approach can be reused on
macOS — just remove the Windows-specific subprocess flags (see section 3 below).

### 2. Platform-specific code to fix in `examples/pomski_template.py`

#### a) Log directory
```python
# Current (Windows):
if getattr(sys, 'frozen', False):
    _LOG_DIR = os.path.join(os.environ.get('LOCALAPPDATA', ...), 'POMSKI')

# Change to:
if getattr(sys, 'frozen', False):
    if sys.platform == 'darwin':
        _LOG_DIR = os.path.join(os.path.expanduser('~'), 'Library', 'Logs', 'POMSKI')
    else:
        _LOG_DIR = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'POMSKI')
os.makedirs(_LOG_DIR, exist_ok=True)
```

#### b) `_kill_stale_bridge()` — uses Windows API
```python
# Current — Windows only:
import ctypes as _ct
_h = _ct.windll.kernel32.OpenProcess(1, False, _old_pid)
...

# Change to platform-aware:
def _kill_stale_bridge() -> None:
    _pid_file = os.path.join(tempfile.gettempdir(), 'pomski_aalink_pid.txt')
    try:
        _old_pid = int(open(_pid_file).read().strip())
        if sys.platform == 'win32':
            import ctypes as _ct
            _h = _ct.windll.kernel32.OpenProcess(1, False, _old_pid)
            if _h:
                _ct.windll.kernel32.TerminateProcess(_h, 0)
                _ct.windll.kernel32.CloseHandle(_h)
        else:
            import signal
            os.kill(_old_pid, signal.SIGTERM)
        os.remove(_pid_file)
    except Exception:
        pass
```

#### c) `_bridge_cmd()` — subprocess flags and exe path
```python
# Current — Windows only:
subprocess.Popen(
    _bridge_cmd(_port),
    ...
    creationflags=(subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP),
)

# Change to:
_flags = {}
if sys.platform == 'win32':
    _flags['creationflags'] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
subprocess.Popen(_bridge_cmd(_port), ..., **_flags)
```

And in `_bridge_cmd()`:
```python
if getattr(sys, 'frozen', False):
    if sys.platform == 'darwin':
        # macOS: bridge exe lives inside the .app bundle's Resources
        _exe = os.path.join(os.path.dirname(sys.executable), '..', 'Resources', 'aalink_bridge')
    else:
        _exe = os.path.join(sys._MEIPASS, 'aalink_bridge.exe')
    return [_exe, '127.0.0.1', str(port), _bpm]
else:
    _py = 'python3' if sys.platform != 'win32' else _find_python_exe()
    _scr = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aalink_bridge.py')
    return [_py, '-u', _scr, '127.0.0.1', str(port), _bpm]
```

#### d) asyncio policy — already guarded, no change needed
```python
# This is already correct:
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```

### 3. `examples/aalink_bridge.py` — remove Windows-only DLL preloading

The VC++ DLL preloading block is Windows-only:
```python
# This entire block can be skipped on macOS:
if sys.platform == 'win32':
    try:
        import ctypes as _ct
        _s32 = os.path.join(os.environ.get('SYSTEMROOT', r'C:\Windows'), 'System32')
        for _dll in ('vcruntime140.dll', ...):
            ...
    except Exception:
        pass
```

---

## macOS PyInstaller setup

### Install dependencies on the Mac

```bash
# Python 3.11 or 3.12 recommended (match the Windows build Python version)
brew install python@3.12

# Install all POMSKI dependencies
pip3 install pyinstaller
pip3 install websockets mido python-rtmidi pythonosc
pip3 install aalink          # Ableton Link Python bindings
pip3 install subsequence     # or install from source: pip install -e .

# Verify aalink works (important — test before building)
python3 -c "import aalink, asyncio; l = aalink.Link(120, asyncio.new_event_loop()); print('OK', l.tempo)"
```

### Create the app icon

macOS requires `.icns` format. Convert from `favicon.ico`:
```bash
# Using ImageMagick (brew install imagemagick):
mkdir pomski.iconset
for size in 16 32 64 128 256 512; do
    convert favicon.ico -resize ${size}x${size} pomski.iconset/icon_${size}x${size}.png
done
iconutil -c icns pomski.iconset -o pomski.icns
```

### Create `pomski_mac.spec`

Base it on `pomski.spec` with these changes:
- `icon='pomski.icns'` instead of `favicon.ico`
- If aalink bridge is NOT needed: remove aalink_bridge from datas, remove from excludes
- If aalink bridge IS needed: include `aalink_bridge` binary (no `.exe` extension on macOS)
- Add `bundle_identifier='io.thinkinsound.pomski'` to EXE
- Use `windowed=True` (no terminal window) — or `console=True` if debugging

```python
# pomski_mac.spec skeleton:
exe = EXE(
    ...
    name='POMSKI',
    icon='pomski.icns',
    console=False,   # no terminal on macOS
    bundle_identifier='io.thinkinsound.pomski',
)
app = BUNDLE(
    exe,
    name='POMSKI.app',
    icon='pomski.icns',
    bundle_identifier='io.thinkinsound.pomski',
    info_plist={
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleName': 'POMSKI',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '10.15',
    },
)
```

### Build

```bash
# If aalink bridge is needed as a separate binary:
pyinstaller aalink_bridge_mac.spec

# Main build:
pyinstaller pomski_mac.spec -y --clean

# Output: dist/POMSKI.app
```

---

## Code signing and notarization (required for distribution)

Without signing, macOS will block the app with a Gatekeeper warning. Users CAN
override this (right-click → Open), but it's bad UX.

### Sign (requires Apple Developer account, $99/yr)
```bash
codesign --deep --force --verify --verbose \
    --sign "Developer ID Application: Your Name (TEAMID)" \
    dist/POMSKI.app
```

### Notarize
```bash
# Create a zip for submission:
ditto -c -k --keepParent dist/POMSKI.app POMSKI.zip

# Submit to Apple:
xcrun notarytool submit POMSKI.zip \
    --apple-id "your@email.com" \
    --team-id "YOURTEAMID" \
    --password "app-specific-password" \
    --wait

# Staple the notarization ticket:
xcrun stapler staple dist/POMSKI.app
```

### Skip signing for a friend's-computer test build
If just testing functionality (not distributing), you can skip signing. The user
will need to right-click → Open the first time. Add this note to the itch.io page
if distributing unsigned.

---

## Distribution (itch.io)

Once built and signed:
```bash
# Zip the .app for upload:
ditto -c -k --keepParent dist/POMSKI.app POMSKI_mac.zip
```

Upload `POMSKI_mac.zip` to https://thinkinsound.itch.io/pomski as a new upload,
tagged as macOS.

---

## Testing checklist

- [ ] aalink imports without crashing in frozen app
- [ ] Ableton Link connects to Ableton Live on macOS
- [ ] MIDI output works (check Audio MIDI Setup → MIDI Studio)
- [ ] Web UI opens at http://localhost:8080
- [ ] REPL (port 5555) accepts connections
- [ ] BPM changes in POMSKI update Ableton's tempo
- [ ] Log files written to ~/Library/Logs/POMSKI/
- [ ] App icon appears correctly in Finder and Dock
- [ ] Gatekeeper allows launch (if signed + notarized)

---

## Reference: Windows build that works

The Windows build pipeline for reference:
1. `pyinstaller aalink_bridge.spec` → `dist/aalink_bridge.exe`
2. `pyinstaller pomski.spec -y --clean` → `dist/POMSKI/POMSKI.exe`
3. `iscc pomski_installer.iss` → `Output/POMSKI_Setup.exe`

The Windows installer is live at: https://thinkinsound.itch.io/pomski
