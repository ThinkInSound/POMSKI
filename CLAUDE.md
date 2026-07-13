# POMSKI — Claude Code Context

## What this project is
POMSKI is a live-coding music environment built on top of **subsequence** (AGPL-3.0).
It adds a web UI, Ableton Live bridge, and REPL live-coding workflow on top of subsequence's
pattern sequencer. The user live-codes patterns from a browser at `http://localhost:8080`.

## File map

| File | Install path | Purpose |
|------|-------------|---------|
| `subsequence/composition.py` | (in-place) | Core — patterns, live hot-swap, scheduler |
| `subsequence/web_ui.py` | (in-place) | WebSocket broadcast loop, MIDI hook, state |
| `subsequence/assets/web/index.html` | (in-place) | Full browser UI (editor, log, patterns, signals, refs) |
| `examples/live_bridge.py` | (in-place) | AbletonOSC + ClyphX Pro bridge |
| `examples/pomski_template.py` | (in-place) | Starter template — 16 silent pattern slots |

## Architecture

```
pomski_template.py
  └─ composition.play()          # starts asyncio event loop
       ├─ web_ui (port 8080)     # WebSocket state broadcast every 100ms
       ├─ live_server (port 5555) # REPL — exec() incoming code blocks
       ├─ sequencer              # MIDI clock, pattern scheduling
       │    └─ live_bridge       # AbletonOSC (port 11000/11001) + ClyphX (port 7005)
       └─ link-service thread    # daemon — manages aalink_bridge subprocess lifecycle
            └─ aalink_bridge.py  # detached system-Python process; TCP socket on dynamic port
                 └─ aalink.Link  # Ableton Link C++ library (via aalink Python extension)
```

## Ableton Link integration

aalink.Link() crashes in a PyInstaller frozen process due to SxS activation context DLL
redirection. Workaround: run aalink in a detached system-Python subprocess (`aalink_bridge.py`)
and communicate via a local TCP socket.

**Key classes/objects in `pomski_template.py`:**

- `_LinkProxy` — stands in for `aalink.Link` in the main process. Exposes `enabled`, `tempo`,
  `num_peers`. Lives at `composition._link`.
- `_run_event` (threading.Event) — controls whether `_link_service` is allowed to reconnect.
  Cleared when user disables Link; set when user enables Link.
- `_link_service` (daemon thread) — connect → read → auto-restart loop. Calls
  `_run_event.wait()` before each reconnect, so it blocks cleanly when Link is disabled.
- `_connect_bridge()` — spawns `aalink_bridge.py`, opens a server socket, waits for READY,
  sets `proxy._enabled = True` then `proxy._conn`.
- `_link_reader_body()` — reads T/P lines from bridge; 2s socket timeout + 15s heartbeat check.

**Toggle off behaviour:** `_LinkProxy.enabled = False` clears `_run_event`, sets `_conn = None`,
and shuts down the TCP socket. This kills the bridge connection immediately, causing Ableton to
lose the peer at the TCP layer. `_link_service` blocks on `_run_event.wait()` and does not
reconnect until re-enabled.

**Bridge protocol (text lines):**
- `T<bpm>\n` — tempo (bidirectional)
- `P<n>\n` — peer count (bridge → POMSKI only)
- `READY\n` — sent once by bridge after Link initialises (bridge → POMSKI)

**BPM sync (POMSKI → Ableton):** `composition.set_bpm()` calls `_link_proxy.tempo = bpm`
(sends T to bridge via TCP) AND `web_ui.py` also calls `live.set_tempo(bpm)` via AbletonOSC
for immediate, reliable delivery.

## Key facts

- **License**: AGPL-3.0
- **MIDI channels**: 0-indexed. `channel=0` = MIDI ch 1, `channel=9` = drums
- **REPL drum aliases**: `drums` = `gm_drums.GM_DRUM_MAP`; `pat` wrapper routes a positional dict to `drum_note_map`, so `@pat(9, 4, drums)` works (defined in `pomski_template.py` namespace override)
- **REPL namespace pre-imports**: `random`, `math`, `rich` available by default (see `live_server.py` `_build_namespace`)
- **Terminal output**: console logging uses `rich.logging.RichHandler` (colour-coded by level); file log (`pomski.log`) stays plain. Console shows INFO+ only (DEBUG → file); `websockets`/`asyncio`/`mido` loggers capped at INFO. Startup banner "POMSKI has started up successfully. Have fun!" prints and browser auto-opens (dev + frozen) once `_web_ui_server` exists — MIDI device prompt happens earlier, at `Composition()` construction
- **Drones**: `p.drone`/`p.drone_off`/`p.note_on`/`p.note_off`/`p.silence` implemented in `pattern_midi.py` via `CcEvent` with `message_type='note_on'/'note_off'` (CcEvent has `note`/`velocity` fields; sequencer tracks them in `active_notes` so stop cleans up)
- **Known-failing tests (pre-existing on clean checkout)**: all three `test_midi_recording.py::test_save_recording_*` tests (save path broken) and `test_rescheduling.py::test_reschedule_lookahead_validation` (code clamps/warns where test expects raise)
- **BPM ramp**: `composition.target_bpm(bpm, bars, shape)` wraps `sequencer.set_target_bpm()`; web UI `_get_state` reads `sequencer.current_bpm` (live ramp value), not static `comp.bpm`. Link/AbletonOSC peers are NOT ramped — call `set_bpm()` after ramp to propagate
- **Live form fix**: `schedule_form` advance callback is registered unconditionally at startup and reads `composition._form_state` via getter each bar — forms defined/redefined via REPL after `play()` advance correctly (previously only wired if form existed at startup → stuck on first section)
- `composition._is_live` — True after `composition.live()` is called
- `composition._main_loop` — asyncio event loop, set at top of `_run()`
- `composition._running_patterns` — dict of active `_DecoratorPattern` objects
- Hot-swap path: redefine a function with the **same name** as a running slot → replaces builder instantly
- Auto-assign path: new name → finds first empty slot (no steps), steals its channel and name
- Re-run of auto-assigned pattern: matched by `_builder_fn.__name__` so it hot-swaps cleanly
- `p.hit()` does **NOT** exist in the API; `p.fill(pitch, step)` **does** exist (fills all beats at a fixed interval)
- `PatternBuilder` has no `data=` kwarg
- LoopBe feedback protection silently mutes — check tray icon if MIDI goes silent

## API quick reference

```python
# ── Place notes ───────────────────────────────────────────────────────────────
p.note(pitch, beat=0, velocity=100, duration=0.5)
p.hit_steps(pitch, steps=[0,4,8,12], velocity=100)   # 16-step grid indices
p.sequence(steps=[0,4,8,12], pitches=[60,62,64,65])
p.seq("60 _ 62 _ 64", velocity=80)                   # Sonic Pi style; space-separated, no commas
p.seq("x [xx] x ?0.6", velocity=80)                  # [..] = subdivision, ?N = per-step probability
p.euclidean("kick_1", pulses=5, velocity=100)         # steps auto-computed from length*4
p.fill(pitch, step=0.25)                              # fills all beats at fixed interval

# ── Chords & melody ───────────────────────────────────────────────────────────
p.chord(chord, root, velocity=80, sustain=1.0, inversion=0, voice_leading=False)
p.strum(chord, root, velocity=80, offset=0.03, direction="up", sustain=1.0)
p.arpeggio(pitches, step=0.25, velocity=80, direction="up")  # "up","down","up_down","random"
p.melody(state, count=8, probability_gate=1.0)        # Narmour IR cognitive melody generator

# ── Generative rhythm ─────────────────────────────────────────────────────────
p.markov(options, rng=None)                           # Markov-chain note/rhythm generation
p.lsystem(axiom, rules, generations=3, step=0.25, velocity=80)
p.cellular_1d(rule=30, generation=0, step=0.25, velocity=80)   # Rules 30/90/110
p.cellular_2d(rows=4, cols=16, rule="B3/S23", generation=0, step=0.25, velocity=80)
p.pink_noise(steps=16, sources=16, pitch_range=(48,72), seed=p.bar)   # Voss-McCartney 1/f noise
p.logistic(steps=16, r=3.9, pitch_range=(48,72))               # chaos: r<3=stable, r>3.57=chaos
p.bresenham_poly(parts, step=0.25, velocity=80)                # interlocking multi-voice grid
p.ghost_fill(density=0.3, bias="sixteenths", step=0.25, velocity=40)  # probabilistic ghost notes
p.thin(step=0.25, velocity=80)                                 # musical inverse of ghost_fill

# ── Modifiers (call after placing notes) ──────────────────────────────────────
p.randomize(timing=0.03, velocity=0.05)
p.dropout(0.2)
p.shift(steps)
p.quantize("C", "dorian")
p.quantize_m21("C", "MelodicMinorScale")              # requires music21; full scale library
p.transpose(semitones)
p.invert()                                            # invert intervals around center note
p.reverse()                                           # reverse note order
p.double_time()                                       # compress notes into first half (2x speed)
p.half_time()                                         # expand notes by 2x (half speed)
p.staccato(fraction=0.5)                              # shorten durations
p.velocity_shape(low=40, high=100)                    # normalize and spread velocities
p.every(n, action)                                    # conditional action every N cycles
p.swing(amount=0.1, grid=0.25, strength=1.0)          # apply swing timing
p.groove(groove, strength=1.0)                        # Groove template (or Groove.from_agr(path))

# ── Pitch bend & portamento ───────────────────────────────────────────────────
p.portamento(time=0.1, shape="ease_in_out", resolution=8, bend_range=2.0)
p.slide(notes=None, steps=None, time=0.15, shape="linear", bend_range=2.0, extend=False)
p.bend(note=0, amount=0.5, start=0.0, end=1.0, shape="linear", resolution=8)

# ── CC & OSC automation ───────────────────────────────────────────────────────
p.cc_ramp(cc, start, end, beat_start=0, beat_end=None, resolution=8, shape="linear")
p.program_change(patch, bank_msb=None, bank_lsb=None, beat=0)
p.sysex(data, beat=0)
p.osc(address, *args, beat=0)                         # fire OSC message at beat position
p.osc_ramp(address, start, end, beat_start=0, beat_end=None, resolution=8, shape="linear")

# ── Drone / sustained notes ───────────────────────────────────────────────────
p.drone(pitch, beat=0, velocity=100)                  # note_on with no auto note_off
p.drone_off(pitch, beat=0)                            # stop a drone
p.note_on(pitch, beat=0, velocity=100)                # raw note_on (no counterpart)
p.note_off(pitch, beat=0)                             # raw note_off
p.silence(beat=0)                                     # CC 123 + CC 120 (all notes/sounds off)

# ── Pattern context (read-only in builder fn) ─────────────────────────────────
p.bar          # global bar count since playback started (int)
p.cycle        # current loop/cycle count, 0-indexed
p.rng          # seeded random.Random instance (deterministic when composition.seed() set)
p.param(key, default)                                 # read tweakable param from composition.data
p.signal(name)                                        # read conductor LFO/ramp at current bar

# p.section properties (None when no form() active)
p.section.name          # "verse", "chorus", etc.
p.section.bar           # bar within current section (1-indexed)
p.section.bars          # total bars in section
p.section.progress      # 0.0–1.0
p.section.first_bar     # bool — True on first bar of section
p.section.last_bar      # bool — True on last bar of section
p.section.next_section  # name of next section, or None

# ── Composition REPL commands ─────────────────────────────────────────────────
composition.mute("ch1")
composition.unmute("ch1")
composition.target_bpm(bpm, bars=4, shape="ease_in_out")      # smooth BPM ramp
composition.form_next(section_name)                           # override next section
composition.form_jump(section_name)                           # jump immediately
composition.freeze(bars=4)                                    # capture harmony → Progression
composition.schedule(func, cycle_beats=4)                     # background polling/task loop
composition.seed(seed)                                        # deterministic RNG
composition.running_patterns                                  # dict of active patterns
composition.data                                              # shared state dict

# ── Conductor signals ─────────────────────────────────────────────────────────
composition.conductor.lfo("name", shape="sine", cycle_beats=4)
composition.conductor.line("name", start_val=0, end_val=1, duration_beats=16, shape="linear")
# shapes: "linear","sine","triangle","saw","square","ease_in","ease_out","ease_in_out","s_curve"
# read in pattern: vel = int(p.signal("name") * 80 + 40)

# ── Live bridge (AbletonOSC) ──────────────────────────────────────────────────
live.clip_play(track=0, clip=0)
live.scene_play(2)
live.track_volume(0, 0.9)
live.track_mute(1, True)
live.device_param(0, 0, 3, 0.7)
live.set_tempo(128.0)
live.watch("track/0/volume")          # pushes to composition.data["live_track_0_volume"]
live.tracks                           # list of track names
live.connected                        # bool
```

## Template pattern slots

`pomski_template.py` defines 16 silent slots `ch1`–`ch16` on channels 0–15.
Redefine any slot by name to hot-swap it:

```python
@composition.pattern(channel=0, length=4)
def ch1(p):
    p.note(60, beat=0)
    p.note(64, beat=1)
    p.note(67, beat=2)
```

Or use any function name — it auto-assigns to the first empty slot:

```python
@composition.pattern(channel=0, length=4)
def melody(p):                        # → replaces ch1 (first empty slot)
    for i,v in enumerate([1,0,0,1,0,0,1,0,0,1,0,0,1,0,0,0]):
        if v: p.note(60, beat=i*0.25)
```

## Known issues & fixed bugs

- **Python 3.14 incompatibility**: `python-rtmidi` 1.5.8 (latest) does not support Python 3.14 — removed C API functions (`PyEval_CallObject`) cause compile-time failures. **POMSKI requires Python 3.10–3.13.** Workaround: use Python 3.13 or earlier. The upstream `python-rtmidi` project is tracking 3.14 support; monitor [their GitHub repo](https://github.com/SpotlightKid/python-rtmidi/) for updates. See [PomskiREADME.md](PomskiREADME.md#troubleshooting) troubleshooting section for install help.
- **aalink / Link import**: removed from composition.py — the aalink C extension crashes the Windows ProactorEventLoop when concurrent coroutines run. `link()` still works via `subsequence.link_clock.LinkClock` (untouched).
- **`subsequence.link_clock` import**: module does not exist at top-level — removed stray import.
- **`FormState` NameError**: fixed by adding `from subsequence.form_state import FormState, SectionInfo`.
- **Nested functions in REPL**: defining `def helper()` inside a `@composition.pattern` block causes client disconnect in the live server's exec() context. All ref tab examples use flat code only.
- **New pattern doubling**: fixed — hot-swap now checks `_builder_fn.__name__` so re-running an auto-assigned pattern hot-swaps instead of spawning another slot.
- **Ableton Link peer count always 0**: `_get_link_state` in web_ui.py didn't include `peers`; fixed. `num_peers` is a valid aalink attribute.
- **Link toggle not disconnecting from Ableton**: `_link.enabled = False` in aalink doesn't remove peers reliably. Fixed by closing the TCP connection entirely on disable, which kills the bridge and removes the peer at the network level.
- **aalink bridge not restarting after Ableton toggle**: Windows half-open TCP socket caused `recv()` to block forever. Fixed by `conn.shutdown(SHUT_RDWR)` in the bridge's `finally` block, plus 15s heartbeat detection in `_link_reader_body`.
- **Multiple Ableton Link toggles eventually crash aalink**: aalink fires C++ callbacks without registered handlers. Fixed by registering no-op lambdas via `set_num_peers_callback`, `set_tempo_callback`, `set_start_stop_callback`.
- **BPM changes in POMSKI not reflected in Ableton**: aalink bridge propagation was unreliable. Fixed by also calling `live.set_tempo(bpm)` via AbletonOSC in the web_ui `set_bpm` handler.

## Web UI notes

- Patterns tab shows all unique pitches as pills; currently playing notes get white outline
- MIDI activity monitor in Signals tab
- Quick command box: prefix `cx:` → ClyphX Pro, plain text → REPL exec
- Ref tab has working copy-to-editor examples for euclidean, markov, Lorenz, Gray-Scott, etc.

## Distribution build pipeline

Build order matters — `aalink_bridge.spec` must run before `pomski.spec`:

```
pyinstaller aalink_bridge.spec          # → dist/aalink_bridge.exe
pyinstaller pomski.spec -y --clean      # → dist/POMSKI/  (bundles bridge exe)
iscc pomski_installer.iss               # → Output/POMSKI_Setup.exe
```

| File | Purpose |
|------|---------|
| `aalink_bridge.spec` | Bridge exe — standalone onefile, aalink included |
| `pomski.spec` | Main exe — icon embedded, bridge exe bundled via datas |
| `pomski_installer.iss` | Inno Setup installer script |
| `favicon.ico` | Multi-size ICO (16/32/48/64/128/256px) |

**Installer notes:**
- Installs to `Program Files\POMSKI`, requires admin/UAC
- Logs written to `%LOCALAPPDATA%\POMSKI\` at runtime (Program Files is read-only)
- `[Code]` Pascal block calls `SHChangeNotify` post-install to force shell icon cache refresh
- `{userdesktop}` + `UsedUserAreasWarning=no` required for correct desktop shortcut with admin install
- Web favicon embedded as base64 data URI in `index.html`
- `aalink_bridge.exe` lives in `_internal/` inside the POMSKI dist folder

## Ports

| Service | Port |
|---------|------|
| Web UI (WebSocket + HTTP) | 8080 |
| REPL (live_server) | 5555 |
| AbletonOSC listens | 11000 |
| AbletonOSC replies | 11001 |
| ClyphX Pro OSC | 7005 |
