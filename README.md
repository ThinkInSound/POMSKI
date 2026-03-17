# POMSKI

Write music as Python code. Change it while it's playing.

<img width="1980" height="1315" alt="pomski" src="https://github.com/user-attachments/assets/e6d2a373-c6fc-4682-9a99-62bbd8ff75cb" />

**POMSKI** — *Python Only MIDI Sequencer Keyboard Interface* — named after Qina, a very good Pomsky dog.

POMSKI is a MIDI sequencer you control with Python; it's a live coding environment where you can rewrite patterns, shift harmonies, and retune the tempo mid-performance without ever stopping playback. POMSKI is also deeply integrated with Ableton Live, with AbletonOSC, Ableton Link, and ClyphX control natively built-in. 

```python
@composition.pattern(channel=0, length=4)
def bass(p):
    p.note(36, beat=0, velocity=100, duration=0.5)
    p.note(43, beat=2, velocity=80,  duration=0.5)

```

---

## Origin

POMSKI is a fork of [subsequence](https://github.com/simonholliday/subsequence) by Simon Holliday, extended with a browser-based Web UI, Ableton Link sync, AbletonOSC, ClyphX, Music21 libraries, and a soon-to-release Max for Live device. The original AGPLv3 license and copyright are preserved.

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
pip install music21             # Exotic scale support (p.quantize_m21)
```

---

## The basics

### Patterns

A pattern is a function that gets called every time its loop comes around. Place notes by calling methods on `p`, the pattern builder:

```python
@composition.pattern(channel=0, length=2)
def kick(p):
    p.note(36, beat=0, velocity=110, duration=0.1)
```

`length` sets the loop length in beats.

### MIDI channels

POMSKI channels are **0-indexed**: `channel=0` = MIDI channel 1, `channel=9` = MIDI channel 10 (usually drums). The template assigns slots `ch1`–`ch16` to channels `0`–`15` respectively.

### Drums

Use `drum_note_map=gm_drums.GM_DRUM_MAP` on the decorator to address drums by name. Channel 9 is the standard GM drums channel.

```python
@composition.pattern(channel=9, length=4, drum_note_map=gm_drums.GM_DRUM_MAP)
def drums(p):
    p.hit_steps("kick_1",       [0, 3, 8, 12], velocity=110)
    p.hit_steps("snare_1",      [4, 12],        velocity=100)
    p.hit_steps("hi_hat_closed", range(16),     velocity=70)
```

### Harmony

Tell POMSKI what harmonic style to use and it will manage chord progressions automatically:

```python
composition.harmony(style="functional_major", cycle_beats=4, gravity=0.8)
```

Available styles include `"functional_major"`, `"aeolian_minor"`, `"dorian"`, `"lydian"`, and others. `cycle_beats` sets how often the chord changes. `gravity` (0–1) controls how strongly chords pull toward the tonic.

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

The real power of POMSKI is changing things while they play. From the **Web UI** (or any text editor that can open a socket) you can type Pythonand hit send — your changes take effect on the next bar:

```python
# change the tempo
composition.set_bpm(140)

# mute a pattern while you work on it
composition.mute("bass")

# redefine a pattern entirely
@composition.pattern(channel=0, length=4)
def bass(p):
    p.note(33, beat=0, velocity=90, duration=2)
```

---

## Web UI

The browser dashboard gives you a visual overview of everything happening in your composition and a built-in code editor for sending live changes.

```python
cd [POMSKI repo examples folder]
python pomski_template.py
Choose your MIDI device
```

Then open **http://localhost:8080** in any browser.

### What's on screen

**Topbar**
- BPM display — drag up/down to change tempo, or tap the TAP button to set it by feel
- Bar and beat counters
- Current chord and key
- Link pill — shows Ableton Link status; click to toggle sync on/off
- Section progress bar

**Bottom Bar** - clear the log, clear the editor window, record a MIDI session to file (slider bar controls for how many bars POMSKI will record)

**Log tab** — everything you send to the REPL and every response comes back here in colour. The quick command input at the bottom accepts Python one-liners, or prefix with `cx:` to send a ClyphX Pro action instead (e.g. `cx: 1/MUTE ON`).

**Signals tab** — live scrolling waveforms for any LFOs or values you've written to `composition.data`. Each signal has a ✕ button to remove it. Useful for checking that modulations are doing what you expect.

**Patterns tab** — every running pattern listed with a mute button, a clear (×) button, and a small 16-step grid showing which steps have notes.

**Refs tab** — copy-ready code examples for every algorithmic method, API calling, plus a button to open the full tutorial in a new window.

**Prefs tab** — turn Ableton Link on or off, select your MIDI input/output device, and monitor AbletonOSC connection status.

### Keyboard shortcuts

| Keys | What it does |
|---|---|
| `Shift+Enter` | Send the current code block to the live coding server |
| `Ctrl+Shift+Enter` | Send the entire editor contents |
| `Ctrl+↑` / `Ctrl+↓` | Step through previous commands (last 200) |
| `Tab` | Indent (4 spaces) |

---

## Ableton Link

Link keeps POMSKI's tempo locked to Ableton Live — and anything else on your network that supports Link (Ableton Live, Reason, Traktor, various iOS apps).

```bash
pip install aalink
```

That's it. If aalink is installed POMSKI will connect to Link automatically. You'll see the peer count in the Link pill in the Web UI.

- Change tempo in Ableton → POMSKI follows
- Call `composition.set_bpm(140)` → Ableton follows
- Toggle sync on/off any time from the Prefs tab

---

## AbletonOSC integration

POMSKI can communicate directly with Ableton Live via [AbletonOSC](https://github.com/ideoforms/AbletonOSC), giving you programmatic control over Live's session from Python code or the REPL.

### Setup

1. Install AbletonOSC as a remote script in Ableton (see its README)

The bridge connects automatically once POMSKI starts. Connection status and track count are shown in the Prefs tab.

### Controlling Live from Python

```python
# Transport
live.scene_play(0)
live.track_stop(0)

# Mixer
live.track_volume(0, 0.85)       # track index, value 0.0–1.0
live.track_mute(0, True)

# Clips
live.clip_play(0, 0)             # track, clip slot
live.clip_stop(0, 0)

# Devices
live.device_param(0, 0, 3, 0.5) # track, device, param, value 0–1

# Tempo
live.set_tempo(128.0)

# Subscribe to a Live value — pushes to composition.data automatically
live.watch("track/0/volume")     # → composition.data["live_track_0_volume"]

# Inspect the session
live.tracks                      # list of track names
live.scenes                      # list of scene names
live.connected                   # True if bridge is active
```

### Reading Live state inside patterns

```python
# After calling live.watch("track/0/volume"):
@composition.pattern(channel=0, length=4)
def melody(p):
    vol = p.data.get("live_track_0_volume", 0.8)
    p.seq("60 _ 63 65", velocity=int(vol * 127))
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

## Max for Live device (Coming Soon)

If you use Ableton Live you can add a small MIDI device to any track that shows whether POMSKI is connected and lets you open the Web UI with one click.

The device files are in the project root:
- `subsequence_webui.amxd` — the Max for Live device
- `subsequence_webui.maxpat` — the Max patch source
- `subsequence.js` — the node.script WebSocket connector

**Setup (one time):**
1. In Ableton, drag `subsequence_webui.amxd` onto any MIDI track
2. First time only: click the `node.script` object inside the device and send it the message `script npm install ws`

The device connects automatically when POMSKI is running and reconnects if it drops. You'll see a green LED when it's live and the current BPM ticking alongside it.

---

## API quick reference

### Composition

| Call | What it does |
|---|---|
| `composition.play()` | Start everything — call this last |
| `composition.set_bpm(120)` | Change tempo; syncs to Link if connected |
| `composition.mute("name")` | Silence a pattern by name |
| `composition.unmute("name")` | Bring a pattern back |
| `composition.web_ui()` | Start the browser dashboard (port 8080) |
| `composition.live()` | Start the live coding server (port 5555) |
| `composition.harmony(style, cycle_beats, gravity)` | Set harmonic style and progression speed |
| `composition.form_next()` | Jump to the next section now |
| `composition.form_jump("chorus")` | Jump to a named section |
| `composition.data` | Shared dict for cross-pattern state and Live values |

### Pattern builder (p.)

| Call | What it does |
|---|---|
| `p.note(pitch, beat, velocity, duration)` | Place a single note |
| `p.hit_steps(pitch, steps, velocity)` | Place hits at 16th-note grid positions (0–15) |
| `p.seq("60 _ 62 64", velocity)` | Sonic Pi-style string notation; `_` = rest |
| `p.sequence(steps, pitches, velocity)` | Pair grid positions with a pitch list |
| `p.euclidean(pitch, pulses, steps)` | Euclidean rhythm distribution |
| `p.brownian(start, steps, step_size, pitch_range)` | Random-walk melody |
| `p.lorenz(steps, pitch_range)` | Lorenz attractor → pitch |
| `p.game_of_life(pitch, cols, rows, generations)` | Conway CA → rhythm |
| `p.logistic(steps, r, pitch_range)` | Logistic map chaos |
| `p.gray_scott(pitch, n, f, k)` | Reaction-diffusion → velocity |
| `p.golden_ratio(pitch, count)` | φ-spaced note distribution |
| `p.spectral(harmonics, steps, pitch_range)` | Sum-of-harmonics contour |
| `p.markov(graph, steps, start)` | Markov chain melody |
| `p.from_midi(filepath, track)` | Load notes from a .mid file |
| `p.quantize(key, mode)` | Snap notes to a named scale |
| `p.quantize_m21(key, scale_name)` | Snap notes to any Music21 scale |
| `p.randomize(timing, velocity)` | Add human-feel micro-variation |
| `p.dropout(probability)` | Randomly remove notes each cycle |
| `p.transpose(semitones)` | Shift all notes up/down |
| `p.shift(steps)` | Shift timing by 16th-note steps |
| `p.reverse()` | Flip the pattern backwards |
| `p.velocity_shape(low, high)` | Rescale velocities to a range |
| `p.thin(density, strategy)` | Remove notes by position bias |

### Pattern attributes

| Attribute | Description |
|---|---|
| `p.cycle` | Integer — how many times this pattern has looped |
| `p.bar` | Global bar number at the time this pattern fired |
| `p.rng` | Seeded `random.Random` instance for reproducible randomness |
| `p.data` | Direct reference to `composition.data` |
| `p.section` | Current `SectionInfo` (name, bar, bars) or `None` |

---

## Tutorial

A full interactive tutorial covering philosophy, API reference, step-by-step composition walkthrough, Python primer, and performance tips is included.

Open **http://localhost:8080/tutorial.html** while POMSKI is running, or open `docs/tutorial.html` directly in any browser.

---

## License

AGPL-3.0 — inherited from [subsequence](https://github.com/simonholliday/subsequence). If you run a modified version of POMSKI as a network service, you must make the source available to its users. See the [LICENSE](LICENSE) file for details.
