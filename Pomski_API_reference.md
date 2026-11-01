# POMSKI API Reference

POMSKI is a live-coding music environment. Write Python patterns in the browser at
`http://localhost:8080` and they play back as MIDI in real time.

---

## Table of Contents

1. [Setup & REPL](#setup--repl)
2. [Composition](#composition)
   - [Playback control](#playback-control)
   - [Startup & lifecycle](#startup--lifecycle)
   - [Harmony](#harmony)
   - [Song structure (form)](#song-structure-form)
   - [Scheduling](#scheduling)
3. [PatternBuilder (`p`)](#patternbuilder-p)
   - [Note placement](#note-placement)
   - [Rhythmic generators](#rhythmic-generators)
   - [Algorithmic & generative](#algorithmic--generative)
   - [Transformations](#transformations)
   - [music21 scales (`quantize_m21`, `microtuning`)](#music21-scales-quantize_m21)
   - [Timing & feel](#timing--feel)
   - [Utilities](#utilities)
4. [Conductor & signals](#conductor--signals)
5. [MIDI messages & automation](#midi-messages--automation)
6. [LiveBridge (`live`)](#livebridgelive)
7. [DataFeeds (`feeds`)](#datafeedsfeeds)
8. [Duration constants (`dur`)](#duration-constants-dur)
9. [GM Drum Map](#gm-drum-map)
10. [REPL Quick Reference](#repl-quick-reference)
11. [Ports](#ports)

---

## Setup & REPL

POMSKI starts from `pomski_template.py`. Once running:

- Browser UI: `http://localhost:8080`
- REPL port: `5555` (plain TCP, newline-terminated code blocks)
- Quick command box in the UI: type code and press Enter to exec

The following objects are pre-wired into the REPL namespace:

| Name | Type | Description |
|------|------|-------------|
| `composition` | `Composition` | Global controller (clock, patterns, harmony) |
| `live` | `LiveBridge` | Ableton Live bridge via AbletonOSC |
| `feeds` | `DataFeeds` | HTTP polling feeds that write into `composition.data` |
| `pat` | shorthand | Alias for `composition.pattern` — write `@pat(channel)` instead of `@composition.pattern(channel=…, length=4)` |

---

## Composition

`composition` is the top-level controller. It manages the clock, harmony, song structure,
and all MIDI patterns.

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `composition.bpm` | `float` | Current tempo |
| `composition.key` | `str `| None` | Root key (e.g. `"C"`, `"F#"`, `"Bb"`) |
| `composition.data` | `dict` | Shared live data store — patterns read; feeds/OSC write |
| `composition.running_patterns` | `dict[str, Pattern]` | Active patterns keyed by name |
| `composition.sequencer` | `Sequencer` | Underlying beat clock |
| `composition.conductor` | `Conductor` | Time-varying signal engine |
| `composition._is_live` | `bool` | `True` after `composition.live()` is called |
| `composition._main_loop` | `asyncio.EventLoop` | The asyncio loop |

### Pattern registration

```python
@composition.pattern(channel=0, length=4)
def ch1(p):
    p.note(60, beat=0)
```

**`composition.pattern(channel, length=4, unit=None, drum_note_map=None, reschedule_lookahead=1, voice_leading=False)`**

| Parameter | Description |
|-----------|-------------|
| `channel` | MIDI channel, 0-indexed (0–15). Channel 9 = GM drums. |
| `length` | Pattern length in beats (default 4). When `unit` is set, this is a note count. |
| `unit` | Duration of one step in beats (e.g. `dur.SIXTEENTH`). Sets `length` as a count and makes it the grid size. **The total beat length (`length × unit`) must be > 1 beat** (the default reschedule lookahead). Minimum useful unit is `0.25` (`dur.SIXTEENTH`). |
| `drum_note_map` | Dict of `{"name": midi_note}`. Pass `GM_DRUM_MAP` for standard GM names. |
| `voice_leading` | If `True`, chord inversions minimize voice movement automatically. |

**`pat` shorthand:** `pat` is pre-loaded as an alias for `composition.pattern`. Both forms are equivalent:

```python
# Full form
@composition.pattern(channel=0, length=4)
def ch1(p):
    p.note(60, beat=0)

# Short form — channel is positional, length defaults to 4
@pat(0)
def ch1(p):
    p.note(60, beat=0)

@pat(0, 8)          # channel 0, 8-beat pattern
def ch1(p):
    p.note(60, beat=0)
```

**Hot-swap:** Redefine any function with the same name while running to replace it on the next cycle.

```python
# Auto-assign: new name → first empty slot
@composition.pattern(channel=0, length=4)
def melody(p):
    p.note(60, beat=0)

# Hot-swap: same name → replaces in place
@composition.pattern(channel=0, length=4)
def melody(p):
    p.note(67, beat=0)
```

### Playback control

```python
composition.mute("ch1")          # Silence a pattern (keeps cycling)
composition.unmute("ch1")        # Resume
composition.set_bpm(128.0)       # Change tempo immediately
composition.live_info()          # Returns dict: bpm, key, bar, section, chord, patterns, data
```

**`composition.target_bpm(bpm, bars=4, shape="ease_in_out")`**

Ramp the tempo smoothly instead of jumping. The sequencer interpolates every pulse.

```python
composition.target_bpm(140, bars=8, shape="ease_in_out")
```

> Ableton Link and AbletonOSC peers are **not** ramped — they only receive the final value.
> Call `composition.set_bpm(140)` afterwards to bring them in line.

Easing shapes: `"linear"`, `"ease_in"`, `"ease_out"`, `"ease_in_out"`, `"exponential"`,
`"logarithmic"`, `"s_curve"`.

### Startup & lifecycle

These are called once, in the template, before playback begins.

| Call | What it does |
|---|---|
| `composition.play()` | Start everything. **Blocks** until interrupted — call it last. |
| `composition.live(port=5555)` | Start the live-coding REPL server. |
| `composition.web_ui()` | Enable the browser/native dashboard on port 8080. |
| `composition.seed(value)` | Fix the RNG for identical playback every run. |
| `composition.display(enabled=True, grid=False, grid_scale=1.0)` | Terminal dashboard. |
| `composition.hotkeys(enabled=True)` | Enable the global hotkey listener (before `play()`). |
| `composition.hotkey(key, action, quantize=0, label=None)` | Bind a single key to an action. |
| `composition.midi_input(device, clock_follow=False)` | Take MIDI in; optionally slave the clock. |
| `composition.clock_output(enabled=True)` | Act as MIDI clock master. |
| `composition.osc(receive_port=9000, send_port=9001, send_host="127.0.0.1")` | Enable OSC in/out. |
| `composition.cc_map(cc, key, channel=None, min_val=0.0, max_val=1.0)` | Route an incoming CC into `composition.data[key]`. |
| `composition.on_event(event_name, callback)` | Hook a sequencer event — `"bar"`, `"start"`, `"stop"`. |

**`composition.render(bars=None, filename="render.mid", max_minutes=60.0)`**

Render to a MIDI file as fast as possible, with no real-time playback.

```python
composition.render(bars=32, filename="sketch.mid")
```

**`composition.layer(*builder_fns, channel, length=4, unit=None, drum_note_map=None, ...)`**

Combine several builder functions into one pattern on a single channel — useful for
composing a part out of reusable pieces.

### Tweaks — live parameter injection

```python
# Inside a pattern, declare a tweakable parameter:
@composition.pattern(channel=0, length=4)
def bass(p):
    pitches = p.param("pitches", [48, 52, 55])
    p.sequence(steps=[0, 4, 8, 12], pitches=pitches)

# From the REPL, override it:
composition.tweak("bass", pitches=[36, 40, 43])

# Remove:
composition.clear_tweak("bass", "pitches")   # remove one param
composition.clear_tweak("bass")              # remove all tweaks

# Inspect:
composition.get_tweaks("bass")               # returns current tweaks dict
```

### Harmony

Requires `key` to be set at construction. The harmony engine uses a weighted chord
transition graph to generate progressions.

```python
composition.harmony(
    style="functional_major",  # harmony style — see list below
    cycle_beats=4,             # beats per chord change
    gravity=1.0,               # 0.0 = wander freely, 1.0 = stay near tonic
    nir_strength=0.5,          # melodic inertia (Narmour model)
    dominant_7th=True,         # include V7 chords
)
```

**Harmony styles:**

| Style | Character |
|-------|-----------|
| `functional_major` / `diatonic_major` | Standard major key progressions |
| `turnaround` | Jazz turnaround patterns |
| `aeolian_minor` | Natural minor |
| `dorian_minor` | Minor with raised 6th |
| `phrygian_minor` | Minor with flattened 2nd |
| `lydian_major` | Major with raised 4th |
| `mixolydian` | Major with flattened 7th |
| `chromatic_mediant` | Chromatic third relationships |
| `suspended` | Sus2/Sus4 dominant movement |
| `whole_tone` | Whole tone scale movement |
| `diminished` | Diminished chord movement |

**Using the current chord in a pattern:**

```python
@composition.pattern(channel=1, length=4, voice_leading=True)
def pads(p, chord):
    p.chord(chord, root=60, velocity=80, sustain=True)
```

The `chord` parameter is injected automatically when the function signature includes it.

### Song structure (form)

```python
composition.form([
    ("intro",  4),
    ("verse",  8),
    ("chorus", 8),
    ("bridge", 4),
    ("chorus", 16),
])

# Use section name inside patterns:
@composition.pattern(channel=1, length=4)
def melody(p):
    if p.section and p.section.name == "chorus":
        p.note(72, beat=0)
    else:
        p.note(67, beat=0)
```

`p.section` attributes: `.name`, `.bar` (bar within section), `.bars` (total bars), `.progress` (0.0–1.0),
`.first_bar` / `.last_bar` (bool), `.next_section` (name or `None`).

**Navigating the form live**

```python
composition.form_next("chorus")   # queue it — takes effect when this section ends
composition.form_jump("chorus")   # cut to it immediately
composition.form_state            # property — the active FormState, or None
```

**Freezing harmony into a fixed progression**

`composition.freeze(bars)` runs the harmony engine forward and captures the chords it
produces, returning a reusable `Progression`. Bind it to a section so that section plays
the same changes every time.

```python
verse_prog = composition.freeze(8)
composition.section_chords("verse", verse_prog)
```

### Scheduling

```python
# Run a function every 4 beats
composition.schedule(my_fn, cycle_beats=4)

# Run once at startup (populates composition.data before patterns build), then every 16 beats
composition.schedule(my_fn, cycle_beats=16, wait_for_initial=True)
```

---

## PatternBuilder (`p`)

`p` is passed to every pattern function. It is the composer's palette — use it to place
notes and apply transformations.

### Context attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `p.cycle` | `int` | How many times this pattern has rebuilt (0-indexed) |
| `p.bar` | `int` | Global bar counter |
| `p.grid` | `int` | Grid slots in this pattern (e.g. 16 for a 4-beat pattern) |
| `p.section` | `SectionInfo \| None` | Current form section |
| `p.rng` | `random.Random` | Seeded RNG (deterministic if `composition.seed` is set) |
| `p.data` | `dict` | Alias for `composition.data` |
| `p.conductor` | `Conductor` | Time-varying signal source (alias: `p.c`) |

---

### Note placement

**`p.note(pitch, beat, velocity=100, duration=0.25)`**

Place a single MIDI note. `beat` is required — there is no default position.

```python
p.note(60, beat=0)                             # Middle C on beat 1
p.note(60, beat=0, velocity=110, duration=0.5)
p.note("kick_1", beat=0)                       # Drum name (requires drum_note_map)
p.note(67, beat=-0.5)                          # Negative = from end of pattern
```

| Parameter | Description |
|-----------|-------------|
| `pitch` | MIDI note number (0–127) or drum name string |
| `beat` | Beat position (0.0 = bar start). Negative values wrap from end. |
| `velocity` | MIDI velocity (0–127, default 100) |
| `duration` | Note length in beats (default 0.25 = 16th note) |

---

**`p.hit(pitch, beats, velocity=100, duration=0.1)`**

Place the same pitch at multiple beat positions.

```python
p.hit("snare_1", [1, 3])   # standard backbeat
```

---

**`p.hit_steps(pitch, steps, velocity=100, duration=0.1, grid=None, probability=1.0)`**

Place hits at grid step indices (0-indexed).

```python
p.hit_steps("kick_1", [0, 8])                          # beats 1 and 3
p.hit_steps("hi_hat_closed", range(16))               # every 16th note
p.hit_steps("hi_hat_closed", range(16), probability=0.8)  # 80% chance each
```

Default grid = `p.grid` (16 for a 4-beat pattern with 16th-note resolution).

---

**`p.sequence(steps, pitches, velocities=100, durations=0.1, grid=None, probability=1.0)`**

Multi-parameter step sequencer. Steps through a list of pitches as it fires.

```python
p.sequence(steps=[0, 4, 8, 12], pitches=[60, 62, 64, 65])
p.sequence(steps=[0, 4, 8, 12], pitches=60)              # same pitch all steps
p.sequence(steps=[0, 4, 8, 12],
           pitches=[60, 62, 64, 65],
           velocities=[100, 80, 100, 80],
           durations=0.25)
```

---

**`p.seq(notation, pitch=None, velocity=100)`**

Mini-notation string sequencer. Events are distributed evenly across the pattern length.

```python
p.seq("kick_1 . [kick_1 kick_1] .")    # kick with 16th subdivision
p.seq("60 [62 64] 67 60")              # melody
p.seq(". snare_1?0.5 . snare_1")       # 50% probability ghost note
p.seq("x x x x", pitch=60)            # `x` = trigger using `pitch` param
```

**Mini-notation syntax:**

| Token | Meaning |
|-------|---------|
| `name` or `60` | Trigger note (pitch name or MIDI number) |
| `.` or `~` | Rest |
| `_` | Sustain — extend the previous note |
| `[a b c]` | Group — subdivide one step into equal parts |
| `x?0.6` | Probability suffix — fires with given probability (0.0–1.0) |

---

**`p.fill(pitch, step, velocity=100, duration=0.25)`**

Repeat a note at a fixed beat interval across the whole pattern.

```python
p.fill(42, step=0.25)   # 16th note hi-hats
p.fill(60, step=0.5)    # 8th notes
```

---

**`p.arpeggio(pitches, step=0.25, velocity=100, duration=None, direction="up")`**

Cycle through a list of pitches at regular intervals.

```python
p.arpeggio([60, 64, 67], step=0.25)                       # ascending 16th notes
p.arpeggio([60, 64, 67], step=0.25, direction="down")      # descending
p.arpeggio([60, 64, 67], step=0.25, direction="up_down")   # ping-pong
p.arpeggio([60, 64, 67], step=0.25, direction="random")    # shuffle each cycle
```

---

**`p.chord(chord_obj, root, velocity=90, sustain=False, duration=1.0, inversion=0, count=None, legato=None)`**

Place a chord at beat 0. Requires `chord` injected via the pattern signature.

```python
@composition.pattern(channel=1, length=4)
def pads(p, chord):
    p.chord(chord, root=60, velocity=80, sustain=True)
    p.chord(chord, root=60, count=4, legato=0.9)   # 4-note arpeggio feel
```

---

**`p.strum(chord_obj, root, velocity=90, sustain=False, duration=1.0, inversion=0, count=None, offset=0.05, direction="up", legato=None)`**

Chord with staggered note onsets (guitar strum effect).

```python
p.strum(chord, root=52, velocity=85, offset=0.06, legato=0.95)
p.strum(chord, root=52, direction="down", offset=0.03)
```

---

### Rhythmic generators

These are called once to generate a full rhythm for the pattern.

**`p.euclidean(pitch, pulses, velocity=100, duration=0.1, dropout=0.0, no_overlap=False)`**

Distribute `pulses` as evenly as possible across the pattern (Bjorklund/Euclidean rhythm).
Produces many of the world's most common rhythms.

```python
p.euclidean("kick_1", pulses=3)                   # 3-against-16 tresillo
p.euclidean("snare_1", pulses=5, dropout=0.2)
p.euclidean("hi_hat_closed", pulses=7, no_overlap=True)
```

`no_overlap=True` skips steps where the same pitch already exists — useful for layering
ghost notes around hand-placed anchors.

---

**`p.bresenham(pitch, pulses, velocity=100, duration=0.1, dropout=0.0, no_overlap=False)`**

Alternative even distribution via the Bresenham line algorithm. Similar to Euclidean,
often yields different accent patterns.

```python
p.bresenham("snare_1", pulses=5)
```

---

**`p.bresenham_poly(parts, velocity=100, duration=0.1, grid=None, dropout=0.0, no_overlap=False)`**

Interlocking multi-voice rhythm generator. Voices never overlap — each step belongs to
exactly one voice. Weights control density.

```python
p.bresenham_poly(
    parts={"kick_1": 0.25, "snare_1": 0.125, "hi_hat_closed": 0.5},
    velocity={"kick_1": 100, "snare_1": 90, "hi_hat_closed": 70},
)
```

`parts` dict: `{pitch: density_weight}`. Weights 0.0–1.0; remainder becomes rests.
Use per-voice velocity dict or a single int for all voices.

---

### Algorithmic & generative

These generate whole sequences from mathematical or musical systems. All are `p.` methods —
no imports needed. Most place notes across the full pattern length automatically.

#### Chaos & continuous systems

**`p.lorenz(steps=16, pitch_range=(48, 72), velocity=80, duration=0.25, s=10.0, r=28.0, b=2.667, dt=0.01)`**

Pitches follow the x-axis of a Lorenz attractor — never exactly repeating, always coherent.

```python
p.lorenz(steps=16, pitch_range=(48, 72))
p.quantize("C", "minor")
```

**`p.logistic(steps=16, r=3.9, x0=0.5, pitch_range=(48, 72), velocity_range=(60, 120), duration=0.25)`**

The logistic map. `r` controls behaviour: below 3.0 settles, 3.0–3.57 oscillates,
above 3.57 is chaotic.

**`p.brownian(start=60, steps=16, step_size=2, pitch_range=(36, 84), velocity=80, duration=0.25)`**

Random-walk melody — each note steps up or down from the last, so lines stay connected.

**`p.golden_ratio(pitch=60, count=12, velocity=80, duration=0.25)`**

Spaces hits by the golden ratio: maximally even, never repeating.

**`p.spectral(harmonics=None, steps=16, pitch_range=(48, 72), velocity=80, duration=0.25)`**

Maps a sum-of-harmonics waveform to a pitch contour.

**`p.gray_scott(pitch=60, n=16, f=0.055, k=0.062, iterations=200, velocity_range=(40, 120), duration=0.25)`**

Reaction-diffusion: Turing-pattern intensities become note velocities.

#### Cellular automata

**`p.cellular_1d(pitch, rule=30, generation=None, velocity=60, duration=0.1, no_overlap=False, dropout=0.0, rng=None)`**

Elementary 1D cellular automaton. Rule 30 is chaotic, 90 is fractal, 110 is complex.
`generation=None` advances automatically with the pattern cycle.

```python
p.cellular_1d("hi_hat_closed", rule=30)
```

**`p.cellular_2d(pitches, rule="B368/S245", generation=None, velocity=60, duration=0.1, no_overlap=False, dropout=0.0, seed=1, density=0.5, rng=None)`**

Life-like 2D automaton — rows map to pitches, so it produces polyphony. `pitches` is a list.

**`p.game_of_life(pitch=60, cols=16, rows=4, generations=8, row=0, duration=0.25, velocity=80)`**

Conway's Game of Life; triggers notes for live cells in a single row.

#### Grammar & probability

**`p.lsystem(pitch_map, axiom, rules, generations=3, step=None, velocity=80, duration=0.2)`**

L-system string rewriting. `pitch_map` maps each symbol to a pitch.

```python
p.lsystem({"A": 60, "B": 64}, axiom="A", rules={"A": "AB", "B": "A"}, generations=4)
```

**`p.markov(transitions, pitch_map, velocity=100, duration=0.1, step=0.25, start=None)`**

Walks a first-order Markov chain, one note per `step` beats. `transitions` maps each state
to a list of `(next_state, weight)` tuples.

```python
p.markov(
    transitions={"a": [("b", 3), ("c", 1)], "b": [("a", 2)], "c": [("a", 1)]},
    pitch_map={"a": 60, "b": 63, "c": 67},
)
```

**`p.melody(state, step=0.25, velocity=90, duration=0.2, chord_tones=None)`**

Generates a melodic line from a persistent `MelodicState` (Narmour implication-realisation
model). Keep the `state` object between cycles so the melody develops.

#### Ghost notes & density

**`p.ghost_fill(pitch, density=0.3, velocity=35, bias="uniform", no_overlap=True, grid=None, duration=0.1, rng=None)`**

Fill the pattern with quiet probability-weighted ghost notes.

```python
p.ghost_fill("snare_1", density=0.4, bias="offbeat")
```

**`p.thin(pitch, strategy="strength", amount=0.5, grid=None, rng=None)`**

The inverse of `ghost_fill` — removes notes based on rhythmic position, keeping the
strong beats.

**`p.build_ghost_bias(grid, bias)`** — Build the probability weight list used by the above,
if you want to inspect or reuse it.

#### Importing

**`p.from_midi(filepath, track=0, channel=None, pitch_offset=0, velocity=None, duration=0.25)`**

Load notes from a `.mid` file into the pattern, then treat them like any other notes.

```python
p.from_midi("riff.mid", pitch_offset=-12)
p.swing(60)
```

---

### Transformations

Call these **after** placing notes. They modify whatever is already in the pattern.

**`p.transpose(semitones)`**

```python
p.transpose(12)    # up one octave
p.transpose(-5)    # down a perfect fourth
```

---

**`p.quantize(key, mode="ionian")`**

Snap all pitches to the nearest scale degree.

```python
p.quantize("C", "dorian")
p.quantize("F#", "aeolian")
```

**Scale modes:** `ionian` (major), `dorian`, `phrygian`, `lydian`, `mixolydian`,
`aeolian` (natural minor), `locrian`, `harmonic_minor`, `melodic_minor`

---

**`p.quantize_m21(key, scale_name="MajorScale", scala_name=None)`**

Snap all pitches to the nearest degree of any music21 scale class or Scala archive file.

```python
p.quantize_m21("C", "MelodicMinorScale")
p.quantize_m21("D", "HarmonicMinorScale")
p.quantize_m21("F#", "DorianScale")
p.quantize_m21("Bb", "OctatonicScale")
# Scala archive — takes precedence over scale_name when given
p.quantize_m21("C", scala_name="mbira_banda.scl")
p.quantize_m21("C", scala_name="pyth_12.scl")
```

| Parameter | Description |
|-----------|-------------|
| `key` | Root note as a string: `"C"`, `"F#"`, `"Bb"`, etc. |
| `scale_name` | music21 scale class name (see table below). Default `"MajorScale"`. Ignored when `scala_name` is given. |
| `scala_name` | Filename from the Scala archive, e.g. `"mbira_banda.scl"`. When provided, overrides `scale_name`. The archive contains 3,935 tuning files covering historical temperaments, world music scales, and microtonal systems. |

**Available scale classes (`scale_name`):**

| Scale class | Character |
|-------------|-----------|
| `MajorScale` | Standard major (Ionian) |
| `MinorScale` | Natural minor (Aeolian) |
| `HarmonicMinorScale` | Minor with raised 7th |
| `MelodicMinorScale` | Ascending melodic minor (raised 6th & 7th) |
| `DorianScale` | Minor with raised 6th |
| `PhrygianScale` | Minor with flattened 2nd |
| `LydianScale` | Major with raised 4th |
| `MixolydianScale` | Major with flattened 7th |
| `LocrianScale` | Diminished-feeling mode (flattened 2nd & 5th) |
| `OctatonicScale` | Diminished scale — alternating whole/half steps |
| `WholeToneScale` | Six-note scale — all whole steps |
| `RagAsawari` | North Indian raga (Asavari) |
| `RagMarwa` | North Indian raga (Marwa) |
| `SieveScale` | Xenakis-style interval sieve |

**Example — chromatic melody snapped to melodic minor:**

```python
@pat(0)
def ch1(p):
    for i in range(16):
        p.note(60 + i, beat=i * 0.25)
    p.quantize_m21("A", "MelodicMinorScale")
```

**Example — Pythagorean tuning via Scala:**

```python
@pat(0)
def ch1(p):
    p.arpeggio([60, 62, 64, 65, 67, 69, 71], step=0.25)
    p.quantize_m21("C", scala_name="pyth_12.scl")
```

> **Requires music21:** bundled in the POMSKI installer. `pip install music21` from source.

---

**`p.microtuning(key, scala_name, bend_range=2.0)`**

Apply microtonal tuning from a Scala archive file using MIDI pitch bend. Unlike `quantize_m21`,
this not only snaps notes to the nearest scale degree but also inserts a pitch bend event at
each note onset that corrects the intonation by the exact cent deviation of that scale degree.
A reset bend is inserted at the next note or pattern end.

This lets notes play at pitches between MIDI semitones — essential for mbira tunings,
just intonation, historical temperaments, and other non-12-TET systems.

```python
p.microtuning("C", "mbira_banda.scl")
p.microtuning("C", "pyth_12.scl", bend_range=12)
```

| Parameter | Description |
|-----------|-------------|
| `key` | Root note as a string. |
| `scala_name` | Filename from the Scala archive (e.g. `"mbira_banda.scl"`). |
| `bend_range` | Synth pitch wheel range in semitones (default `2.0`). Must match the receiving instrument's pitch bend range setting. Use `12` or `24` if your synth is configured for a wider range. |

> **Limitation:** Pitch bend is per-channel, so simultaneously playing notes share one bend value.
> Works best on monophonic lines or instruments where all simultaneous notes have the same tuning correction.

```python
@pat(0)
def ch1(p):
    p.brownian(start=60, steps=16)
    p.microtuning("C", "mbira_banda.scl")

@pat(1)
def ch2(p):
    p.euclidean(60, pulses=5)
    p.microtuning("C", "gamelan_udan.scl", bend_range=12)
```

---

**`p.dropout(probability)`**

Randomly remove notes.

```python
p.dropout(0.2)   # 20% chance of removal per note
```

---

**`p.reverse()`** — Flip the pattern backwards in time.

**`p.double_time()`** — Compress into first half; plays at 2× speed.

**`p.half_time()`** — Expand by 2×; plays at half speed. Notes outside the pattern length are removed.

---

**`p.shift(steps, grid=None)`**

Rotate the pattern by N grid steps.

```python
p.shift(2)     # shift right 2 sixteenth notes
p.shift(-1)    # shift left 1 step
```

---

**`p.invert(pivot=60)`**

Reflect all pitches around a pivot MIDI note.

```python
p.invert(60)   # mirror around Middle C
```

---

**`p.every(n, fn)`**

Apply a transformation every Nth cycle.

```python
p.every(4, lambda p: p.reverse())         # reverse every 4 bars
p.every(8, lambda p: p.transpose(12))    # up an octave every 8 bars
```

---

### Timing & feel

**`p.swing(amount=57.0, grid=0.25, strength=1.0)`**

Apply swing feel.

```python
p.swing(57)                    # Ableton default — gentle 16th-note shuffle
p.swing(67)                    # triplet swing
p.swing(57, grid=0.5)          # 8th-note swing
p.swing(57, strength=0.5)      # half-strength blend
```

`amount`: 50 = straight, 57 = moderate shuffle, 67 ≈ triplet swing. Range 50–75.

---

**`p.groove(template, strength=1.0)`**

Apply a groove template (timing + velocity offsets).

```python
from subsequence.groove import Groove
groove = Groove.swing(percent=57)
p.groove(groove)
p.groove(groove, strength=0.5)
```

---

**`p.randomize(timing=0.03, velocity=0.0)`**

Add micro-variations to timing and/or velocity — the humanising step.

```python
p.randomize()                              # timing only (±0.03 beats)
p.randomize(timing=0.04, velocity=0.08)   # both
```

Recommended ranges: `timing` 0.02–0.08 beats, `velocity` 0.05–0.15.

---

**`p.legato(ratio=1.0)`**

Stretch note durations to fill the gap to the next note.

```python
p.legato(0.9)   # 90% of the gap — slightly detached
p.legato(1.0)   # fully connected
```

---

**`p.staccato(ratio=0.5)`**

Set all note durations to a fixed proportion of a beat.

```python
p.staccato(0.25)   # 16th note gate (very short)
p.staccato(0.5)    # 8th note gate
```

---

**`p.velocity_shape(low=64, high=127)`**

Apply organic velocity variation using a van der Corput quasi-random sequence.

---

### Utilities

**`p.set_length(length)`**

Dynamically change pattern length in beats.

```python
if p.cycle % 4 == 3:
    p.set_length(2)   # half-length every 4th cycle
```

---

**`p.param(name, default=None)`**

Read a live-tweakable parameter (set via `composition.tweak()`).

```python
pitch = p.param("pitch", 60)
```

---

**`p.signal(name)`**

Read a conductor signal value at the current bar (0.0–1.0 by default).

```python
density = p.signal("density")
```

---

## Conductor & signals

The conductor produces named, continuously-varying values. Register a signal once, then read
it from any pattern with `p.signal(name)`. Signals are drawn live in the Signals tab.

**`composition.conductor.lfo(name, shape="sine", cycle_beats=16.0, min_val=0.0, max_val=1.0, phase=0.0)`**

A repeating cycle. Shapes: `"sine"`, `"triangle"`, `"saw"`, `"square"`.

```python
composition.conductor.lfo("swell", shape="sine", cycle_beats=16, min_val=0.2, max_val=1.0)

@composition.pattern(channel=0, length=4)
def pad(p):
    vel = int(p.signal("swell") * 100)
    p.chord(chord, root=48, velocity=vel)
```

**`composition.conductor.line(name, start_val, end_val, duration_beats, start_beat=0.0, loop=False, shape="linear")`**

A one-shot ramp that holds at `end_val` when it finishes — use it for build-ups and fades.
Set `loop=True` to repeat instead of holding.

```python
composition.conductor.line("buildup", start_val=0, end_val=1,
                           duration_beats=32, shape="ease_in_out")
```

Ramp shapes are easing curves, **not** the LFO waveform list: `"linear"`, `"ease_in"`,
`"ease_out"`, `"ease_in_out"`, `"exponential"`, `"logarithmic"`, `"s_curve"`.

**`composition.conductor.signal_names`** — property (no parentheses); a tuple of every
registered signal name.
**`composition.conductor.get(name, beat)`** — value at an explicit beat. Inside a pattern
prefer `p.signal(name)`, which resolves the current beat for you.

---

## MIDI messages & automation

Beyond notes, a pattern can emit CC, pitch bend, program changes, SysEx and OSC — all
scheduled at beat positions inside the loop.

### Sustained notes & drones

`note()` schedules its own note-off. These do not — they sustain until you stop them.

| Call | What it does |
|---|---|
| `p.drone(pitch, beat=0.0, velocity=100)` | Start a sustained note |
| `p.drone_off(pitch, beat=0.0)` | Stop a drone |
| `p.note_on(pitch, beat=0.0, velocity=100)` | Raw note-on, no counterpart |
| `p.note_off(pitch, beat=0.0)` | Raw note-off |
| `p.silence(beat=0.0)` | CC 123 + CC 120 — all notes/sound off on this channel |

Guard a drone with a cycle check so it doesn't retrigger every loop:

```python
@composition.pattern(channel=2, length=4)
def bed(p):
    if p.cycle == 0:
        p.drone(36, velocity=70)
```

### Control change

**`p.cc(control, value, beat=0.0)`** — one CC message.

**`p.cc_ramp(control, start, end, beat_start=0.0, beat_end=None, resolution=1, shape="linear")`**

Interpolate a CC over a beat range — filter sweeps, swells, anything mapped in your synth.
`resolution` is messages per pulse; raise it for smoother movement.

```python
p.cc_ramp(74, 0, 127, beat_start=0, beat_end=4, shape="ease_in_out")
```

### Pitch bend & glide

| Call | What it does |
|---|---|
| `p.pitch_bend(value, beat=0.0)` | Single bend message |
| `p.pitch_bend_ramp(start, end, beat_start=0.0, beat_end=None, resolution=1, shape="linear")` | Bend over a range |
| `p.portamento(time=0.15, shape="linear", resolution=1, bend_range=2.0, wrap=True)` | Glide between **all** consecutive notes |
| `p.slide(notes=None, steps=None, time=0.15, shape="linear", resolution=1, bend_range=2.0, wrap=True, extend=True)` | TB-303-style glide into **selected** notes only |
| `p.bend(note, amount, start=0.0, end=1.0, shape="linear", resolution=1)` | Bend one note by index |

`bend_range` must match your synth's pitch-bend range in semitones, or the interval will
sound wrong.

```python
p.seq("36 _ 39 _ 43")
p.slide(steps=[2, 4], time=0.12, bend_range=2.0)
```

### Patches, SysEx & OSC

**`p.program_change(program, beat=0.0, bank_msb=None, bank_lsb=None)`** — switch patch on
this pattern's channel, optionally with bank select.

**`p.sysex(data, beat=0.0)`** — raw System Exclusive bytes.

**`p.osc(address, *args, beat=0.0)`** and
**`p.osc_ramp(address, start, end, beat_start=0.0, beat_end=None, resolution=4, shape="linear")`**
send OSC from inside a pattern. Both require `composition.osc()` to have been called before
`composition.play()`.

---

## LiveBridge (`live`)

Bidirectional bridge to Ableton Live via AbletonOSC. Silent if Live is not running;
reconnects automatically every 5 seconds.

**Setup:** Install AbletonOSC remote script, enable it in Live Preferences →
Link/Tempo/MIDI → Control Surface. Live's status bar should confirm:
*"AbletonOSC: Listening for OSC on port 11000"*

### State

| Attribute | Type | Description |
|-----------|------|-------------|
| `live.connected` | `bool` | `True` if Live is reachable |
| `live.tracks` | `list[str]` | Track names |
| `live.scenes` | `list[str]` | Scene names |
| `live.clip_grid` | `list[list[int]]` | Clip states: 0=empty, 1=stopped, 2=playing, 3=triggered |

### Transport

```python
live.play()                 # Start global transport
live.stop_transport()       # Stop global transport
live.set_tempo(128.0)       # Set BPM in Ableton (also updates Link if active)
```

### Clips & scenes

```python
live.clip_play(track=0, clip=0)    # Fire clip at track 0, slot 0 (0-indexed)
live.clip_stop(track=0, clip=0)    # Stop a clip
live.track_stop(track=0)           # Stop all clips on a track
live.scene_play(scene=2)           # Fire scene 2 (0-indexed)
```

### Mixer

```python
live.track_volume(track=0, value=0.9)         # Normalised 0.0–1.0
live.track_pan(track=0, value=0.0)            # -1.0 (L) to 1.0 (R), 0 = centre
live.track_mute(track=1, muted=True)          # Mute/unmute track
live.track_send(track=0, send=0, value=0.7)   # Send level 0.0–1.0
```

### Devices

```python
live.device_param(track=0, device=0, param=3, value=0.7)
# value is normalised 0.0–1.0 — mapped to real range by Live's device
```

### Watch (live data polling)

Poll a Live property every ~500ms and write into `composition.data`:

```python
live.watch("track/0/volume")
# → composition.data["live_track_0_volume"] updated every 500ms

live.watch("song/tempo", data_key="current_bpm")
# → composition.data["current_bpm"]
```

Use the value inside a pattern via `p.data`:

```python
@composition.pattern(channel=1, length=4)
def reactive(p):
    vol = p.data.get("live_track_0_volume", 0.8)
    pitch = 60 + int(vol * 24)
    p.note(pitch, beat=0)
```

### ClyphX

POMSKI bundles the free [ClyphX](https://github.com/ldrolez/clyphx-live11) (LGPL-3.0) and
installs it into Ableton's Remote Scripts folder on first launch. Add **ClyphX** as a Control
Surface in Live's preferences (alongside AbletonOSC) and restart Live to enable it.

**`live.clyphx(action)`** — Send any ClyphX action string. Works with the bundled free version.

Creates a clip on a dedicated hidden MIDI track (`_POMSKI_CLYPHX`) and fires it.
ClyphX intercepts the clip launch and executes the action. Each concurrent call
uses its own clip slot.

```python
live.clyphx("BPM 120")
live.clyphx("1/MUTE ON")
live.clyphx("1/DEV(1) ON ; 2/ARM ON")
live.clyphx("(PSEQ) 1/MUTE ; 2/MUTE ; 3/MUTE")
```

**`live.clyphx_osc(address, value=1.0)`** — Trigger a pre-defined X-OSC address.
**Requires ClyphX Pro** — a separate paid product from
[Isotonik Studios](https://isotonikstudios.com/product/clyphx-pro/). The bundled free ClyphX
has no OSC listener, and because this is fire-and-forget UDP it cannot detect a missing
listener: the call silently does nothing if ClyphX Pro isn't installed and running.

Faster than `clyphx()` for frequently-used actions. Bypasses AbletonOSC and sends
directly to ClyphX Pro on port 7005. Requires entries in ClyphX Pro's `X-OSC.txt`.

```python
# X-OSC.txt:  MY_ACTION | BPM 120
live.clyphx_osc("/MY_ACTION")        # trigger with value 1
live.clyphx_osc("/MUTE_1", 1)        # on
live.clyphx_osc("/MUTE_1", 0)        # off
```

### Raw OSC

```python
live.send("/live/song/set/tempo", 128.0)   # raw AbletonOSC message
```

---

## DataFeeds (`feeds`)

HTTP polling helper. Fetches external APIs at regular intervals and writes results
into `composition.data`.

```python
# Start a feed — value lands at composition.data["feed_btc"]
feeds.add("btc", "https://api.coinbase.com/v2/prices/BTC-USD/spot",
          interval=10, extract=lambda r: float(r["data"]["amount"]))

# Custom headers
feeds.add("gh", "https://api.github.com/repos/python/cpython",
          headers={"Accept": "application/vnd.github+json"},
          extract=lambda r: r["stargazers_count"])

# POST request
feeds.add("custom", "https://api.example.com/query",
          method="POST", body={"filter": "all"},
          extract=lambda r: r["value"])

feeds.stop("btc")       # stop one feed
feeds.stop_all()        # stop all feeds
feeds                   # shows active feeds and current values
```

**`feeds.add(key, url, interval=30, extract=None, headers=None, method="GET", body=None)`**

| Parameter | Description |
|-----------|-------------|
| `key` | Short name. Value lands in `composition.data["feed_<key>"]` |
| `url` | HTTP endpoint |
| `interval` | Seconds between fetches (default 30) |
| `extract` | `lambda parsed_json: value` — stores full JSON if omitted |
| `headers` | Optional dict of request headers |
| `method` | HTTP method (default `"GET"`) |
| `body` | Optional request body, serialised to JSON |

Use the value in a pattern:

```python
@composition.pattern(channel=0, length=4)
def price_melody(p):
    price = p.data.get("feed_btc", 0)
    pitch = int(48 + min(price / 1000, 36))
    p.note(pitch, beat=0)
```

---

## Duration constants (`dur`)

```python
import subsequence.constants.durations as dur
```

| Constant | Beats | Musical value |
|----------|-------|---------------|
| `dur.THIRTYSECOND` | 0.125 | 32nd note |
| `dur.SIXTEENTH` | 0.25 | 16th note |
| `dur.DOTTED_SIXTEENTH` | 0.375 | Dotted 16th |
| `dur.TRIPLET_EIGHTH` | 0.333 | Triplet 8th |
| `dur.EIGHTH` | 0.5 | 8th note |
| `dur.DOTTED_EIGHTH` | 0.75 | Dotted 8th |
| `dur.TRIPLET_QUARTER` | 0.667 | Triplet quarter |
| `dur.QUARTER` | 1.0 | Quarter note (1 beat) |
| `dur.DOTTED_QUARTER` | 1.5 | Dotted quarter |
| `dur.HALF` | 2.0 | Half note |
| `dur.DOTTED_HALF` | 3.0 | Dotted half |
| `dur.WHOLE` | 4.0 | Whole note (1 bar) |

Usage:

```python
# 8-step pattern at 16th-note resolution
@composition.pattern(channel=1, length=8, unit=dur.SIXTEENTH)
def riff(p):
    p.sequence(steps=[0, 2, 5, 7], pitches=[60, 62, 64, 67])
```

---

## GM Drum Map

Pass `GM_DRUM_MAP` as `drum_note_map` to use string names in all note placement methods.

```python
from subsequence.constants.instruments.gm_drums import GM_DRUM_MAP

@composition.pattern(channel=9, length=4, drum_note_map=GM_DRUM_MAP)
def drums(p):
    p.hit_steps("kick_1", [0, 8])
    p.hit_steps("snare_1", [4, 12])
    p.hit_steps("hi_hat_closed", range(16), velocity=70)
    p.euclidean("ride_1", pulses=5)
```

### GM name → MIDI note reference

| Name | Note | | Name | Note |
|------|------|-|------|------|
| `kick_2` | 35 | | `hi_hat_closed` | 42 |
| `kick_1` | 36 | | `hi_hat_pedal` | 44 |
| `side_stick` | 37 | | `hi_hat_open` | 46 |
| `snare_1` | 38 | | `crash_1` | 49 |
| `hand_clap` | 39 | | `ride_1` | 51 |
| `snare_2` | 40 | | `chinese_cymbal` | 52 |
| `low_floor_tom` | 41 | | `ride_bell` | 53 |
| `high_floor_tom` | 43 | | `tambourine` | 54 |
| `low_tom` | 45 | | `splash_cymbal` | 55 |
| `low_mid_tom` | 47 | | `cowbell` | 56 |
| `high_mid_tom` | 48 | | `crash_2` | 57 |
| `high_tom` | 50 | | `ride_2` | 59 |
| `high_bongo` | 60 | | `maracas` | 70 |
| `low_bongo` | 61 | | `cabasa` | 69 |
| `mute_high_conga` | 62 | | `shaker` | 82 |
| `open_high_conga` | 63 | | `jingle_bell` | 83 |
| `low_conga` | 64 | | `claves` | 75 |
| `high_timbale` | 65 | | `cowbell` | 56 |
| `low_timbale` | 66 | | `mute_triangle` | 80 |
| `high_agogo` | 67 | | `open_triangle` | 81 |
| `low_agogo` | 68 | | `vibraslap` | 58 |

Full list: `subsequence/constants/instruments/gm_drums.py` (notes 27–87).

---

## REPL Quick Reference

Type code into the browser command box (Enter to run) or send via TCP to port `5555`.

```python
# ── Pattern control ──────────────────────────────────────────────────
composition.mute("ch3")
composition.unmute("ch3")
composition.running_patterns                    # dict of active patterns
composition.set_bpm(140)

# ── Live tweaks ──────────────────────────────────────────────────────
composition.tweak("bass", pitches=[48, 52, 55, 60])
composition.clear_tweak("bass")

# ── Ableton Live control ─────────────────────────────────────────────
live.clip_play(0, 0)
live.scene_play(2)
live.track_volume(0, 0.8)
live.track_mute(1, True)
live.set_tempo(128.0)
live.clyphx("BPM 120")
live.clyphx_osc("/MY_ACTION")

# ── Data feeds ───────────────────────────────────────────────────────
feeds.add("btc", "https://api.coinbase.com/v2/prices/BTC-USD/spot",
          extract=lambda r: float(r["data"]["amount"]))
feeds.stop("btc")
feeds                        # list feeds and current values

# ── Inspect state ────────────────────────────────────────────────────
composition.data             # shared live data dict
composition.live_info()      # full state snapshot
live.connected
live.tracks
live.clip_grid
```

### Command box prefixes

| Prefix | Behaviour |
|--------|-----------|
| *(none)* | Python — executed in REPL |
| `cx:` | ClyphX Pro action (e.g. `cx:BPM 120`) |

---

## Ports

| Service | Port |
|---------|------|
| Web UI (HTTP + WebSocket) | 8080 |
| REPL | 5555 |
| AbletonOSC receive | 11000 |
| AbletonOSC reply | 11001 |
| ClyphX Pro OSC | 7005 |

---

## MIDI channel reference

POMSKI uses 0-indexed channels (`channel=0` = MIDI ch 1).

| Channel | Use |
|---------|-----|
| 0–8, 10–15 | Melodic instruments |
| 9 | GM percussion |

Template slots `ch1`–`ch16` map to channels 0–15 respectively.
