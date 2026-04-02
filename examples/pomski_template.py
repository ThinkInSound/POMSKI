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

# ── Log directory ─────────────────────────────────────────────────────────────
if getattr(sys, 'frozen', False):
    _LOG_DIR = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'POMSKI')
    os.makedirs(_LOG_DIR, exist_ok=True)
else:
    _LOG_DIR = '.'
_LOG_PATH = os.path.join(_LOG_DIR, 'pomski.log')
_FAULT_PATH = os.path.join(_LOG_DIR, 'fault.log')

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    handlers=[
        logging.FileHandler(_LOG_PATH, encoding='utf-8'),
        logging.StreamHandler(sys.stdout),
    ]
)
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
    composition = subsequence.Composition(key="C", bpm=120)
    composition.harmony(style="functional_major", cycle_beats=4, gravity=0.8)

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
    _orig_build = composition._live_server._build_namespace
    composition._live_server._build_namespace = lambda: {
        **_orig_build(),
        "feeds": feeds,
        "live": live,
        "pat": composition.pattern,
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

    try:
        _link_proxy = _LinkProxy()
        composition._link = _link_proxy
        threading.Thread(target=_link_service, args=(_link_proxy,),
                         daemon=True, name="link-service").start()
        logging.info("Ableton Link service started")
    except Exception as _e:
        logging.warning(f"Ableton Link unavailable: {_e}")

    # Auto-open browser when running as compiled exe.
    if getattr(sys, 'frozen', False):
        import webbrowser, time
        threading.Thread(
            target=lambda: (time.sleep(2), webbrowser.open('http://localhost:8080')),
            daemon=True
        ).start()

    composition.play()

except BaseException:
    _write_crash_log()
    sys.exit(1)
