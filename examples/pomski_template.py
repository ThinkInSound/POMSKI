import sys
import os
import traceback
import logging
import faulthandler
import subprocess
import threading
import asyncio
import socket as _socket_mod
import tempfile
import weakref

# ── Log directory ─────────────────────────────────────────────────────────────
if getattr(sys, 'frozen', False):
    if sys.platform == 'darwin':
        _LOG_DIR = os.path.join(os.path.expanduser('~'), 'Library', 'Logs', 'POMSKI')
    else:
        _LOG_DIR = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'POMSKI')
    os.makedirs(_LOG_DIR, exist_ok=True)
else:
    _LOG_DIR = '.'
_LOG_PATH = os.path.join(_LOG_DIR, 'pomski.log')
_FAULT_PATH = os.path.join(_LOG_DIR, 'fault.log')

# ── Finder-launch MIDI picker hand-off (macOS, frozen builds only) ─────────────
# pomski_mac.spec's wrapper script opens a fresh Terminal window (and drops a
# marker file here) only when launched with no controlling terminal (i.e. from
# Finder) — that Terminal window exists solely so the MIDI-output prompt below
# has a tty. Once a device is picked, this process hands off to a fully
# detached copy of itself (no controlling terminal at all) and exits — so the
# window can close later with no "still running" warning and no risk of
# SIGHUP killing the real app (see _close_launch_terminal() further down,
# which the detached copy calls once its own window is on screen).
_WRAPPER_MARKER = os.path.join(_LOG_DIR, '.launched_via_wrapper')
_launched_via_wrapper = False
_marker_seen = os.path.exists(_WRAPPER_MARKER)
if getattr(sys, 'frozen', False) and sys.platform == 'darwin' and _marker_seen:
    _launched_via_wrapper = True
    try:
        os.remove(_WRAPPER_MARKER)
    except OSError:
        pass

# Temporary diagnostics for the picker/relaunch hand-off — safe to remove
# once this is confirmed working across launches.
def _debug(msg: str) -> None:
    try:
        import datetime as _dt
        with open(os.path.join(_LOG_DIR, 'picker_debug.log'), 'a', encoding='utf-8') as _pf:
            _pf.write(f"{_dt.datetime.now().isoformat()} pid={os.getpid()} {msg}\n")
    except Exception:
        pass

_debug(
    f"startup frozen={getattr(sys,'frozen',False)} platform={sys.platform} "
    f"marker_path={_WRAPPER_MARKER} marker_seen={_marker_seen} "
    f"launched_via_wrapper={_launched_via_wrapper} "
    f"stdin_isatty={sys.stdin.isatty()} "
    f"POMSKI_RELAUNCHED={os.environ.get('POMSKI_RELAUNCHED')!r} "
    f"POMSKI_LAUNCH_TTY={os.environ.get('POMSKI_LAUNCH_TTY')!r}"
)

def _run_midi_picker_and_relaunch() -> None:
    try:
        import mido
        outputs = mido.get_output_names()
    except Exception:
        outputs = []

    device = None
    if len(outputs) == 1:
        device = outputs[0]
    elif len(outputs) > 1:
        print("\nAvailable MIDI output devices:\n")
        for i, name in enumerate(outputs, 1):
            print(f"  {i}. {name}")
        print()
        while True:
            try:
                choice = int(input(f"Select a device (1-{len(outputs)}): "))
                if 1 <= choice <= len(outputs):
                    device = outputs[choice - 1]
                    break
            except EOFError:
                device = outputs[0]
                break
            except ValueError:
                pass

    env = dict(os.environ)
    env['POMSKI_RELAUNCHED'] = '1'
    if device:
        env['POMSKI_MIDI_OUTPUT'] = device
    try:
        env['POMSKI_LAUNCH_TTY'] = os.ttyname(sys.stdin.fileno())
    except OSError:
        pass

    print("\nStarting POMSKI…\n")
    child = subprocess.Popen(
        [sys.executable] + sys.argv[1:],
        env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    _debug(f"picker: outputs={outputs} device={device!r} spawned_child_pid={child.pid} exiting")
    os._exit(0)

_debug(
    f"gate: will_run_picker={_launched_via_wrapper and sys.stdin.isatty() and os.environ.get('POMSKI_RELAUNCHED') != '1'}"
)
if (_launched_via_wrapper and sys.stdin.isatty()
        and os.environ.get('POMSKI_RELAUNCHED') != '1'):
    _run_midi_picker_and_relaunch()  # never returns

# Console handler: rich colour-codes by level (DEBUG dim, INFO default,
# WARNING yellow, ERROR/CRITICAL red). File log stays plain text.
_file_handler = logging.FileHandler(_LOG_PATH, encoding='utf-8')
_file_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
try:
    from rich.logging import RichHandler
    _console_handler = RichHandler(show_path=False, rich_tracebacks=True)
    _console_handler.setFormatter(logging.Formatter('%(name)s: %(message)s'))
except Exception:
    _console_handler = logging.StreamHandler(sys.stdout)
    _console_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))

# Console shows INFO+ only; full DEBUG still goes to pomski.log.
_console_handler.setLevel(logging.INFO)

logging.basicConfig(
    level=logging.DEBUG,
    handlers=[_file_handler, _console_handler],
)

# Chatty third-party loggers: websockets logs every frame/ping at DEBUG.
for _noisy in ('websockets', 'websockets.server', 'asyncio', 'mido'):
    logging.getLogger(_noisy).setLevel(logging.INFO)
if getattr(sys, 'frozen', False):
    sys.stderr = open(_LOG_PATH, 'a', encoding='utf-8', buffering=1)

_fault_file = open(_FAULT_PATH, 'w', buffering=1)
faulthandler.enable(file=_fault_file)

# ── Crash logger ──────────────────────────────────────────────────────────────
def _write_crash_log() -> None:
    log_path = os.path.join(_LOG_DIR, 'crash.log')
    with open(log_path, 'w') as f:
        traceback.print_exc(file=f)
    print(f'\n[CRASH] Error log written to: {log_path}')
    traceback.print_exc()
    input('\nPress Enter to exit...')

def _asyncio_exception_handler(loop, context):
    msg = context.get('exception', context['message'])
    logging.error(f'Asyncio error: {msg}', exc_info=context.get('exception'))

# ── Find system Python ────────────────────────────────────────────────────────
def _find_python_exe() -> str | None:
    if sys.platform != 'win32':
        return 'python3'
    try:
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for ver in ('3.13', '3.12', '3.11', '3.10', '3.9'):
                for key_path in (
                    rf'SOFTWARE\Python\PythonCore\{ver}\InstallPath',
                    rf'SOFTWARE\WOW6432Node\Python\PythonCore\{ver}\InstallPath',
                ):
                    try:
                        with winreg.OpenKey(hive, key_path) as k:
                            try:
                                exe, _ = winreg.QueryValueEx(k, 'ExecutablePath')
                                if exe and os.path.isfile(exe):
                                    return exe
                            except FileNotFoundError:
                                pass
                            install_dir, _ = winreg.QueryValueEx(k, '')
                            candidate = os.path.join(install_dir.rstrip('\\'), 'python.exe')
                            if os.path.isfile(candidate):
                                return candidate
                    except OSError:
                        continue
    except Exception:
        pass
    return 'python'


# ── Ableton Link proxy ────────────────────────────────────────────────────────
class _LinkProxy:
    """
    Stands in for aalink.Link in the main process.
    Forwards reads/writes to aalink_bridge.py via a TCP socket.
    """
    def __init__(self):
        self._tempo     = 120.0
        self._enabled   = False
        self._num_peers = 0
        self._conn: _socket_mod.socket | None = None
        self._run_event = threading.Event()
        self._run_event.set()  # starts in "allowed to run" state

    @property
    def enabled(self):
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        value = bool(value)
        self._enabled = value
        if value:
            # Let _link_service reconnect.
            self._run_event.set()
        else:
            # Block _link_service from reconnecting, then close the
            # current bridge connection so Ableton loses the peer immediately.
            self._run_event.clear()
            self._num_peers = 0
            conn = self._conn
            self._conn = None
            if conn is not None:
                try:
                    conn.shutdown(_socket_mod.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

    @property
    def tempo(self):
        return self._tempo

    @tempo.setter
    def tempo(self, value):
        self._tempo = float(value)
        self._send(f'T{value:.4f}\n')

    @property
    def num_peers(self):
        return self._num_peers

    def _send(self, msg: str) -> None:
        try:
            if self._conn:
                self._conn.sendall(msg.encode('utf-8'))
        except Exception:
            pass


# Top-level imports — kept outside try/except so PyInstaller bundles them.
import subsequence
import subsequence.constants.instruments.gm_drums as gm_drums
from live_bridge import LiveBridge
from api_feeds import DataFeeds

try:
    composition = subsequence.Composition(key="C", bpm=120,
                                          output_device=os.environ.get('POMSKI_MIDI_OUTPUT') or None)
    composition.harmony(style="functional_major", cycle_beats=4, gravity=0.8)

    # Mirror console log lines (INFO+) into the web UI's console pane, so the
    # launch Terminal can be closed once the native window is up without
    # losing debug visibility — see _close_launch_terminal() below.
    class _WebUILogHandler(logging.Handler):
        # DEBUG here (unlike the real console/terminal, which stays INFO+)
        # so the pane replicates the old terminal's constantly-flowing
        # scheduler activity. websockets/asyncio/mido are already capped at
        # INFO globally (see the noisy-logger loop above), so this only
        # actually adds subsequence's own DEBUG chatter (pattern scheduling).
        def __init__(self, comp: 'subsequence.Composition') -> None:
            super().__init__(level=logging.DEBUG)
            self._comp_ref = weakref.ref(comp)

        def emit(self, record: logging.LogRecord) -> None:
            comp = self._comp_ref()
            server = getattr(comp, '_web_ui_server', None) if comp else None
            if server is None:
                return
            try:
                if record.levelno >= logging.ERROR:
                    level = 'err'
                elif record.levelno >= logging.WARNING:
                    level = 'warn'
                elif record.levelno <= logging.DEBUG:
                    level = 'debug'
                else:
                    level = 'info'
                import datetime as _dt
                server.push_console_log(
                    time=_dt.datetime.fromtimestamp(record.created).strftime('%H:%M:%S'),
                    name=record.name,
                    message=record.getMessage(),
                    level=level,
                )
            except Exception:
                pass

    logging.getLogger().addHandler(_WebUILogHandler(composition))

    # ── Ableton Live bridge ───────────────────────────────────────────────────
    live = LiveBridge(composition)
    composition._live_bridge = live

    # ── 16 silent pattern slots ───────────────────────────────────────────────
    @composition.pattern(channel=0,  length=4)
    def ch1(p):  pass

    @composition.pattern(channel=1,  length=4)
    def ch2(p):  pass

    @composition.pattern(channel=2,  length=4)
    def ch3(p):  pass

    @composition.pattern(channel=3,  length=4)
    def ch4(p):  pass

    @composition.pattern(channel=4,  length=4)
    def ch5(p):  pass

    @composition.pattern(channel=5,  length=4)
    def ch6(p):  pass

    @composition.pattern(channel=6,  length=4)
    def ch7(p):  pass

    @composition.pattern(channel=7,  length=4)
    def ch8(p):  pass

    @composition.pattern(channel=8,  length=4)
    def ch9(p):  pass

    @composition.pattern(channel=9, length=4, drum_note_map=gm_drums.GM_DRUM_MAP)
    def ch10(p): pass

    @composition.pattern(channel=10, length=4)
    def ch11(p): pass

    @composition.pattern(channel=11, length=4)
    def ch12(p): pass

    @composition.pattern(channel=12, length=4)
    def ch13(p): pass

    @composition.pattern(channel=13, length=4)
    def ch14(p): pass

    @composition.pattern(channel=14, length=4)
    def ch15(p): pass

    @composition.pattern(channel=15, length=4)
    def ch16(p): pass

    # ── Start ─────────────────────────────────────────────────────────────────
    composition.web_ui()
    composition.live()

    # ── API feeds ─────────────────────────────────────────────────────────────
    feeds = DataFeeds(composition)

    def _pat(channel, length=4, *args, **kwargs):
        # REPL sugar: a dict passed positionally is a drum note map, so
        # @pat(9, 4, drums) works; a number is still unit.
        for arg in args:
            if isinstance(arg, dict):
                kwargs.setdefault("drum_note_map", arg)
            else:
                kwargs.setdefault("unit", arg)
        return composition.pattern(channel, length, **kwargs)

    _orig_build = composition._live_server._build_namespace
    composition._live_server._build_namespace = lambda: {
        **_orig_build(),
        "feeds": feeds,
        "live": live,
        "pat": _pat,
        "drums": gm_drums.GM_DRUM_MAP,
    }

    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # ── Ableton Link (orphaned system-Python process + TCP socket) ────────────
    #
    # aalink.Link() crashes in *any* direct child process of a PyInstaller
    # frozen executable due to SxS activation context DLL redirection.
    # Workaround: run aalink in a detached system-Python subprocess (bridge),
    # communicate via local TCP.  The bridge auto-restarts via _link_service().
    #
    # Suppress composition._run()'s built-in aalink init unconditionally.
    composition._link_thread_running = True

    def _kill_stale_bridge() -> None:
        _pid_file = os.path.join(tempfile.gettempdir(), 'pomski_aalink_pid.txt')
        try:
            _old_pid = int(open(_pid_file).read().strip())
            import ctypes as _ct
            _h = _ct.windll.kernel32.OpenProcess(1, False, _old_pid)
            if _h:
                _ct.windll.kernel32.TerminateProcess(_h, 0)
                _ct.windll.kernel32.CloseHandle(_h)
                logging.info(f"Killed stale aalink bridge (pid {_old_pid})")
            os.remove(_pid_file)
        except Exception:
            pass

    def _bridge_cmd(port: int) -> list:
        """Return the command list to launch aalink_bridge with the given TCP port."""
        _bpm = f'{float(getattr(composition, "bpm", 120.0)):.4f}'
        if getattr(sys, 'frozen', False):
            # Frozen: aalink_bridge.exe is bundled in _internal/ (_MEIPASS).
            _exe = os.path.join(sys._MEIPASS, 'aalink_bridge.exe')
            return [_exe, '127.0.0.1', str(port), _bpm]
        else:
            # Dev: run aalink_bridge.py under system Python.
            _py  = _find_python_exe()
            _scr = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aalink_bridge.py')
            if not os.path.isfile(_scr):
                raise FileNotFoundError(f"aalink_bridge.py not found at {_scr}")
            return [_py, '-u', _scr, '127.0.0.1', str(port), _bpm]

    def _connect_bridge(proxy: '_LinkProxy') -> tuple:
        """Spawn bridge, wait for READY, update proxy._conn. Returns leftover buf."""
        _kill_stale_bridge()

        _srv = _socket_mod.socket(_socket_mod.AF_INET, _socket_mod.SOCK_STREAM)
        _srv.setsockopt(_socket_mod.SOL_SOCKET, _socket_mod.SO_REUSEADDR, 1)
        _srv.bind(('127.0.0.1', 0))
        _port = _srv.getsockname()[1]
        _srv.listen(1)

        subprocess.Popen(
            _bridge_cmd(_port),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True,
            cwd=tempfile.gettempdir(),
            creationflags=(subprocess.DETACHED_PROCESS |
                           subprocess.CREATE_NEW_PROCESS_GROUP),
        )
        logging.info(f"Ableton Link: bridge started, TCP port {_port}")

        _srv.settimeout(15.0)
        try:
            _conn, _ = _srv.accept()
        except _socket_mod.timeout:
            _srv.close()
            raise RuntimeError("aalink_bridge did not connect within 15 s")
        finally:
            _srv.close()

        _conn.setsockopt(_socket_mod.IPPROTO_TCP, _socket_mod.TCP_NODELAY, 1)

        # Wait for READY
        _conn.settimeout(10.0)
        _rbuf, _ready = '', False
        try:
            while not _ready:
                _d = _conn.recv(1024)
                if not _d:
                    break
                _rbuf += _d.decode('utf-8', errors='replace')
                while '\n' in _rbuf:
                    _ln, _rbuf = _rbuf.split('\n', 1)
                    if _ln.strip() == 'READY':
                        _ready = True
                        break
        except _socket_mod.timeout:
            pass

        if not _ready:
            _conn.close()
            raise RuntimeError("aalink_bridge did not send READY")

        _conn.settimeout(None)
        proxy._enabled   = True   # set before _conn so asyncio never sees conn!=None + enabled=False
        proxy._num_peers = 0
        proxy._conn      = _conn
        return _rbuf               # leftover bytes after READY

    def _link_reader_body(conn: '_socket_mod.socket',
                          proxy: '_LinkProxy',
                          initial_buf: str) -> None:
        """Block-read T/P lines from bridge until connection closes."""
        import time as _time
        _buf       = initial_buf
        _last      = getattr(composition, 'bpm', 120.0)
        _last_recv = _time.monotonic()
        conn.settimeout(2.0)          # unblock periodically to check heartbeat
        try:
            while True:
                try:
                    _data = conn.recv(1024)
                except _socket_mod.timeout:
                    # Bridge sends T every 50 ms; silence > 15 s = dead connection.
                    if _time.monotonic() - _last_recv > 15.0:
                        logging.warning("aalink bridge: no heartbeat for 15 s — reconnecting")
                        break
                    continue
                if not _data:
                    break
                _last_recv = _time.monotonic()
                _buf += _data.decode('utf-8', errors='replace')
                while '\n' in _buf:
                    _ln, _buf = _buf.split('\n', 1)
                    _ln = _ln.strip()
                    if not _ln:
                        continue
                    if _ln[0] == 'T':
                        try:
                            _tempo = float(_ln[1:])
                        except ValueError:
                            continue
                        proxy._tempo = _tempo
                        if 20.0 <= _tempo <= 400.0 and abs(_tempo - _last) > 0.05:
                            _last = _tempo
                            try:
                                composition._sequencer.set_bpm(_tempo)
                                if not composition._clock_follow:
                                    composition.bpm = _tempo
                            except Exception:
                                pass
                    elif _ln[0] == 'P':
                        try:
                            proxy._num_peers = int(_ln[1:])
                        except ValueError:
                            pass
        except Exception:
            pass

    def _link_service(proxy: '_LinkProxy') -> None:
        """Daemon thread: connect bridge, run reader, restart on disconnect."""
        import time as _time
        _delay = 0
        while True:
            # Block here (without spinning) when user has disabled Link.
            proxy._run_event.wait()
            if _delay:
                _time.sleep(_delay)
            # Re-check after sleep — user may have disabled while we waited.
            if not proxy._run_event.is_set():
                _delay = 0
                continue
            try:
                _buf = _connect_bridge(proxy)
                logging.info("Ableton Link connected")
                _link_reader_body(proxy._conn, proxy, _buf)
                logging.warning("aalink bridge disconnected — restarting in 5 s")
            except Exception as _e:
                logging.warning(f"Ableton Link bridge error: {_e} — retrying in 10 s")
                _delay = 10
                continue
            # Normal disconnect: clear state, then retry quickly (unless paused).
            proxy._num_peers = 0
            if proxy._conn is not None:   # setter didn't already clear it
                proxy._conn = None
            if proxy._run_event.is_set():
                proxy._enabled = False    # bridge died unexpectedly
            _delay = 5

    def _start_direct_link() -> None:
        """
        macOS/Linux: aalink.Link() works fine directly in-process (no SxS DLL
        redirection issue like Windows), so no bridge subprocess is needed.
        Runs its own dedicated asyncio loop in a daemon thread, since aalink
        needs a *running* loop and composition._main_loop doesn't exist yet
        at this point in startup.
        """
        import aalink as _aalink_mod

        class _DirectLinkProxy:
            """Wraps a real aalink.Link. Exposes the same shape web_ui.py's
            _get_link_state() reads from the Windows bridge _LinkProxy
            (enabled/tempo/num_peers, plus _tempo/_num_peers)."""
            def __init__(self, link: 'aalink.Link'):
                self._link = link

            @property
            def enabled(self):
                return self._link.enabled

            @enabled.setter
            def enabled(self, value):
                self._link.enabled = bool(value)

            @property
            def tempo(self):
                return self._link.tempo

            @tempo.setter
            def tempo(self, value):
                self._link.tempo = float(value)

            @property
            def num_peers(self):
                return self._link.num_peers

            @property
            def _tempo(self):
                return self._link.tempo

            @property
            def _num_peers(self):
                return self._link.num_peers

        def _link_thread_body() -> None:
            _loop = asyncio.new_event_loop()
            asyncio.set_event_loop(_loop)
            _bpm = float(getattr(composition, "bpm", 120.0))
            _link = _aalink_mod.Link(_bpm, _loop)
            _link.enabled = True
            try:
                _link.set_num_peers_callback(lambda n: None)
                _link.set_tempo_callback(lambda t: None)
                _link.set_start_stop_callback(lambda p: None)
            except Exception:
                pass

            composition._link = _DirectLinkProxy(_link)
            logging.info("Ableton Link initialised (direct, in-process)")

            async def _poll() -> None:
                _last = _bpm
                while True:
                    try:
                        _t = _link.tempo
                        if 20.0 <= _t <= 400.0 and abs(_t - _last) > 0.05:
                            _last = _t
                            composition._sequencer.set_bpm(_t)
                            if not composition._clock_follow:
                                composition.bpm = _t
                    except Exception:
                        pass
                    await asyncio.sleep(0.05)

            _loop.run_until_complete(_poll())

        threading.Thread(target=_link_thread_body, daemon=True,
                         name="link-direct").start()

    try:
        if sys.platform == 'win32':
            _link_proxy = _LinkProxy()
            composition._link = _link_proxy
            threading.Thread(target=_link_service, args=(_link_proxy,),
                             daemon=True, name="link-service").start()
            logging.info("Ableton Link service started")
        else:
            _start_direct_link()
    except Exception as _e:
        logging.warning(f"Ableton Link unavailable: {_e}")

    # ── Startup: native window (macOS) or browser ─────────────────────────────
    # MIDI device selection happens at Composition() construction (top of this
    # file), so by the time _web_ui_server exists the prompt is long done.
    def _wait_for_web_ui(must_be_alive: 'threading.Thread | None' = None) -> None:
        import time
        while getattr(composition, '_web_ui_server', None) is None:
            if must_be_alive is not None and not must_be_alive.is_alive():
                raise RuntimeError("POMSKI failed to start — see pomski.log")
            time.sleep(0.25)
        time.sleep(0.5)  # let the HTTP server bind

    def _print_banner() -> None:
        try:
            from rich.console import Console
            Console().print("\n[bold green]POMSKI has started up successfully. Have fun![/bold green]\n")
        except Exception:
            print("\nPOMSKI has started up successfully. Have fun!\n")

    def _close_launch_terminal() -> None:
        """Called by pywebview once the native window's GUI loop is running.
        This process is the detached copy spawned by
        _run_midi_picker_and_relaunch() above — it has no controlling
        terminal of its own (stdin is /dev/null). POMSKI_LAUNCH_TTY names
        the *picker's* Terminal window/tab, which by now has long since
        exited (the picker process exits immediately after spawning us), so
        closing it triggers neither a "still running" confirmation nor any
        risk of SIGHUP to a live process."""
        tty_path = os.environ.get('POMSKI_LAUNCH_TTY')
        _debug(f"close_launch_terminal: tty_path={tty_path!r}")
        if sys.platform != 'darwin' or not tty_path:
            return
        import time
        time.sleep(0.5)  # let the window actually render before closing
        script = f'''
        tell application "Terminal"
            repeat with w in windows
                repeat with t in tabs of w
                    if tty of t is "{tty_path}" then
                        close w
                        return
                    end if
                end repeat
            end repeat
        end tell
        '''
        try:
            result = subprocess.run(['osascript', '-e', script], capture_output=True, timeout=5)
            _debug(f"close_launch_terminal: osascript rc={result.returncode} stdout={result.stdout!r} stderr={result.stderr!r}")
        except Exception as _e:
            _debug(f"close_launch_terminal: osascript raised {_e!r}")

    # pywebview (WKWebView) renders the web UI in a native window, so no
    # browser is needed. macOS requires the GUI to own the main thread, so
    # composition.play() moves to a background thread in that mode.
    _webview = None
    if sys.platform == 'darwin':
        try:
            import webview as _webview
        except ImportError:
            pass

    if _webview is not None:
        _play_thread = threading.Thread(target=composition.play,
                                        name="pomski-play")
        _play_thread.daemon = True
        _play_thread.start()
        _wait_for_web_ui(must_be_alive=_play_thread)
        _print_banner()

        class _PomskiJsApi:
            """Bridge for UI actions WKWebView can't do itself (window.open
            with _blank is silently ignored in pywebview)."""
            def open_tutorial(self):
                _webview.create_window('POMSKI Tutorial',
                                       'http://localhost:8080/tutorial.html',
                                       width=1100, height=850, text_select=True)

        _webview.create_window('POMSKI', 'http://localhost:8080',
                               width=1400, height=900,
                               text_select=True, js_api=_PomskiJsApi())
        # func runs once the GUI loop starts (window is up) — closes the
        # launch Terminal at that point. Blocks until the window is closed.
        _webview.start(func=_close_launch_terminal)

        # Window closed: request a clean sequencer shutdown (notes off),
        # then exit. os._exit is the backstop for anything non-daemon.
        try:
            _seq  = composition._sequencer
            _loop = composition._main_loop
            _loop.call_soon_threadsafe(_seq._stop_event.set)
            _play_thread.join(timeout=5.0)
        except Exception:
            pass
        logging.info("POMSKI window closed — shutting down")
        os._exit(0)
    else:
        def _announce_and_open_browser():
            import webbrowser
            _wait_for_web_ui()
            _print_banner()
            webbrowser.open('http://localhost:8080')

        threading.Thread(target=_announce_and_open_browser, daemon=True,
                         name="startup-announce").start()

        composition.play()

except BaseException:
    _write_crash_log()
    sys.exit(1)
