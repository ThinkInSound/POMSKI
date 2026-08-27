# POMSKI — Claude Code Context

Tracked in Subroutine under project key `POMSKI` (see `.subroutine`). Check `subroutine_changes()`
and `subroutine_list(ready=true)` at the start of a session for open work.

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
| `examples/live_bridge.py` | (in-place) | AbletonOSC + ClyphX bridge (X-OSC needs ClyphX Pro) |
| `examples/pomski_template.py` | (in-place) | Starter template — 16 silent pattern slots |
| `third_party/ClyphX/` | installed to Ableton Remote Scripts on first run | Vendored free ClyphX (LGPL-3.0) |

## Architecture

```
pomski_template.py
  └─ composition.play()          # starts asyncio event loop
       ├─ web_ui (port 8080)     # WebSocket state broadcast every 100ms
       ├─ live_server (port 5555) # REPL — exec() incoming code blocks
       ├─ sequencer              # MIDI clock, pattern scheduling
       │    └─ live_bridge       # AbletonOSC (port 11000/11001) + ClyphX Pro X-OSC (port 7005)
       └─ link-service thread    # daemon — manages aalink_bridge subprocess lifecycle
            └─ aalink_bridge.py  # detached system-Python process; TCP socket on dynamic port
                 └─ aalink.Link  # Ableton Link C++ library (via aalink Python extension)
```

## Ableton Link integration

**This entire section is Windows-only.** aalink.Link() crashes in a PyInstaller frozen Windows
process due to SxS activation context DLL redirection — a Windows-specific mechanism. Workaround:
run aalink in a detached system-Python subprocess (`aalink_bridge.py`) and communicate via a
local TCP socket. The whole `_LinkProxy`/bridge path below is gated behind
`sys.platform == 'win32'` in `pomski_template.py`.

**On macOS**, aalink works fine directly in a frozen process — no bridge needed. `pomski_mac.spec`
bundles aalink into the app directly, and `pomski_template.py`'s own `_start_direct_link()` runs
`aalink.Link` in-process on a daemon thread with its own asyncio loop (aalink needs a *running*
loop, and `composition._main_loop` doesn't exist yet at that point in startup). It wraps the real
Link in `_DirectLinkProxy`, which exposes the same shape web_ui.py's `_get_link_state()` reads off
the Windows `_LinkProxy` (`enabled`/`tempo`/`num_peers` plus `_tempo`/`_num_peers`).

**Neither platform uses `composition.py`'s own aalink init** (`_run()`, line ~1939):
`pomski_template.py` sets `composition._link_thread_running = True` **unconditionally** (not inside
the `win32` branch), which suppresses it everywhere. The `_run()` path is effectively dead code for
anything launched via the template — it only runs for a bare `subsequence` script that never sets
that flag. Dispatch is `if sys.platform == 'win32': <bridge>  else: _start_direct_link()`.

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
- **Drum name strings**: must exactly match a `GM_DRUM_MAP` key (`gm_drums.py`) — there is no `"hh"` shorthand, it's `"hi_hat_closed"`/`"hi_hat_open"`/`"hi_hat_pedal"`. Notes 36–51 (`kick_1` through `ride_1`) cover a standard Ableton Drum Rack's default 16 pads; GM defines percussion 27–87 total. Using a name not in the map raises at note-resolution time, not at pattern-definition time.
- **REPL namespace pre-imports**: `composition`, `subsequence`, `gm_drums`, `random`, `math`, `rich` (from `live_server.py` `_build_namespace`), plus `feeds`, `live`, `pat`, `drums` (from the `pomski_template.py` override). NOTE: `notes`/`midi_notes` are NOT injected — use `subsequence.constants.midi_notes` explicitly
- **Terminal output**: console logging uses `rich.logging.RichHandler` (colour-coded by level); file log (`pomski.log`) stays plain. Console shows INFO+ only (DEBUG → file); `websockets`/`asyncio`/`mido` loggers capped at INFO. Startup banner "POMSKI has started up successfully. Have fun!" prints and browser auto-opens (dev + frozen) once `_web_ui_server` exists — MIDI device prompt happens earlier, at `Composition()` construction
- **Drones**: `p.drone`/`p.drone_off`/`p.note_on`/`p.note_off`/`p.silence` implemented in `pattern_midi.py` via `CcEvent` with `message_type='note_on'/'note_off'` (CcEvent has `note`/`velocity` fields; sequencer tracks them in `active_notes` so stop cleans up)
- **Known-failing tests (pre-existing on clean checkout)**: 4 fail, and the save path is **NOT** broken — that earlier characterisation was wrong. `save_recording()` writes a proper Type-1 file (track 0 = tempo, track 1 = notes), but two tests still read notes out of `mid.tracks[0]` — now the tempo track — so they see 0 notes (`::test_save_recording_creates_valid_midi_file`, `::test_save_recording_delta_ticks_are_correct`). **Stale tests, working feature.** The third (`::test_save_recording_skips_when_not_recording`) is a real, minor gap: `save_recording()` guards only on `if not self.recorded_events`, never on `self.recording`, so it writes a file even when recording is off. The other two save_recording tests pass. Fourth failure is `test_rescheduling.py::test_reschedule_lookahead_validation` (code clamps/warns where test expects raise)
- **BPM ramp**: `composition.target_bpm(bpm, bars, shape)` wraps `sequencer.set_target_bpm()`; web UI `_get_state` reads `sequencer.current_bpm` (live ramp value), not static `comp.bpm`. Link/AbletonOSC peers are NOT ramped — call `set_bpm()` after ramp to propagate
- **Live form fix**: `schedule_form` advance callback is registered unconditionally at startup and reads `composition._form_state` via getter each bar — forms defined/redefined via REPL after `play()` advance correctly (previously only wired if form existed at startup → stuck on first section)
- `composition._is_live` — True after `composition.live()` is called
- `composition._main_loop` — asyncio event loop, set at top of `_run()`
- `composition._running_patterns` — dict of active `_DecoratorPattern` objects
- Hot-swap path: redefine a function with the **same name** as a running slot → replaces builder instantly
- Auto-assign path: new name → finds first empty slot (no steps), steals its channel and name
- Re-run of auto-assigned pattern: matched by `_builder_fn.__name__` so it hot-swaps cleanly
- `p.hit(pitch, beats)` **does** exist (list of beat positions), as does `p.fill(pitch, step)` (fills all beats at a fixed interval)
- `PatternBuilder` **does** accept `data=` (and `tweaks=`, `section=`, `rng=`, `default_grid=`) — see `pattern_builder.py` `__init__`
- LoopBe feedback protection silently mutes — check tray icon if MIDI goes silent

## API quick reference

```python
# ── Place notes ───────────────────────────────────────────────────────────────
p.note(pitch, beat, velocity=100, duration=0.25)     # beat is REQUIRED, no default
p.hit_steps(pitch, steps=[0,4,8,12], velocity=100)   # 16-step grid indices
p.sequence(steps=[0,4,8,12], pitches=[60,62,64,65])
p.seq("60 _ 62 _ 64", velocity=80)                   # Sonic Pi style; space-separated, no commas
p.seq("x [xx] x ?0.6", velocity=80)                  # [..] = subdivision, ?N = per-step probability
p.euclidean("kick_1", pulses=5, velocity=100)         # steps auto-computed from length*4
p.fill(pitch, step=0.25)                              # fills all beats at fixed interval

# ── Chords & melody ───────────────────────────────────────────────────────────
p.chord(chord_obj, root, velocity=90, sustain=False, duration=1.0, inversion=0, count=None, legato=None)
p.strum(chord_obj, root, velocity=90, sustain=False, duration=1.0, inversion=0, count=None, offset=0.05, direction="up", legato=None)
p.arpeggio(pitches, step=0.25, velocity=100, duration=None, direction="up")  # "up","down","up_down","random"
# pitches MUST be a real list ([48,50,55,60]), NOT a Sonic-Pi-style string ("48 50 55 60") —
# arpeggio() does `for p in pitches`, so a string iterates character-by-character and
# _resolve_pitch(' ') throws ValueError on the first space. That notation is p.seq()-only.
p.melody(state, step=0.25, velocity=90, duration=0.2, chord_tones=None)  # Narmour IR melody generator
# `state` is NOT a placeholder — it's a required subsequence.MelodicState(key="C", mode="ionian",
# low=48, high=72, nir_strength=0.5, chord_weight=0.4) instance you construct yourself, ONCE, at
# module level (outside any pattern function). Recreating it inside the pattern wipes its
# melodic memory every rebuild, defeating the point. Passing a plain string/undefined name
# throws NameError or AttributeError, not a helpful "you forgot to construct MelodicState".

# ── Generative rhythm ─────────────────────────────────────────────────────────
p.markov(transitions, pitch_map, velocity=100, duration=0.1, step=0.25, start=None)  # transitions: {state: [(next, weight), ...]}
p.lsystem(pitch_map, axiom, rules, generations=3, step=None, velocity=80, duration=0.2)
p.cellular_1d(pitch, rule=30, generation=None, velocity=60, duration=0.1, no_overlap=False, dropout=0.0, rng=None)   # Rules 30/90/110
p.cellular_2d(pitches, rule="B368/S245", generation=None, velocity=60, duration=0.1, no_overlap=False, dropout=0.0, seed=1, density=0.5, rng=None)
# NOTE: pink_noise is NOT a p.* method — it's sequence_utils.pink_noise(steps, sources=16, seed=0) -> list[float]
p.logistic(steps=16, r=3.9, x0=0.5, pitch_range=(48,72), velocity_range=(60,120), duration=0.25)  # r<3 stable, >3.57 chaotic
p.lorenz(steps=16, pitch_range=(48,72), velocity=80, duration=0.25, s=10.0, r=28.0, b=2.667, dt=0.01)
# s=sigma (Prandtl, reaction speed), r=rho (chaos driver, chaotic above ~24.7), b=beta (geometric factor)
# velocity is ONE value for every note in the call — for per-note modulation, unroll the loop
# yourself (copy the body from pattern_algorithmic.py) and read p.conductor.get() per step
p.gray_scott(pitch=60, n=16, f=0.055, k=0.062, iterations=200, velocity_range=(40,120), duration=0.25)
# n=grid size (= note count), f=feed rate, k=kill rate, iterations=simulation steps before reading the field
p.bresenham_poly(parts, velocity=100, duration=0.1, grid=None, dropout=0.0, no_overlap=False, rng=None)
# parts is a dict: {pitch: density_weight} e.g. {"kick_1": 0.25, "snare_1": 0.125} — each step
# goes to exactly one voice (never overlapping), weights <1.0 leave the remainder as rests.
# velocity can also be a dict ({pitch: velocity}) instead of one int for all voices.
# NOTE: there is no `step` param — that was wrong in this reference; use `grid` instead.
p.ghost_fill(pitch, density=0.3, velocity=35, bias="uniform", no_overlap=True, grid=None, duration=0.1, rng=None)
p.thin(pitch, strategy="strength", amount=0.5, grid=None, rng=None)      # musical inverse of ghost_fill

# ── Modifiers (call after placing notes) ──────────────────────────────────────
p.randomize(timing=0.03, velocity=0.0, rng=None)
p.dropout(probability, rng=None)
p.shift(steps, grid=None)                             # grid: step-grid size steps are measured in; defaults to pattern's grid
p.quantize("C", "dorian")
p.quantize_m21("C", "MelodicMinorScale")              # requires music21; full scale library
# quantize_m21 also takes scala_name=None — pass a Scala tuning filename to use music21's
# bundled Scala archive (3,935 microtonal tuning files) instead of scale_name; scala_name wins
# if both are given
p.transpose(semitones)
p.invert(pivot=60)                                    # invert intervals around a pivot pitch
p.reverse()                                           # reverse note order
p.double_time()                                       # compress notes into first half (2x speed)
p.half_time()                                         # expand notes by 2x (half speed)
p.staccato(ratio=0.5)                                 # shorten durations (also p.legato(ratio=1.0))
p.velocity_shape(low=64, high=127)                    # normalize and spread velocities
p.every(n, action)                                    # conditional action every N cycles
p.swing(amount=57.0, grid=0.25, strength=1.0)         # 50=straight, 57=default, 67=triplet
p.groove(template, strength=1.0)                      # Groove template (or Groove.from_agr(path))

# ── Pitch bend & portamento ───────────────────────────────────────────────────
p.portamento(time=0.15, shape="linear", resolution=1, bend_range=2.0, wrap=True)
p.slide(notes=None, steps=None, time=0.15, shape="linear", resolution=1, bend_range=2.0, wrap=True, extend=True)
# extend defaults to True (this reference previously said False) — extending the preceding
# note's duration to meet the slide target, no retrigger, is the actual 303-style default
p.bend(note, amount, start=0.0, end=1.0, shape="linear", resolution=1)
# `note` is a NOTE INDEX (0=first note placed, -1=last), NOT a MIDI pitch — raises IndexError
# if out of range. `amount` is normalized -1.0..1.0 (not semitones); with the standard ±2
# semitone pitch wheel range, 0.5 = 1 semitone. start/end are fractions of THAT note's own
# duration (0.0=onset, 1.0=note end), not beat positions.

# ── CC & OSC automation ───────────────────────────────────────────────────────
p.cc_ramp(control, start, end, beat_start=0.0, beat_end=None, resolution=1, shape="linear")
p.program_change(program, beat=0.0, bank_msb=None, bank_lsb=None)
p.sysex(data, beat=0)
p.osc(address, *args, beat=0)                         # fire OSC message at beat position
p.osc_ramp(address, start, end, beat_start=0.0, beat_end=None, resolution=4, shape="linear")

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
p.param(name, default=None)
# Reads this pattern's OWN _tweaks dict, NOT composition.data — a separate mechanism entirely.
# Set via composition.tweak(pattern_name, **kwargs) from the REPL; persists across rebuilds
# until composition.clear_tweak(pattern_name, *names) removes it (all tweaks if no names given).
# composition.get_tweaks(pattern_name) reads the current dict back.
p.signal(name)                                        # read conductor LFO/ramp — shorthand for p.conductor.get(name, p.bar*4)
# p.signal() is fixed to beat 0 of the current bar — calling it once and reusing the value for
# every note in the pattern only changes velocity/pitch/etc. per REBUILD (once per `length`
# beats), not per note. For per-note modulation within one pattern call, read the signal at
# each note's own beat instead: p.conductor.get(name, p.bar*4 + beat)

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
composition.freeze(bars)                                      # capture harmony → Progression; bars is REQUIRED, no default
composition.schedule(func, cycle_beats=4)                     # background polling/task loop
# Works when called live from the REPL too (registers directly on the running sequencer) —
# re-calling with the same function replaces its previous registration rather than stacking a
# second one. func can take a `p` param (ScheduleContext): p.cycle is a call counter (0,1,2…),
# so p.cycle * cycle_beats reconstructs the absolute beat for e.g. composition.conductor.get()
# — useful for continuous OSC/device-param automation, which p.osc_ramp() can't do since
# live.device_param() needs fixed leading args (track, device, param) osc_ramp can't carry.
composition.seed(seed)                                        # deterministic RNG
composition.running_patterns                                  # dict of active patterns
composition.data                                              # shared state dict
composition.tweak(pattern_name, **kwargs)                     # set per-pattern override(s), read via p.param()
composition.clear_tweak(pattern_name, *param_names)           # remove tweak(s); no names = clear all for that pattern
composition.get_tweaks(pattern_name)                          # current tweaks dict for a pattern

# ── Conductor signals ─────────────────────────────────────────────────────────
composition.conductor.lfo("name", shape="sine", cycle_beats=4)
composition.conductor.line("name", start_val=0, end_val=1, duration_beats=16, start_beat=0.0, loop=False, shape="linear")
# shapes: "linear","sine","triangle","saw","square","ease_in","ease_out","ease_in_out","s_curve"
# read in pattern: vel = int(p.signal("name") * 80 + 40)

# ── Live bridge (AbletonOSC) ──────────────────────────────────────────────────
live.play()                                    # transport start
live.stop_transport()                          # transport stop
live.set_tempo(128.0)
live.clip_play(track=0, clip=0)
live.clip_stop(track=0, clip=0)
live.track_stop(track=0)                       # stop all clips on a track
live.scene_play(2)
live.track_volume(track=0, value=0.9)          # 0.0-1.0
live.track_pan(track=0, value=0.0)             # -1.0 (left) to 1.0 (right)
live.track_mute(track=1, muted=True)
live.track_send(track=0, send=0, value=0.5)    # send slot index, 0.0-1.0
live.device_param(track=0, device=0, param=3, value=0.7)  # device/param are indices
                                                # in Live's UI order (0-indexed);
                                                # value is ALWAYS 0.0-1.0 normalized —
                                                # AbletonOSC/Live map it to the param's
                                                # real range (Hz, dB, etc), you never
                                                # pass the real-world value
live.watch("track/0/volume")          # pushes to composition.data["live_track_0_volume"]
live.send(address, *args)             # raw OSC — any /live/... path AbletonOSC supports
live.clyphx("action string")          # fire an X-Clip action (see clyphx notes below)
live.tracks                           # list of track names
live.connected                        # bool
```

**Finding device/param indices**: POMSKI has no built-in lookup — AbletonOSC doesn't expose a
name→index query either. Reliable method: right-click the parameter in Live → the Max for Live
LOM path item (e.g. "Copy M4L path") gives something like `live_set tracks 0 devices 0
parameters 28` — those three numbers ARE `track`, `device`, `param` directly, since AbletonOSC
addresses the same Live Object Model tree. This beats counting knobs visually, since LOM
parameter order doesn't always match on-screen layout (chained macros, hidden params, rack
chains can shift it). `track` is the track's position in Live's track list, 0-indexed, matching
`live.tracks[track]`.

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
- **`FormState` NameError**: fixed by adding `from subsequence.form_state import FormState, SectionInfo`.
- **Nested functions in REPL**: defining `def helper()` inside a `@composition.pattern` block causes client disconnect in the live server's exec() context. All ref tab examples use flat code only.
- **New pattern doubling**: fixed — hot-swap now checks `_builder_fn.__name__` so re-running an auto-assigned pattern hot-swaps instead of spawning another slot.
- **Ableton Link peer count always 0**: `_get_link_state` in web_ui.py didn't include `peers`; fixed. `num_peers` is a valid aalink attribute.
- **Link toggle not disconnecting from Ableton**: `_link.enabled = False` in aalink doesn't remove peers reliably. Fixed by closing the TCP connection entirely on disable, which kills the bridge and removes the peer at the network level.
- **aalink bridge not restarting after Ableton toggle**: Windows half-open TCP socket caused `recv()` to block forever. Fixed by `conn.shutdown(SHUT_RDWR)` in the bridge's `finally` block, plus 15s heartbeat detection in `_link_reader_body`.
- **Multiple Ableton Link toggles eventually crash aalink**: aalink fires C++ callbacks without registered handlers. Fixed by registering no-op lambdas via `set_num_peers_callback`, `set_tempo_callback`, `set_start_stop_callback`.
- **BPM changes in POMSKI not reflected in Ableton**: aalink bridge propagation was unreliable. Fixed by also calling `live.set_tempo(bpm)` via AbletonOSC in the web_ui `set_bpm` handler.
- **ClyphX Pro is a paid product, not bundled with Ableton**: `live.clyphx()`/X-Clip triggers previously required ClyphX Pro (nativeKontrol) to be separately purchased and installed — a hard dependency users hit blind on a fresh machine. Fixed by vendoring the free ClyphX fork (`third_party/ClyphX/`, LGPL-3.0, github.com/ldrolez/clyphx-live11) and auto-installing it to Ableton's Remote Scripts folder on first run (`_ensure_clyphx_installed()` in `pomski_template.py`). `clyphx()`/X-Clip triggers (the `"[] ACTION"` clip-name convention) work with the free version — that's a core ClyphX feature, not Pro-exclusive. `clyphx_osc()`/X-OSC (port 7005) genuinely is ClyphX Pro–only; since it's fire-and-forget UDP it can't detect a missing listener, so it now logs a one-time warning instead of silently doing nothing. Users still have to manually add "ClyphX" as a control surface in Ableton Preferences once — the Live API gives no way to automate that step.
- **`composition.schedule()` silently no-op'd when called live from the REPL**: it unconditionally appended to `_pending_scheduled`, a list only ever drained once at `play()` startup — unlike `@composition.pattern`, which has explicit `_is_live` hot-swap/hot-add handling. A user hit this trying to drive continuous `live.device_param()` automation via a scheduled callback registered mid-session. Fixed: `schedule()` now mirrors the pattern decorator's live path — if `_is_live` and the main loop is running, it wraps the callback and registers it directly on the running sequencer via `schedule_callback_repeating()` instead of queuing for a startup pass that already happened.
- **Re-registering a live `composition.schedule()` callback stacked a duplicate instead of replacing it**: the live-add path above had no identity tracking, so re-running `composition.schedule(fn, cycle_beats=...)` with a new interval (e.g. tweaking an automation's speed) left the old repeating callback running alongside the new one — both firing forever after with independent, out-of-sync cycle counters, seen as a live-automated parameter (e.g. `live.device_param`) jittering randomly. Fixed by giving `ScheduledCallback` (sequencer.py) a `cancelled` flag checked in the dispatch loop (lazy-delete, not re-queued once set) and having `Composition._live_scheduled` track the active callback per function name, cancelling the previous one before registering a new one under the same name — same idea as pattern hot-swap keying off `_builder_fn.__name__`.
- **Pattern-rebuild errors flooded the log**: a broken pattern re-raises every rebuild cycle, and `push_builder_error()` pushed a fresh full traceback each time with no dedup — worse, a runaway value inside the pattern (e.g. a string being concatenated onto itself every cycle) makes the message text different every time, so naive exact-string dedup wouldn't have caught it either. Fixed in `web_ui.py`: dedup key is exception type + traceback frames (excluding the final message text), cleared once the pattern rebuilds clean again, and truncated past 4000 chars regardless.

## Web UI notes

- Patterns tab shows all unique pitches as pills; currently playing notes get white outline
- MIDI activity monitor in Signals tab
- Quick command box: plain text → REPL exec (the old `cx:` → ClyphX Pro routing was removed client-side; `cx:` is now just tolerated/stripped if pasted from old muscle memory, see index.html)
- Ref tab has working copy-to-editor examples for euclidean, markov, Lorenz, Gray-Scott, etc.

## Distribution build pipeline

**macOS** (`pomski_mac.spec`, repo root) — single step, no bridge needed (aalink bundled directly):

```
pyinstaller pomski_mac.spec -y --clean   # → dist/POMSKI.app
```

**Windows** — build order matters, `aalink_bridge.spec` must run before `pomski.spec`:

```
pyinstaller aalink_bridge.spec          # → dist/aalink_bridge.exe
pyinstaller pomski.spec -y --clean      # → dist/POMSKI/  (bundles bridge exe)
iscc pomski_installer.iss               # → Output/POMSKI_Setup.exe
```

All three files live at **repo root**. They must stay there: every spec does
`ROOT = Path(SPECPATH)` (the spec's *own* directory) and the `.iss` uses paths relative to itself
(`favicon.ico`, `OutputDir=Output`, `SourceDir=dist\POMSKI`). They were previously moved into
`pomski_docs/`, which silently broke every one of those paths — nothing errors at rest, the build
just fails on a fresh checkout. Don't relocate them without rewriting the paths inside.

`aalink_bridge.spec` was missing from the repo entirely until it was reconstructed — `pomski.spec`
depended on an artifact nothing in version control could produce, so the Windows pipeline was not
reproducible from a clean clone. Smoke-tested on macOS (frozen bridge connects back, completes the
READY handshake, streams live tempo), which validates the spec logic and that aalink bundles into a
frozen onefile correctly. The Windows-specific SxS/DLL behaviour it exists to work around is, by
definition, only testable on Windows.

| File | Purpose |
|------|---------|
| `aalink_bridge.spec` | Bridge exe — standalone onefile, aalink bundled (Windows only) |
| `pomski.spec` | Windows main exe — icon embedded, bridge exe bundled via datas, aalink EXCLUDED |
| `pomski_installer.iss` | Inno Setup installer script (Windows) |
| `pomski_mac.spec` | macOS app bundle — aalink direct, no bridge |
| `favicon.ico` | Multi-size ICO (16/32/48/64/128/256px), Windows |

**Windows installer notes:**
- Installs to `Program Files\POMSKI`, requires admin/UAC
- Logs written to `%LOCALAPPDATA%\POMSKI\` at runtime (Program Files is read-only)
- `[Code]` Pascal block calls `SHChangeNotify` post-install to force shell icon cache refresh
- `{userdesktop}` + `UsedUserAreasWarning=no` required for correct desktop shortcut with admin install
- Web favicon embedded as base64 data URI in `index.html`
- `aalink_bridge.exe` lives in `_internal/` inside the POMSKI dist folder

**macOS notes:**
- Logs written to `~/Library/Logs/POMSKI/`
- Requires Apple Developer signing + notarization for distribution without a Gatekeeper warning
  (see `pomski_docs/CLAUDE_MAC.md` for the codesign/notarytool commands — that file predates the
  actual mac port and its own "create pomski_mac.spec" section is superseded by the real one at
  repo root, but its signing/notarization/itch.io steps are still the only place those are written down)

## Ports

| Service | Port |
|---------|------|
| Web UI HTTP | 8080 |
| Web UI WebSocket | 8765 |
| REPL (live_server) | 5555 |
| AbletonOSC listens | 11000 |
| AbletonOSC replies | 11001 |
| ClyphX Pro OSC (X-OSC only, not free ClyphX) | 7005 |
