"""
live_bridge.py — POMSKI ↔ Ableton Live bridge via AbletonOSC

Requires:
    pip install python-osc

Requires AbletonOSC remote script installed in Live:
    Windows: C:\\Users\\[you]\\Documents\\Ableton\\User Library\\Remote Scripts\\AbletonOSC
    macOS:   ~/Music/Ableton/User Library/Remote Scripts/AbletonOSC
    Then: Live Preferences → Link/Tempo/MIDI → Control Surface → AbletonOSC
    Live's status bar should confirm: "AbletonOSC: Listening for OSC on port 11000"
"""

import asyncio
import logging
import socket
import time
import typing
import weakref

logger = logging.getLogger(__name__)

OSC_SEND_PORT  = 11000
OSC_RECV_PORT  = 11001
OSC_HOST       = "127.0.0.1"
RETRY_INTERVAL = 5.0

CLIP_EMPTY     = 0
CLIP_STOPPED   = 1
CLIP_PLAYING   = 2
CLIP_TRIGGERED = 3


class _RecvProtocol(asyncio.DatagramProtocol):
    """Plain asyncio UDP protocol — no pythonosc server layer."""

    def __init__(self, handler: typing.Callable) -> None:
        self._handler = handler

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        try:
            from pythonosc.osc_message import OscMessage
            msg = OscMessage(data)
            self._handler(msg.address, *msg.params)
        except Exception as e:
            logger.debug(f"LiveBridge: bad OSC packet from {addr}: {e}")

    def error_received(self, exc: Exception) -> None:
        logger.debug(f"LiveBridge: UDP error: {exc}")

    def connection_lost(self, exc: Exception) -> None:
        pass


class LiveBridge:
    """
    Bidirectional OSC bridge between POMSKI and Ableton Live.
    Exposes a clip launcher grid to the POMSKI web UI.
    Silent if Live is not running; reconnects automatically every 5s.
    """

    def __init__(
        self,
        composition: typing.Any,
        host: str = OSC_HOST,
        send_port: int = OSC_SEND_PORT,
        recv_port: int = OSC_RECV_PORT,
        clyphx_osc_port: int = 7005,
    ) -> None:
        self._comp_ref  = weakref.ref(composition)
        self._host      = host
        self._send_port = send_port
        self._recv_port = recv_port
        self.clyphx_osc_port = clyphx_osc_port

        self._send_sock: typing.Optional[socket.socket] = None  # plain UDP send
        self._pending:   typing.Dict[str, asyncio.Future] = {}
        self._watches:   typing.Dict[str, str] = {}

        self.tracks:    typing.List[str] = []
        self.scenes:    typing.List[str] = []
        self.clip_grid: typing.List[typing.List[int]] = []

        self._connected = False
        self._started   = False
        self._loop: typing.Optional[asyncio.AbstractEventLoop] = None

    # ─── startup ──────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Call after composition.live(), before composition.play()."""
        if self._started:
            return
        self._started = True
        # Plain socket for sending — same as the working test script
        self._send_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        asyncio.get_event_loop().call_soon(lambda: asyncio.ensure_future(self._run()))

    # ─── transport ────────────────────────────────────────────────────────────

    def play(self)           -> None: self._send("/live/song/start_playing")
    def stop_transport(self) -> None: self._send("/live/song/stop_playing")

    # ─── clips ────────────────────────────────────────────────────────────────

    def clip_play(self, track: int, clip: int)  -> None: self._send("/live/clip_slot/fire", track, clip)
    def clip_stop(self, track: int, clip: int)  -> None: self._send("/live/clip_slot/stop", track, clip)
    def track_stop(self, track: int)            -> None: self._send("/live/track/stop_all_clips", track)
    def scene_play(self, scene: int)            -> None: self._send("/live/scene/fire", scene)

    # ─── mixer ────────────────────────────────────────────────────────────────

    def track_volume(self, track: int, value: float) -> None:
        self._send("/live/track/set/volume", track, float(value))

    def track_pan(self, track: int, value: float) -> None:
        self._send("/live/track/set/panning", track, float(value))

    def track_mute(self, track: int, muted: bool = True) -> None:
        self._send("/live/track/set/mute", track, int(muted))

    def track_send(self, track: int, send: int, value: float) -> None:
        self._send("/live/track/set/send", track, send, float(value))

    # ─── devices ──────────────────────────────────────────────────────────────

    def device_param(self, track: int, device: int, param: int, value: float) -> None:
        """Normalised value 0.0–1.0, mapped to real range by Live."""
        self._send("/live/device/set/parameter/value", track, device, param, float(value))

    # ─── watch ────────────────────────────────────────────────────────────────

    def watch(self, osc_path: str, data_key: typing.Optional[str] = None) -> None:
        """
        Poll osc_path every ~500ms and write into composition.data.
        Example: live.watch("track/0/volume") → composition.data["live_track_0_volume"]
        """
        address = self._full_address(osc_path)
        if data_key is None:
            data_key = "live_" + osc_path.strip("/").replace("/", "_").replace("live_", "", 1)
        self._watches[address] = data_key

    # ─── raw OSC ──────────────────────────────────────────────────────────────

    def send(self, address: str, *args) -> None:
        self._send(address, *args)


    # ─── ClyphX Pro ───────────────────────────────────────────────────────────

    def clyphx(self, action: str) -> None:
        """
        Send an arbitrary ClyphX Pro action string via an X-Clip trigger track.

        Uses a dedicated hidden MIDI track (_POMSKI_CLYPHX). On first call the
        track and a 1-bar clip are created automatically. On every subsequent
        call the clip is renamed to the new action and fired — ClyphX Pro
        intercepts the launch and executes the action list.

        This approach supports fully dynamic, arbitrary action strings without
        any pre-configuration in ClyphX Pro's settings files.

        Examples:
            live.clyphx("BPM 120")
            live.clyphx("1/MUTE ON")
            live.clyphx("1/DEV(1) ON ; 2/ARM ON")
            live.clyphx("(PSEQ) 1/MUTE ; 2/MUTE ; 3/MUTE")
        """
        clip_name = f"[] {action}"
        if self._loop is not None:
            asyncio.run_coroutine_threadsafe(self._clyphx_fire(clip_name), self._loop)
        else:
            logger.warning("ClyphX: bridge not yet started")

    def clyphx_osc(self, address: str, value: float = 1.0) -> None:
        """
        Trigger a pre-defined X-OSC address in ClyphX Pro (port 7005).

        X-OSC addresses are defined in ClyphX Pro's X-OSC.txt file. Each
        address maps to a fixed Action List that ClyphX Pro executes when
        it receives a non-zero value on that address.

        This is faster and cleaner than clyphx() for frequently-used actions
        since it bypasses AbletonOSC entirely and talks directly to ClyphX Pro.

        Requires entries in X-OSC.txt like:
            MY_ACTION | BPM 120
            MUTE_1    | 1/MUTE

        Usage:
            live.clyphx_osc("/MY_ACTION")       # trigger with value 1
            live.clyphx_osc("/MUTE_1", 1)       # on
            live.clyphx_osc("/MUTE_1", 0)       # off (if action has stop list)

        Default ClyphX Pro OSC port is 7005 (change in Preferences.txt if needed).
        """
        self._clyphx_osc_send(address, value)

    def _clyphx_osc_send(self, address: str, value: float) -> None:
        """Send a raw OSC message directly to ClyphX Pro on port 7005."""
        try:
            from pythonosc.udp_client import SimpleUDPClient
            client = SimpleUDPClient("127.0.0.1", self.clyphx_osc_port)
            client.send_message(address, float(value))
        except Exception as e:
            logger.warning(f"ClyphX OSC send failed — {e}")

    async def _clyphx_fire(self, clip_name: str) -> None:
        """Create/reuse the dedicated ClyphX trigger track, rename clip, fire."""
        try:
            track_idx = await self._clyphx_get_or_create_track()
            if track_idx is None:
                logger.warning("ClyphX: could not get trigger track")
                return

            has = await self._query("/live/clip_slot/get/has_clip", track_idx, 0, timeout=2.0)
            has_clip = has and len(has) >= 3 and bool(has[2])

            if not has_clip:
                self._send("/live/clip_slot/create_clip", track_idx, 0, 4.0)
                await asyncio.sleep(0.15)

            self._send("/live/clip/set/name", track_idx, 0, clip_name)
            await asyncio.sleep(0.05)
            self._send("/live/clip_slot/fire", track_idx, 0)

        except Exception as e:
            logger.warning(f"ClyphX: fire failed — {e}")

    async def _clyphx_get_or_create_track(self) -> typing.Optional[int]:
        """Return index of the ClyphX trigger track, creating it if needed."""
        TRACK_NAME = "_POMSKI_CLYPHX"

        names = await self._query("/live/song/get/track_names", timeout=2.0)
        if names:
            for i, name in enumerate(names):
                if str(name) == TRACK_NAME:
                    return i

        self._send("/live/song/create_midi_track", -1)
        await asyncio.sleep(0.3)

        names = await self._query("/live/song/get/track_names", timeout=2.0)
        if not names:
            return None

        new_idx = len(names) - 1
        self._send("/live/track/set/name", new_idx, TRACK_NAME)
        self._send("/live/track/set/mute", new_idx, 1)
        await asyncio.sleep(0.1)
        return new_idx


    # ─── state for web_ui ─────────────────────────────────────────────────────

    def get_ui_state(self) -> dict:
        return {
            "connected": self._connected,
            "tracks":    self.tracks,
            "scenes":    self.scenes,
            "clip_grid": self.clip_grid,
        }

    @property
    def connected(self) -> bool:
        return self._connected

    def __repr__(self) -> str:
        s = "connected" if self._connected else "disconnected"
        return f"<LiveBridge {s} tracks={self.tracks}>"

    # ─── internal: main loop ──────────────────────────────────────────────────

    async def _run(self) -> None:
        """Bind recv endpoint then enter connect/poll loop."""
        loop = asyncio.get_event_loop()
        self._loop = loop  # store so clyphx() can schedule from any thread
        logger.warning("LiveBridge: _run() started")
        print("LiveBridge: _run() started", flush=True)

        # Bind a plain asyncio UDP endpoint on recv_port for incoming replies
        try:
            recv_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            recv_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            recv_sock.bind(("0.0.0.0", self._recv_port))
            recv_sock.setblocking(False)

            await loop.create_datagram_endpoint(
                lambda: _RecvProtocol(self._osc_recv),
                sock=recv_sock,
            )
            logger.warning(f"LiveBridge: recv socket bound on port {self._recv_port}")
            print(f"LiveBridge: recv socket bound on port {self._recv_port}", flush=True)
        except Exception as e:
            logger.warning(f"LiveBridge: cannot bind recv port {self._recv_port} — {e}")
            print(f"LiveBridge: CANNOT BIND PORT {self._recv_port}: {e}", flush=True)
            return

        while True:
            if not self._connected:
                await self._try_connect()
                await asyncio.sleep(RETRY_INTERVAL)
            else:
                await self._poll()
                await asyncio.sleep(0.5)

    async def _try_connect(self) -> None:
        try:
            result = await self._query("/live/test", timeout=2.0)
            if result is None:
                return

            # Track names — plain tuple of strings, no ID prefix
            names = await self._query("/live/song/get/track_names", timeout=2.0)
            self.tracks = [str(n) for n in names] if names else []

            # num_scenes is reliable even when scene names are blank
            num_scenes = await self._query("/live/song/get/num_scenes", timeout=2.0)
            n_scenes = int(num_scenes[0]) if num_scenes else 0

            scene_names = await self._query("/live/song/get/scene_names", timeout=2.0)
            if scene_names:
                self.scenes = [str(s) if s else str(i+1) for i, s in enumerate(scene_names)]
            else:
                self.scenes = [str(i+1) for i in range(n_scenes)]

            self.clip_grid = [[CLIP_EMPTY] * len(self.scenes) for _ in self.tracks]
            self._connected = True
            print(f"LiveBridge: connected — {len(self.tracks)} tracks, {len(self.scenes)} scenes", flush=True)
            logger.info(f"LiveBridge: connected — {len(self.tracks)} tracks, {len(self.scenes)} scenes")
            await self._refresh_clip_grid()

        except Exception as e:
            print(f"LiveBridge: connect failed — {e}", flush=True)
            logger.debug(f"LiveBridge: connect attempt failed — {e}")

    async def _poll(self) -> None:
        try:
            # Re-query track/scene counts so additions/removals are reflected live
            names = await self._query("/live/song/get/track_names", timeout=2.0)
            if names is not None:
                self.tracks = [str(n) for n in names]

            num_scenes = await self._query("/live/song/get/num_scenes", timeout=1.0)
            if num_scenes is not None:
                n_scenes = int(num_scenes[0])
                scene_names = await self._query("/live/song/get/scene_names", timeout=1.0)
                if scene_names:
                    self.scenes = [str(s) if s else str(i+1) for i, s in enumerate(scene_names)]
                else:
                    self.scenes = [str(i+1) for i in range(n_scenes)]

            await self._refresh_clip_grid()
        except Exception:
            self._connected = False
            logger.warning("LiveBridge: lost connection to Live — will retry")
            return

        comp = self._comp_ref()
        if comp is None:
            return
        for address, key in list(self._watches.items()):
            try:
                result = await self._query(address, timeout=0.5)
                if result is not None:
                    comp.data[key] = float(result[0]) if len(result) == 1 else list(result)
            except Exception:
                pass

    async def _refresh_clip_grid(self) -> None:
        T = len(self.tracks)
        S = len(self.scenes)
        if not T or not S:
            return

        # Single bulk query for all tracks/clips:
        # track_data returns: track_name, clip_0_has_clip, clip_0_is_playing, clip_0_is_triggered,
        #                                  clip_1_has_clip, ...  for each track
        # Note: all clip getters return (track_id, clip_id, value) — value is at index 2
        result = await self._query(
            "/live/song/get/track_data",
            0, T,
            "track.name",
            "clip_slot.has_clip",
            "clip.is_playing",
            "clip.is_triggered",
            timeout=5.0
        )

        if result is None:
            # Bulk query not supported or timed out — fall back to per-slot queries
            await self._refresh_clip_grid_slow()
            return

        # Parse flat result list:
        # [t0_name, t0_c0_has, t0_c0_playing, t0_c0_triggered, t0_c1_has, ..., t1_name, ...]
        vals = list(result)
        props_per_clip = 3   # has_clip, is_playing, is_triggered
        stride = 1 + S * props_per_clip  # 1 track name + S clips * 3 props each

        new_grid: typing.List[typing.List[int]] = []
        for t in range(T):
            base = t * stride
            if base >= len(vals):
                new_grid.append([CLIP_EMPTY] * S)
                continue
            row: typing.List[int] = []
            for c in range(S):
                clip_base = base + 1 + c * props_per_clip
                if clip_base + 2 >= len(vals):
                    row.append(CLIP_EMPTY)
                    continue
                has      = bool(vals[clip_base])
                playing  = bool(vals[clip_base + 1])
                triggered= bool(vals[clip_base + 2])
                if not has:
                    row.append(CLIP_EMPTY)
                elif playing:
                    row.append(CLIP_PLAYING)
                elif triggered:
                    row.append(CLIP_TRIGGERED)
                else:
                    row.append(CLIP_STOPPED)
            new_grid.append(row)
        self.clip_grid = new_grid

    async def _refresh_clip_grid_slow(self) -> None:
        """Per-slot fallback. Also fixes (track_id, clip_id, value) index offset."""
        T = len(self.tracks)
        S = len(self.scenes)
        new_grid: typing.List[typing.List[int]] = []
        for t in range(T):
            row: typing.List[int] = []
            for c in range(S):
                has = await self._query("/live/clip_slot/get/has_clip", t, c, timeout=0.3)
                # Returns (track_id, clip_id, has_clip) — value at index 2
                if not has or len(has) < 3 or not has[2]:
                    row.append(CLIP_EMPTY)
                    continue
                playing   = await self._query("/live/clip/get/is_playing",  t, c, timeout=0.3)
                triggered = await self._query("/live/clip/get/is_triggered", t, c, timeout=0.3)
                if playing and len(playing) >= 3 and playing[2]:
                    row.append(CLIP_PLAYING)
                elif triggered and len(triggered) >= 3 and triggered[2]:
                    row.append(CLIP_TRIGGERED)
                else:
                    row.append(CLIP_STOPPED)
            new_grid.append(row)
        self.clip_grid = new_grid

    # ─── internal: OSC send/recv ──────────────────────────────────────────────

    def _send(self, address: str, *args) -> None:
        if self._send_sock is None:
            return
        try:
            from pythonosc.osc_message_builder import OscMessageBuilder
            builder = OscMessageBuilder(address=address)
            for arg in args:
                builder.add_arg(int(arg) if isinstance(arg, bool) else arg)
            self._send_sock.sendto(
                builder.build().dgram,
                (self._host, self._send_port)
            )
        except Exception as e:
            logger.debug(f"LiveBridge: send error {address}: {e}")

    def _osc_recv(self, address: str, *args) -> None:
        logger.warning(f"LiveBridge: _osc_recv {address} {args}")
        print(f"LiveBridge: _osc_recv {address} {args}", flush=True)
        key = next((k for k in self._pending if k == address or k.startswith(address + ":")), None)
        if key is not None:
            fut = self._pending.pop(key)
            if not fut.done():
                fut.get_loop().call_soon_threadsafe(fut.set_result, args)

    async def _query(self, address: str, *args, timeout: float = 2.0) -> typing.Optional[tuple]:
        if self._send_sock is None:
            return None
        loop = asyncio.get_event_loop()
        key = f"{address}:{time.monotonic_ns()}"
        fut: asyncio.Future = loop.create_future()
        self._pending[key] = fut
        try:
            self._send(address, *args)
            return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(key, None)
            return None

    def _full_address(self, path: str) -> str:
        return path if path.startswith("/live/") else "/live/" + path
