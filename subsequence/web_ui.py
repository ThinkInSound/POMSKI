import asyncio
import http.server
import json
import logging
import mido
import mido.backends.rtmidi  # ensure PyInstaller bundles the rtmidi backend
import os
import queue
import socketserver
import threading
import typing
import weakref

import websockets
import websockets.asyncio.server
import websockets.exceptions

import subsequence.helpers.network

logger = logging.getLogger(__name__)

class WebUI:

    """
    Background Web UI Server.
    Delivers composition state to connected web clients via WebSockets without
    blocking the audio loop, and serves the static frontend assets via HTTP.
    """

    def __init__ (self, composition: typing.Any, http_port: int = 8080, ws_port: int = 8765) -> None:

        self.composition_ref = weakref.ref(composition)
        self.http_port = http_port
        self.ws_port = ws_port
        self._http_thread: typing.Optional[threading.Thread] = None
        self._ws_server: typing.Optional[websockets.asyncio.server.Server] = None
        self._broadcast_task: typing.Optional[asyncio.Task] = None
        self._clients: typing.Set[websockets.asyncio.server.ServerConnection] = set()
        self._last_bar: int = -1
        self._cached_patterns: typing.List[typing.Dict[str, typing.Any]] = []
        self._midi_queue: queue.SimpleQueue = queue.SimpleQueue()
        self._builder_error_queue: queue.SimpleQueue = queue.SimpleQueue()
        self._data_snap: typing.FrozenSet = frozenset()
        self._data_signals_cache: typing.Dict[str, float] = {}

    def start (self) -> None:

        self._start_http_server()
        asyncio.create_task(self._start_ws_server())

    def _start_http_server (self) -> None:

        if self._http_thread and self._http_thread.is_alive():
            return

        web_dir = os.path.join(os.path.dirname(__file__), "assets", "web")
        if not os.path.exists(web_dir):
            os.makedirs(web_dir, exist_ok=True)

        class Handler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args: typing.Any, **kwargs: typing.Any) -> None:
                super().__init__(*args, directory=web_dir, **kwargs)
            def log_message(self, format: str, *args: typing.Any) -> None:
                pass

        def run_server() -> None:
            socketserver.TCPServer.allow_reuse_address = True
            with socketserver.TCPServer(("", self.http_port), Handler) as httpd:
                try:
                    httpd.serve_forever()
                except Exception as e:
                    logger.error(f"HTTP Server error: {e}")

        self._http_thread = threading.Thread(target=run_server, daemon=True)
        self._http_thread.start()
        
        local_ip = subsequence.helpers.network.get_local_ip()
        urls = [f"http://localhost:{self.http_port}"]
        if local_ip != "127.0.0.1":
            urls.append(f"http://127.0.0.1:{self.http_port}")
            urls.append(f"http://{local_ip}:{self.http_port}")
            
        logger.info("Web UI Dashboard available at:\n  " + "\n  ".join(urls))

    async def _handle_client (self, websocket: websockets.asyncio.server.ServerConnection) -> None:

        self._clients.add(websocket)
        try:
            async for message in websocket:
                try:
                    cmd  = json.loads(message)
                    comp = self.composition_ref()
                    if comp is None:
                        continue
                    action = cmd.get('cmd')

                    if action == 'set_bpm':
                        bpm = float(cmd.get('value', 120))
                        if hasattr(comp, 'set_bpm'):
                            comp.set_bpm(bpm)
                        elif hasattr(comp, 'sequencer') and comp.sequencer:
                            comp.sequencer.set_bpm(bpm)
                        live = getattr(comp, '_live_bridge', None)
                        if live is not None and getattr(live, 'connected', False):
                            live.set_tempo(bpm)

                    elif action == 'mute':
                        name = cmd.get('pattern')
                        if name and hasattr(comp, 'running_patterns'):
                            pat = comp.running_patterns.get(name)
                            if pat: pat._muted = True

                    elif action == 'unmute':
                        name = cmd.get('pattern')
                        if name and hasattr(comp, 'running_patterns'):
                            pat = comp.running_patterns.get(name)
                            if pat: pat._muted = False

                    elif action == 'clear_pattern':
                        name = cmd.get('pattern')
                        if name and hasattr(comp, 'running_patterns'):
                            pat = comp.running_patterns.get(name)
                            if pat:
                                pat._builder_fn = lambda p: None
                                pat._wants_chord = False
                                pat._muted = False
                                # Reset length to a safe default so the slot is
                                # fully usable again even if a bad `unit` value
                                # left it with an invalid (too-short) length.
                                pat.length = 4.0
                                pat.steps = {}
                                self._last_bar = -1  # invalidate pattern cache
                                # Silence the channel immediately so pre-queued
                                # note_on events are skipped at dispatch time.
                                # The channel unsilences automatically when the
                                # next rebuild produces notes.
                                seq = getattr(comp, 'sequencer', None)
                                if seq is not None:
                                    seq.silenced_channels.add(pat.channel)

                    elif action == 'repl':
                        code = cmd.get('code', '').strip()
                        if code:
                            asyncio.create_task(self._forward_repl(code, websocket))

                    elif action == 'link_toggle':
                        link = getattr(comp, '_link', None)
                        if link is not None:
                            link.enabled = not link.enabled
                            await websocket.send(json.dumps({"link_state": self._get_link_state(comp)}))

                    elif action == 'clear_signal':
                        sig_name = cmd.get('name')
                        if sig_name and comp.conductor:
                            comp.conductor._signals.pop(sig_name, None)
                            comp.data.pop(sig_name, None)

                    elif action == 'get_midi_devices':
                        await websocket.send(json.dumps({"midi_devices": self._get_midi_devices()}))

                    elif action == 'set_midi_input':
                        device = cmd.get('device', '')
                        seq = getattr(comp, 'sequencer', None)
                        if seq and device:
                            try:
                                seq.input_device_name = device
                                seq.reopen_input()
                                await websocket.send(json.dumps({"midi_input_set": device}))
                            except Exception as e:
                                await websocket.send(json.dumps({"midi_input_error": str(e)}))

                    elif action == 'set_midi_output':
                        device = cmd.get('device', '')
                        seq = getattr(comp, 'sequencer', None)
                        if seq and device:
                            try:
                                seq.midi_out = mido.open_output(device)
                                seq.output_device_name = device
                                await websocket.send(json.dumps({"midi_output_set": device}))
                            except Exception as e:
                                await websocket.send(json.dumps({"midi_output_error": str(e)}))

                    elif action == 'record_start':
                        seq = getattr(comp, 'sequencer', None)
                        if seq is not None:
                            import datetime, os
                            ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                            fname = f'session_{ts}.mid'
                            seq.record_filename = fname
                            seq.recorded_events = []
                            seq.recording = True
                            abs_path = os.path.abspath(fname)
                            await websocket.send(json.dumps({'repl_result': f'record_start: seq id={id(seq)} recording={seq.recording} events={len(seq.recorded_events)}'}))
                            await websocket.send(json.dumps({'record_state': 'recording', 'filename': abs_path}))
                        else:
                            await websocket.send(json.dumps({'record_state': 'error', 'filename': 'No sequencer found'}))

                    elif action == 'record_stop':
                        seq = getattr(comp, 'sequencer', None)
                        if seq is not None:
                            import os, traceback
                            n_events = len(getattr(seq, 'recorded_events', []))
                            is_recording = getattr(seq, 'recording', False)
                            filename = getattr(seq, 'record_filename', None) or 'session.mid'
                            abs_path = os.path.abspath(filename)
                            if not is_recording:
                                await websocket.send(json.dumps({'record_state': 'error', 'filename': 'recording was not active — start recording first'}))
                            elif n_events == 0:
                                seq.recording = False
                                await websocket.send(json.dumps({'record_state': 'error', 'filename': 'no events captured — MIDI may not have played during recording'}))
                            else:
                                try:
                                    seq.recording = False
                                    seq.save_recording()
                                    seq.recorded_events = []
                                    await websocket.send(json.dumps({'record_state': 'saved', 'filename': abs_path}))
                                except Exception:
                                    await websocket.send(json.dumps({'record_state': 'error', 'filename': traceback.format_exc()}))
                        else:
                            await websocket.send(json.dumps({'record_state': 'error', 'filename': 'No sequencer found'}))

                    elif action == 'live_clip_fire':
                        live = getattr(comp, '_live_bridge', None)
                        if live and live.connected:
                            live.clip_play(cmd.get('track', 0), cmd.get('clip', 0))

                    elif action == 'live_clip_stop':
                        live = getattr(comp, '_live_bridge', None)
                        if live and live.connected:
                            live.clip_stop(cmd.get('track', 0), cmd.get('clip', 0))

                    elif action == 'live_scene_fire':
                        live = getattr(comp, '_live_bridge', None)
                        if live and live.connected:
                            live.scene_play(cmd.get('scene', 0))

                    elif action == 'live_track_stop':
                        live = getattr(comp, '_live_bridge', None)
                        if live and live.connected:
                            live.track_stop(cmd.get('track', 0))

                    elif action == 'clyphx':
                        live = getattr(comp, '_live_bridge', None)
                        script = cmd.get('script', '')
                        if not script:
                            await websocket.send(json.dumps({'log': 'ClyphX: empty script', 'level': 'err'}))
                        elif live is None:
                            await websocket.send(json.dumps({'log': 'ClyphX: no live bridge attached', 'level': 'err'}))
                        elif not live.connected:
                            await websocket.send(json.dumps({'log': 'ClyphX: AbletonOSC not connected', 'level': 'err'}))
                        else:
                            live.clyphx(script)

                except Exception:
                    logger.exception("WebUI: unhandled error processing WebSocket command")

        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._clients.discard(websocket)

    async def _forward_repl(self, code: str, websocket: websockets.asyncio.server.ServerConnection) -> None:
        import asyncio as _asyncio
        try:
            reader, writer = await _asyncio.open_connection('127.0.0.1', 5555)
            writer.write(code.encode('utf-8') + b'\x04')
            await writer.drain()
            chunks = []
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                if b'\x04' in chunk:
                    before, _, _ = chunk.partition(b'\x04')
                    chunks.append(before)
                    break
                chunks.append(chunk)
            writer.close()
            result = b''.join(chunks).decode('utf-8').strip()
            is_error = any(x in result for x in ['Traceback', 'Error:', 'Exception:'])

            # Deduplicate pending patterns and invalidate pattern cache
            comp = self.composition_ref()
            if comp is not None and not is_error:
                pending = getattr(comp, '_pending_patterns', None)
                if pending is not None:
                    seen = {}
                    for pp in reversed(pending):
                        name = getattr(pp, '_builder_fn', None)
                        name = getattr(name, '__name__', None) if name else None
                        if name and name not in seen:
                            seen[name] = pp
                    pending[:] = list(reversed(list(seen.values())))
                self._last_bar = -1  # force pattern list refresh on next broadcast

            await websocket.send(json.dumps({
                'repl_result' if not is_error else 'repl_error': result
            }))
        except Exception as e:
            await websocket.send(json.dumps({'repl_error': str(e)}))

    def _get_link_state(self, comp: typing.Any) -> dict:
        link = getattr(comp, '_link', None)
        if link is None:
            return {"available": False}
        return {
            "available": True,
            "enabled":   bool(getattr(link, 'enabled', False)),
            "peers":     int(getattr(link, '_num_peers', 0)),
            "tempo":     float(getattr(link, '_tempo', 120.0)),
        }

    def _get_midi_devices(self) -> typing.Dict[str, typing.List[str]]:
        try:
            return {
                "inputs":  mido.get_input_names(),
                "outputs": mido.get_output_names(),
            }
        except Exception:
            return {"inputs": [], "outputs": []}

    async def _start_ws_server(self) -> None:
        try:
            self._ws_server = await websockets.asyncio.server.serve(self._handle_client, "0.0.0.0", self.ws_port)
            asyncio.create_task(self._broadcast_loop())
        except Exception as e:
            logger.error(f"WebSocket server error: {e}")

    def push_builder_error(self, pattern_name: str, tb: str) -> None:
        """Called from the sequencer thread when a pattern builder raises."""
        self._builder_error_queue.put_nowait(f"[{pattern_name}] {tb.strip()}")

    def _register_midi_hook(self) -> None:
        comp = self.composition_ref()
        if comp is None:
            return
        seq = getattr(comp, 'sequencer', None)
        if seq is None:
            return
        if getattr(seq, '_pomski_hooked', False):
            return
        original_send = seq._send_midi
        midi_queue = self._midi_queue

        def _hooked_send(event):
            original_send(event)
            if event.message_type in ('note_on', 'note_off', 'control_change'):
                try:
                    midi_queue.put_nowait({
                        'type': event.message_type,
                        'ch':   event.channel,
                        'note': getattr(event, 'note', 0),
                        'vel':  getattr(event, 'velocity', 0),
                        'ctrl': getattr(event, 'control', 0),
                        'val':  getattr(event, 'value', 0),
                    })
                except Exception:
                    pass

        seq._send_midi = _hooked_send
        seq._pomski_hooked = True

    async def _broadcast_loop(self) -> None:

        while True:
            await asyncio.sleep(0.1)
            
            if not self._clients:
                continue
            
            comp = self.composition_ref()
            if comp is None:
                break

            # Start live bridge now if it hasn't been started yet
            # (must happen inside the running event loop, not before play())
            live = getattr(comp, '_live_bridge', None)
            if live is not None and not getattr(live, '_started', False):
                live.start()
                # Also inject into REPL namespace now that start() has been called
                live_server = getattr(comp, '_live_server', None)
                if live_server is not None and isinstance(live_server._namespace, dict):
                    live_server._namespace['live'] = live

            # Try to hook midi now if not yet hooked (sequencer may not exist at start time)
            self._register_midi_hook()

            try:
                state = self._get_state(comp)
                message = json.dumps(state)
                websockets.broadcast(self._clients, message)
            except Exception as e:
                import traceback
                logger.error(f"Error broadcasting UI state: {e}\n{traceback.format_exc()}")

            # Drain MIDI event queue and forward to clients (consolidated from
            # the former 1ms polling loop — 100ms latency is imperceptible for
            # a visual activity monitor).
            midi_events: typing.List[typing.Dict] = []
            try:
                while True:
                    midi_events.append(self._midi_queue.get_nowait())
            except queue.Empty:
                pass
            for event in midi_events:
                try:
                    websockets.broadcast(self._clients, json.dumps({'midi': event}))
                except Exception:
                    pass

            # Drain builder error queue and forward to all clients as log messages.
            try:
                while True:
                    err_msg = self._builder_error_queue.get_nowait()
                    websockets.broadcast(self._clients, json.dumps({'log': err_msg, 'level': 'err'}))
            except queue.Empty:
                pass

    def _get_state(self, comp: typing.Any) -> typing.Dict[str, typing.Any]:

        state: typing.Dict[str, typing.Any] = {
            "bpm": comp.bpm,
            "section": None,
            "chord": None,
            "patterns": [],
            "signals": {},
            "playhead_pulse": 0,
            "pulses_per_beat": 24,
            "key": comp.key,
            "section_bar": None,
            "section_bars": None,
            "next_section": None,
            "global_bar": 0,
            "global_beat": 0
        }
        
        if comp.sequencer:
            state["playhead_pulse"] = comp.sequencer.pulse_count
            state["pulses_per_beat"] = comp.sequencer.pulses_per_beat
            state["global_bar"] = max(0, comp.sequencer.current_bar) + 1
            state["global_beat"] = max(0, comp.sequencer.current_beat) + 1
        
        if comp.form_state:
            section_info = comp.form_state.get_section_info()
            if section_info:
                state["section"] = section_info.name
                state["section_bar"] = section_info.bar + 1
                state["section_bars"] = section_info.bars
                state["next_section"] = section_info.next_section
                
        if comp.harmonic_state and comp.harmonic_state.current_chord:
            state["chord"] = comp.harmonic_state.current_chord.name()
            
        current_bar = state["global_bar"]
        if current_bar != self._last_bar:
            self._last_bar = current_bar
            self._cached_patterns = []
            for name, pattern in comp.running_patterns.items():
                pattern_data: typing.Dict[str, typing.Any] = {
                    "name": name,
                    "muted": getattr(pattern, "_muted", False),
                    "length_pulses": int(pattern.length * state["pulses_per_beat"]),
                    "drum_map": getattr(pattern, "_drum_note_map", None),
                    "notes": []
                }
                if hasattr(pattern, "steps"):
                    for pulse, step in pattern.steps.items():
                        for note in getattr(step, "notes", []):
                            pattern_data["notes"].append({
                                "p": note.pitch,
                                "s": pulse,
                                "d": note.duration,
                                "v": note.velocity
                            })
                self._cached_patterns.append(pattern_data)
        state["patterns"] = self._cached_patterns

        def _extract_val(val: typing.Any) -> typing.Optional[float]:
            if hasattr(val, "current"):
                try:
                    return float(val.current)
                except Exception:
                    pass
            if callable(getattr(val, "value", None)):
                try:
                    return float(val.value())
                except Exception:
                    pass
            elif hasattr(val, "value"):
                try:
                    return float(val.value)
                except Exception:
                    pass
            elif type(val) in (int, float, bool):
                return float(val)
            return None

        # Conductor LFOs are time-varying — always recompute.
        if comp.conductor and comp.conductor._signals:
            beat_time = (comp.sequencer.pulse_count / comp.sequencer.pulses_per_beat
                         if comp.sequencer else 0.0)
            for name, signal in comp.conductor._signals.items():
                try:
                    state["signals"][name] = float(signal.value_at(beat_time))
                except Exception:
                    pass

        # comp.data: snapshot primitive values and only re-extract when they
        # change.  Non-primitive entries (objects with .current / .value) are
        # re-extracted every tick because their internal state may vary even
        # when their identity is stable.
        snap = frozenset(
            (k, v) for k, v in comp.data.items() if type(v) in (int, float, bool)
        )
        if snap != self._data_snap:
            self._data_snap = snap
            new_cache: typing.Dict[str, float] = {}
            for name, val in comp.data.items():
                if type(val) in (int, float, bool):
                    new_cache[name] = float(val)
            self._data_signals_cache = new_cache
        state["signals"].update(self._data_signals_cache)

        # Non-primitive extractable values in comp.data (e.g. feed objects).
        for name, val in comp.data.items():
            if type(val) not in (int, float, bool):
                extracted = _extract_val(val)
                if extracted is not None:
                    state["signals"][name] = extracted

        state["link"] = self._get_link_state(comp)

        live = getattr(comp, '_live_bridge', None)
        state["live"] = live.get_ui_state() if live is not None else {"connected": False, "tracks": [], "scenes": [], "clip_grid": []}

        return state

    def push_builder_error(self, pattern_name: str, tb: str) -> None:

        """Queue a builder error to be forwarded to all connected web clients."""

        try:
            self._builder_error_queue.put_nowait({"name": pattern_name, "tb": tb})
        except Exception:
            pass

    def stop(self) -> None:

        if self._broadcast_task:
            self._broadcast_task.cancel()
        if self._ws_server:
            self._ws_server.close()
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._ws_server.wait_closed())
            except RuntimeError:
                pass
