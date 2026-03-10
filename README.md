# POMSKI

Write music as Python code. Change it while it's playing.

**POMSKI** — *Python Only MIDI Sequencer Keyboard Interface* — named after Qina, a very good Pomsky dog.

POMSKI is a MIDI sequencer you control from a Python script — or from a live coding environment where you can rewrite patterns, shift harmonies, and retune the tempo mid-performance without ever stopping playback.

```python
from pomski import Composition

composition = Composition(key="C", bpm=120)

@composition.pattern(channel=1, length=4)
def bass(p):
    p.note(36, beat=0, velocity=100, duration=1)
    p.note(43, beat=2, velocity=80,  duration=0.5)

composition.web_ui()   # open the browser dashboard
composition.live()     # start the live coding server
composition.play()
```

---

## Origin

POMSKI is a fork of [subsequence](https://github.com/simonholliday/subsequence) by Simon Holliday, extended with a browser-based Web UI, Ableton Link sync, Windows compatibility fixes, and a Max for Live device. The original AGPLv3 license and copyright are preserved.

---

## Installation

You'll need Python 3.10+ and a DAW or hardware synth receiving MIDI.

```bash
git clone https://github.com/ThinkInSound/POMSKI.git
cd POMSKI
pip install -e .
```

> **Important:** use `git clone`, not the ZIP download. The ZIP is missing files that the installer needs.

**Windows users** — POMSKI works on Windows. See the [Windows section](#windows) below.

### Optional extras

```bash
pip install aalink              # Ableton Link tempo sync
pip install mido python-rtmidi  # MIDI device selection in the Web UI
```

---

## The basics

### Patterns

A pattern is a function that gets called every time its loop comes around. Return notes by calling `pattern.note()`:

```python
@composition.pattern(channel=1, length=2)
def kick(p):
    p.note(36, beat=0, velocity=110, duration=0.1)
```

`beats` sets the loop length. `bar` and `beat` tell you where you are in the composition so you can vary things over time.

### Harmony

Tell POMSKI what key and chord you're in and it will transpose your patterns automatically:

```python
composition.harmony(key="D", chord="minor7")
```

### Sections

Organise your piece into named sections with automatic transitions:

```python
composition.form([
    ("intro",  4),   # 4 bars
    ("verse",  8),
    ("chorus", 8),
])
```

---

## Live coding

The real power of POMSKI is changing things while they play. Start the live coding server before `play()`:

```python
composition.live()     # starts a server on port 5555
composition.play()
```

Then from the **Web UI** (or any text editor that can open a socket) you can type Python and hit send — your changes take effect on the next bar:

```python
# change the tempo
composition.set_bpm(140)

# mute a pattern while you work on it
composition.mute("bass")

# redefine a pattern entirely
@composition.pattern(channel=1, length=4)
def bass(p):
    p.note(33, beat=0, velocity=90, duration=2)
```

---

## Web UI

The browser dashboard gives you a visual overview of everything happening in your composition and a built-in code editor for sending live changes.

```python
composition.web_ui()
composition.live()
composition.play()
```

Then open **http://localhost:8080** in any browser.

### What's on screen

**Topbar**
- BPM display — drag up/down to change tempo, or tap the TAP button to set it by feel
- Bar and beat counters
- Current chord and key
- Link pill — shows Ableton Link status; click to toggle sync on/off
- Section progress bar

**Log tab** — everything you send to the REPL and every response comes back here in colour. The quick command input at the bottom accepts Python one-liners, or prefix with `cx:` to send a ClyphX Pro action instead (e.g. `cx: 1/MUTE ON`).

**Signals tab** — live scrolling waveforms for any LFOs or values you've registered with the conductor. Useful for checking that modulations are doing what you expect.

**Patterns tab** — every running pattern listed with a mute button and a small 16-step grid showing which steps have notes and how loud they are.

**Prefs tab** — turn Ableton Link on or off, select your MIDI input/output device, and monitor AbletonOSC connection status (track count updates live as tracks are added or removed).

### Keyboard shortcuts

| Keys | What it does |
|---|---|
| `Shift+Enter` | Send editor code to the live coding server |
| `Ctrl+↑` / `Ctrl+↓` | Step through previous commands |
| `Tab` | Indent (4 spaces) |

---

## Ableton Link

Link keeps POMSKI's tempo locked to Ableton Live — and anything else on your network that supports Link (Ableton Live, Reason, Traktor, various iOS apps).

```bash
pip install aalink
```

That's it. If aalink is installed POMSKI will connect to Link automatically when you call `play()`. You'll see the peer count in the Link pill in the Web UI.

- Change tempo in Ableton → POMSKI follows
- Call `composition.set_bpm(140)` → Ableton follows
- Toggle sync on/off any time from the Prefs tab

---

## AbletonOSC integration

POMSKI can communicate directly with Ableton Live via [AbletonOSC](https://github.com/ideoforms/AbletonOSC), giving you programmatic control over Live's session from Python code or the REPL.

### Setup

1. Install AbletonOSC as a remote script in Ableton (see its README)
2. Add `LiveBridge` to your script:

```python
from examples.live_bridge import LiveBridge

composition = Composition(key="C", bpm=120)
live = LiveBridge(composition)

# ... your patterns ...

composition.web_ui()
composition.live()
composition.play()
```

The bridge connects automatically once `play()` starts. Connection status and track count are shown in the Prefs tab.

### Controlling Live from Python

```python
# Transport
live.play()
live.stop_transport()

# Mixer
live.track_volume(0, 0.85)   # track index, value 0.0–1.0
live.track_mute(0, True)
live.track_send(0, 0, 0.5)   # track, send index, value

# Clips
live.clip_play(0, 0)         # track, clip slot
live.clip_stop(0, 0)
live.scene_play(0)

# Devices
live.device_param(0, 0, 0, 0.5)   # track, device, param, value 0–1

# Raw OSC (full AbletonOSC API available)
live.send("/live/song/create_midi_track", -1)
live.send("/live/track/set/arm", 0, 1)
```

---

## ClyphX Pro integration

If you have [ClyphX Pro](https://isotonikstudios.com/product/clyphx-pro/) installed, POMSKI can trigger its action strings directly from Python.

```python
# Arbitrary action strings — uses a hidden X-Clip trigger track
live.clyphx("BPM 128")
live.clyphx("1/MUTE ON")
live.clyphx("1/DEV(1) ON ; 2/ARM ON ; BPM 140")
live.clyphx("(PSEQ) 1/MUTE ; 2/MUTE ; 3/MUTE")

# Pre-defined X-OSC addresses — faster, bypasses AbletonOSC entirely
# Requires entries in ClyphX Pro's X-OSC.txt file
live.clyphx_osc("/MY_ACTION")
```

From the Web UI quick command box, prefix with `cx:`:

```
cx: 1/MUTE ON
cx: BPM 128 ; METRO
```

### How it works

`live.clyphx()` creates a single hidden MIDI track (`_POMSKI_CLYPHX`) on first call, drops a 1-bar clip in slot 0, renames it to the action string wrapped in ClyphX bracket syntax, and fires it. ClyphX Pro intercepts the launch and executes the action list. The track is muted so it makes no sound.

`live.clyphx_osc()` sends a raw OSC message directly to ClyphX Pro's built-in OSC receiver on port 7005, bypassing AbletonOSC entirely. Use this for performance-critical or frequently-triggered actions that you've pre-mapped in `X-OSC.txt`.

---

## Troubleshooting MIDI output

**LoopBe Internal MIDI — silent muting**

LoopBe has a feedback protection feature that silently mutes the port if it detects a MIDI loop. The port indicator in the system tray turns red. This can happen when Ableton Live and AbletonOSC are running alongside POMSKI.

Fix: right-click the LoopBe icon in the taskbar and reset/unmute the port.

**MIDI activity light blinking but no sound**

Check that your DAW instrument tracks are set to receive from the correct MIDI port — the one POMSKI is sending to. Run `print(composition._sequencer.output_device_name)` in the REPL to confirm which port is in use.

---


## Windows

POMSKI runs on Windows with two things to be aware of:

**1. Use git clone**
Download via `git clone` rather than the ZIP button on GitHub. The ZIP is missing the `.git` folder and the installer won't work without it.

**2. No extra steps needed for asyncio**
Older versions of POMSKI crashed on Windows due to a signal handler that Windows doesn't support. This is fixed — it just works.

---

## Max for Live device (still in testing)

If you use Ableton Live you can add a small MIDI device to any track that shows whether POMSKI is connected and lets you open the Web UI with one click.

The device files are in `tools/m4l/`:

**Setup (one time):**
1. In Ableton, drag a **Max MIDI Effect** onto a MIDI track
2. Click the pencil to open it in Max
3. Select everything in the patch and delete it
4. Open `subsequence_webui_PASTE.maxpat` in a text editor, copy everything, then go back to Max and choose **Edit → Paste from Clipboard**
5. Copy `subsequence.js` into the same folder as your saved `.amxd` file
6. First time only: click the `node.script` object and send it the message `script npm install ws`

The device connects automatically when POMSKI is running and reconnects if it drops. You'll see a green LED when it's live and the current BPM ticking alongside it.

---

## API quick reference

| Call | What it does |
|---|---|
| `composition.play()` | Start everything — call this last |
| `composition.set_bpm(120)` | Change tempo; syncs to Link if connected |
| `composition.mute("name")` | Silence a pattern by name |
| `composition.unmute("name")` | Bring a pattern back |
| `composition.web_ui()` | Start the browser dashboard (port 8080) |
| `composition.live()` | Start the live coding server (port 5555) |
| `composition.form_next()` | Jump to the next section now |
| `composition.form_jump("chorus")` | Jump to a named section |
| `composition.harmony(key, chord)` | Change key and chord |

---

## License

AGPL-3.0 — inherited from [subsequence](https://github.com/simonholliday/subsequence). If you run a modified version of POMSKI as a network service, you must make the source available to its users. See the [LICENSE](LICENSE) file for details.
