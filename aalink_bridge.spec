# aalink_bridge.spec — PyInstaller build spec for the Ableton Link bridge
#
# WINDOWS ONLY. macOS does not need this at all — aalink.Link() works fine
# directly in a frozen macOS process, so pomski_mac.spec bundles aalink into
# the app itself and pomski_template.py takes its _start_direct_link() path.
#
# Build FIRST, before pomski.spec:
#   pyinstaller aalink_bridge.spec        ->  dist/aalink_bridge.exe
#   pyinstaller pomski.spec -y --clean    ->  dist/POMSKI/   (bundles the above)
#   iscc pomski_installer.iss             ->  Output/POMSKI_Setup.exe
#
# Why this exists as a separate executable at all:
#   aalink.Link() crashes inside a PyInstaller-frozen Windows process, because
#   the frozen exe's SxS activation context redirects the VC++ runtime DLLs to
#   _internal/. The bridge is therefore built as its own standalone onefile exe
#   and launched DETACHED (see _connect_bridge() in pomski_template.py), so it
#   never inherits POMSKI's activation context. It talks to POMSKI over a local
#   TCP socket instead — see the protocol in aalink_bridge.py's docstring.
#
# This is the mirror image of pomski.spec, which *excludes* aalink for exactly
# the same reason. aalink must be bundled HERE and nowhere else.

from pathlib import Path
from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH)                  # directory containing this .spec file
EXAMPLES = ROOT / "examples"

block_cipher = None

# collect_all rather than collect_submodules: aalink is a compiled C extension,
# so its binaries have to come along too, not just its Python modules.
_aalink_datas, _aalink_binaries, _aalink_hiddenimports = collect_all('aalink')

a = Analysis(
    [str(EXAMPLES / "aalink_bridge.py")],
    pathex=[str(ROOT), str(EXAMPLES)],
    binaries=_aalink_binaries,
    datas=_aalink_datas,
    hiddenimports=_aalink_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],

    # The bridge imports nothing but stdlib + aalink, so everything heavy can
    # go. Keeps this exe small — it ships inside the main POMSKI bundle.
    excludes=[
        "tkinter",
        "matplotlib", "mpl_toolkits",
        "numpy", "scipy",
        "pandas",
        "PIL", "Pillow",
        "IPython", "ipywidgets", "notebook",
        "music21",
        "mido", "rtmidi",
        "websockets",
        "pythonosc",
        "rich",
        "requests", "urllib3", "certifi",
        "subsequence",
    ],

    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# Onefile: pomski.spec bundles the single resulting .exe via datas, and
# pomski_template.py's _bridge_cmd() looks for exactly one file at
# sys._MEIPASS/aalink_bridge.exe.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="aalink_bridge",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,

    # UPX off deliberately: it has a history of corrupting compiled C
    # extensions, and a mangled aalink here would fail at Link() construction
    # inside a detached process with its stdio pointed at DEVNULL — i.e.
    # silently, with Link simply never connecting and no clue why.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,

    # No console: the bridge is launched DETACHED_PROCESS with stdin/stdout/
    # stderr all set to DEVNULL, so a console would only ever flash on screen.
    # It redirects its own sys.stderr to %TEMP%/aalink_bridge_err.log early in
    # startup, so diagnostics survive regardless. Flip to True when debugging
    # the bridge directly from a terminal.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
