import asyncio
import http.server
import json
import logging
import os
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
                pass # Suppress HTTP access logging to keep the console clean

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

    def _get_midi_devices (self) -> typing.Dict[str, typing.List[str]]:
        """Return available MIDI input and output port names via mido."""
        try:
            import mido
            return {
                "inputs":  mido.get_input_names(),
                "outputs": mido.get_output_names(),
            }
        except Exception:
            return {"inputs": [], "outputs": []}

    def _get_link_state (self, comp: typing.Any) -> typing.Dict[str, typing.Any]:
        """Return current Ableton Link state if aalink is present and attached."""
        link = getattr(comp, '_link', None)
        if link is None:
            return {"available": False, "enabled": False, "tempo": None, "peers": 0}
        try:
            return {
                "available": True,
                "enabled":   bool(link.enabled),
                "tempo":     round(float(link.tempo), 2),
                "peers":     int(link.peers) if hasattr(link, 'peers') else 0,
            }
        except Exception:
            return {"available": True, "enabled": False, "tempo": None, "peers": 0}

    async def _forward_repl (self, code: str, websocket: websockets.asyncio.server.ServerConnection) -> None:
        """Forward a code string to the live coding TCP server (port 5555) and relay the response."""
        try:
            reader, writer = await asyncio.open_connection('127.0.0.1', 5555)
            writer.write((code + '\x04').encode('utf-8'))
            await writer.drain()

            response = b''
            while True:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=5.0)
                if not chunk:
                    break
                response += chunk
                if b'\x04' in chunk:
                    break

            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

            result = response.replace(b'\x04', b'').decode('utf-8', errors='replace').strip()
            # The live server returns raw traceback text on error - detect and re-route it
            if result.startswith("Traceback ") or result.startswith("SyntaxError") or result.startswith("  File "):
                reply = {"repl_error": result}
            else:
                reply = {"repl_result": result or "OK"}

        except asyncio.TimeoutError:
            reply = {"repl_error": "Timeout - live server did not respond"}
        except ConnectionRefusedError:
            reply = {"repl_error": "Live server not running - call composition.live() before composition.play()"}
        except Exception as e:
            reply = {"repl_error": str(e)}

        try:
            await websocket.send(json.dumps(reply))
        except Exception:
            pass

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

                    elif action == 'repl':
                        code = cmd.get('code', '').strip()
                        if code:
                            asyncio.create_task(self._forward_repl(code, websocket))

                    elif action == 'link_toggle':
                        link = getattr(comp, '_link', None)
                        if link is not None:
                            link.enabled = not link.enabled
                            await websocket.send(json.dumps({"link_state": self._get_link_state(comp)}))

                    elif action == 'get_midi_devices':
                        await websocket.send(json.dumps({"midi_devices": self._get_midi_devices()}))

                    elif action == 'set_midi_input':
                        # Reopen the live input port via sequencer.reopen_input().
                        # Also updates comp._input_device so live_info() stays accurate.
                        device = cmd.get('device', '').strip()
                        if device:
                            try:
                                seq = comp.sequencer
                                seq.reopen_input(device)
                                comp._input_device = seq.input_device_name  # reflect resolved name
                                await websocket.send(json.dumps({
                                    "repl_result": f"MIDI input: {seq.input_device_name}"
                                }))
                            except Exception as e:
                                await websocket.send(json.dumps({"repl_error": f"MIDI input failed: {e}"}))

                    elif action == 'set_midi_output':
                        # Reopen the live output port via sequencer.reopen_output().
                        # Also updates comp.output_device so it's consistent.
                        device = cmd.get('device', '').strip()
                        if device:
                            try:
                                seq = comp.sequencer
                                seq.reopen_output(device)
                                comp.output_device = seq.output_device_name  # reflect resolved name
                                await websocket.send(json.dumps({
                                    "repl_result": f"MIDI output: {seq.output_device_name}"
                                }))
                            except Exception as e:
                                await websocket.send(json.dumps({"repl_error": f"MIDI output failed: {e}"}))

                except Exception as e:
                    logger.warning(f"WebUI command error: {e}")

        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._clients.remove(websocket)

    async def _start_ws_server (self) -> None:

        try:
            self._ws_server = await websockets.asyncio.server.serve(self._handle_client, "0.0.0.0", self.ws_port)
            self._broadcast_task = asyncio.create_task(self._broadcast_loop())
        except Exception as e:
            logger.error(f"WebSocket server error: {e}")

    async def _broadcast_loop (self) -> None:

        while True:
            # Broadcast 10 times a second to keep UI snappy without bogging down the loop
            await asyncio.sleep(0.1)
            
            if not self._clients:
                continue
            
            comp = self.composition_ref()
            if comp is None:
                break

            try:
                state = self._get_state(comp)
                message = json.dumps(state)
                websockets.broadcast(self._clients, message)
            except Exception as e:
                import traceback
                logger.error(f"Error broadcasting UI state: {e}\n{traceback.format_exc()}")

    def _get_state (self, comp: typing.Any) -> typing.Dict[str, typing.Any]:

        state: typing.Dict[str, typing.Any] = {
            "bpm":             comp.bpm,
            "section":         None,
            "chord":           None,
            "patterns":        [],
            "signals":         {},
            "playhead_pulse":  0,
            "pulses_per_beat": 24,
            "key":             comp.key,
            "section_bar":     None,
            "section_bars":    None,
            "next_section":    None,
            "global_bar":      0,
            "global_beat":     0,
            "link":            self._get_link_state(comp),
        }
        
        if comp.sequencer:
            state["playhead_pulse"]  = comp.sequencer.pulse_count
            state["pulses_per_beat"] = comp.sequencer.pulses_per_beat
            state["global_bar"]      = max(0, comp.sequencer.current_bar) + 1
            state["global_beat"]     = max(0, comp.sequencer.current_beat) + 1
        
        if comp.form_state:
            section_info = comp.form_state.get_section_info()
            if section_info:
                state["section"]      = section_info.name
                state["section_bar"]  = section_info.bar + 1
                state["section_bars"] = section_info.bars
                state["next_section"] = section_info.next_section
                
        if comp.harmonic_state and comp.harmonic_state.current_chord:
            state["chord"] = comp.harmonic_state.current_chord.name()
            
        current_bar = state["global_bar"]
        if current_bar != self._last_bar:
            self._last_bar        = current_bar
            self._cached_patterns = []
            for name, pattern in comp.running_patterns.items():
                pattern_data: typing.Dict[str, typing.Any] = {
                    "name":          name,
                    "muted":         getattr(pattern, "_muted", False),
                    "length_pulses": int(pattern.length * state["pulses_per_beat"]),
                    "drum_map":      getattr(pattern, "_drum_note_map", None),
                    "notes":         []
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

        if comp.conductor:
            beat_time = comp.sequencer.pulse_count / comp.sequencer.pulses_per_beat if comp.sequencer else 0.0
            for name, signal in comp.conductor._signals.items():
                try:
                    state["signals"][name] = float(signal.value_at(beat_time))
                except Exception:
                    pass
                    
        for name, val in comp.data.items():
            extracted = _extract_val(val)
            if extracted is not None:
                state["signals"][name] = extracted

        return state

    def stop (self) -> None:

        if self._broadcast_task:
            self._broadcast_task.cancel()
        if self._ws_server:
            self._ws_server.close()
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._ws_server.wait_closed())
            except RuntimeError:
                pass
