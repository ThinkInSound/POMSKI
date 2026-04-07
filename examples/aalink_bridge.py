"""
aalink_bridge.py — Ableton Link bridge for POMSKI.

POMSKI writes a launcher that starts this script via subprocess with
DETACHED_PROCESS flags, making it independent of POMSKI's console group.
aalink.Link() crashes when it inherits POMSKI's SxS activation context
(which redirects VC++ DLLs to _internal/).  Pre-loading from System32
fixes this.

Communication: bidirectional TCP on 127.0.0.1:<port>

Protocol (text lines, both directions):
    T<bpm>\n          tempo
    E<0|1>\n          link enabled state
    P<n>\n            peer count (bridge→POMSKI only)
    READY\n           sent once by bridge after Link initialises (bridge→POMSKI)
"""

import sys
import os
import asyncio
import threading
import faulthandler
import tempfile
import socket as _socket

# ── Logging ───────────────────────────────────────────────────────────────────
_log_dir    = tempfile.gettempdir()
_fault_path = os.path.join(_log_dir, 'aalink_bridge_fault.log')
_err_path   = os.path.join(_log_dir, 'aalink_bridge_err.log')
faulthandler.enable(file=open(_fault_path, 'w', buffering=1))
sys.stderr = open(_err_path, 'w', buffering=1)

# Write our PID immediately so POMSKI can kill us on next startup.
_pid_path = os.path.join(_log_dir, 'pomski_aalink_pid.txt')
open(_pid_path, 'w').write(str(os.getpid()))

_host        = sys.argv[1] if len(sys.argv) > 1 else '127.0.0.1'
_port        = int(sys.argv[2])   if len(sys.argv) > 2 else 9999
_initial_bpm = float(sys.argv[3]) if len(sys.argv) > 3 else 120.0

print(f"aalink_bridge pid={os.getpid()} starting — connecting to "
      f"{_host}:{_port}", file=sys.stderr, flush=True)


# ── Pre-load VC++ runtime from System32 ──────────────────────────────────────
# POMSKI's SxS activation context (inherited even with DETACHED_PROCESS) would
# redirect VCRUNTIME140.dll etc. to POMSKI's _internal/ copies.  Loading them
# explicitly from System32 first causes Windows to reuse those handles, fixing
# the ACCESS_VIOLATION in aalink.Link()'s C++ constructor.
try:
    import ctypes as _ct
    _s32 = os.path.join(os.environ.get('SYSTEMROOT', r'C:\Windows'), 'System32')
    for _dll in ('vcruntime140.dll', 'vcruntime140_1.dll', 'msvcp140.dll',
                 'concrt140.dll'):
        _p = os.path.join(_s32, _dll)
        if os.path.isfile(_p):
            _ct.CDLL(_p)
    print("preload: VC++ runtime OK", file=sys.stderr, flush=True)
except Exception as _pe:
    print(f"preload: warning — {_pe}", file=sys.stderr, flush=True)


# ── Asyncio event loop ────────────────────────────────────────────────────────
# aalink needs a running loop for peer-discovery callbacks and enable/disable
# state transitions.  SelectorEventLoop avoids IOCP-related issues on Windows.
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
_loop = asyncio.new_event_loop()
asyncio.set_event_loop(_loop)

# ── Initialise aalink ─────────────────────────────────────────────────────────
print("step1: import aalink", file=sys.stderr, flush=True)
import aalink as _aalink_mod

print("step2: aalink.Link()", file=sys.stderr, flush=True)
_link = _aalink_mod.Link(_initial_bpm, _loop)
print("step2 OK", file=sys.stderr, flush=True)

print("step3: link.enabled = True", file=sys.stderr, flush=True)
_link.enabled = True

# Register no-op callbacks so aalink's C++ layer never fires into a null
# function pointer when peers join/leave or tempo changes rapidly.
try:
    _link.set_num_peers_callback(lambda n: None)
    _link.set_tempo_callback(lambda t: None)
    _link.set_start_stop_callback(lambda p: None)
    print("callbacks: no-op callbacks registered OK", file=sys.stderr, flush=True)
except Exception as _e:
    print(f"callbacks: warning — {_e}", file=sys.stderr, flush=True)

# Log available API so we know which peer-count attribute to use.
_link_attrs = [a for a in dir(_link) if not a.startswith('_')]
print(f"aalink Link attrs: {_link_attrs}", file=sys.stderr, flush=True)
print("aalink_bridge: Link initialised OK", file=sys.stderr, flush=True)


# ── Command receiver thread ───────────────────────────────────────────────────
def _recv_commands(conn: _socket.socket) -> None:
    # Schedule Link mutations on the asyncio loop thread so aalink's
    # enable/disable cycling is thread-safe (avoids re-entry into C++ from
    # a non-loop thread while callbacks are in flight).
    buf = ''
    try:
        while True:
            data = conn.recv(1024)
            if not data:
                break
            buf += data.decode('utf-8', errors='replace')
            while '\n' in buf:
                line, buf = buf.split('\n', 1)
                line = line.strip()
                if not line:
                    continue
                if line[0] == 'T':
                    v = float(line[1:])
                    _loop.call_soon_threadsafe(setattr, _link, 'tempo', v)
                elif line[0] == 'E':
                    v = bool(int(line[1:]))
                    _loop.call_soon_threadsafe(setattr, _link, 'enabled', v)
    except Exception:
        pass


# ── Main async loop ───────────────────────────────────────────────────────────
async def _run() -> None:
    conn = _socket.create_connection((_host, _port), timeout=10)
    conn.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_NODELAY, 1)

    threading.Thread(target=_recv_commands, args=(conn,), daemon=True,
                     name="link-cmd").start()

    conn.sendall(b'READY\n')
    print("aalink_bridge READY", file=sys.stderr, flush=True)

    _last_peers = -1
    try:
        while True:
            try:
                _p = getattr(_link, 'num_peers', None)
                if _p is None:
                    _p = getattr(_link, 'numPeers', None)
                    if callable(_p):
                        _p = _p()
                peers = int(_p) if _p is not None else 0
            except Exception:
                peers = 0
            try:
                msg = f'T{_link.tempo:.4f}\n'
            except Exception as _re:
                print(f'poll read error: {_re}', file=sys.stderr, flush=True)
                await asyncio.sleep(0.1)
                continue
            if peers != _last_peers:
                msg += f'P{peers}\n'
                _last_peers = peers
            conn.sendall(msg.encode())
            await asyncio.sleep(0.05)
    except Exception as _e:
        print(f'poll loop exiting: {_e}', file=sys.stderr, flush=True)
    finally:
        # Explicitly shut down so POMSKI's recv() unblocks immediately.
        try:
            conn.shutdown(_socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


_loop.run_until_complete(_run())
print("aalink_bridge: TCP connection closed, exiting", file=sys.stderr, flush=True)
sys.exit(0)
