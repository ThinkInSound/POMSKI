# pomski_mac.spec — PyInstaller build spec for POMSKI (macOS)
#
# Build a distributable macOS app bundle:
#   source myenv/bin/activate
#   pip install pyinstaller
#   pyinstaller pomski_mac.spec -y --clean
#
# Output:  dist/POMSKI.app
#
# Notes:
#   • Requires Python 3.10-3.13 and all POMSKI dependencies installed in the
#     active environment before building (see myenv/).
#   • Unlike Windows, aalink.Link() works fine directly in a frozen macOS
#     process (no SxS DLL redirection issue), so aalink is bundled into the
#     main app instead of excluded + run via a separate bridge subprocess.
#   • console=True for now: the MIDI device picker uses input(), which needs
#     an attached terminal. Launch via
#     `dist/POMSKI.app/Contents/MacOS/POMSKI` from Terminal to test, not by
#     double-clicking in Finder, until the picker is made Finder-launch-safe.

import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

ROOT = Path(SPECPATH)          # directory containing this .spec file
EXAMPLES = ROOT / "examples"

block_cipher = None

a = Analysis(
    [str(EXAMPLES / "pomski_template.py")],

    # ROOT must be on sys.path so PyInstaller resolves the `subsequence`
    # package from its editable-install source tree.
    # EXAMPLES must be on sys.path so bare `live_bridge`/`api_feeds` imports work.
    pathex=[str(ROOT), str(EXAMPLES)],

    binaries=[],

    # Bundle the web UI assets. Destination mirrors the source tree so that
    # web_ui.py's os.path.dirname(__file__)-based lookup still works inside
    # the bundle (PyInstaller sets __file__ to the _MEIPASS equivalent path).
    datas=[
        (str(ROOT / "subsequence" / "assets" / "web"),
         "subsequence/assets/web"),
        *collect_data_files('music21', excludes=[
            # Exclude score files (the bulk of the corpus) but keep:
            #   - corpus/scala/*.scl  — needed for ScalaScale / microtuning
            #   - corpus/metadata/    — corpus index JSON files
            '**/*.abc', '**/*.xml', '**/*.mxl', '**/*.musicxml',
            '**/*.krn', '**/*.mid', '**/*.midi', '**/*.ly',
            '**/*.capx', '**/*.nwc', '**/*.pdf',
            '**/demos/**',
        ]),
        *collect_data_files('rich'),
    ],

    hiddenimports=(
        collect_submodules('subsequence') +
        collect_submodules('websockets') +
        collect_submodules('mido') +
        collect_submodules('rtmidi') +
        collect_submodules('pythonosc') +
        collect_submodules('music21') +
        collect_submodules('rich') +
        collect_submodules('requests') +
        collect_submodules('webview') +
        ['urllib3', 'certifi', 'charset_normalizer', 'idna', 'aalink']
    ),

    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],

    # Trim the bundle — these are never needed at runtime.
    # NOTE: aalink is NOT excluded here (unlike pomski.spec on Windows) —
    # aalink.Link() works directly in a frozen macOS process.
    excludes=[
        "tkinter",
        "matplotlib", "mpl_toolkits",
        "numpy", "scipy",
        "pandas",
        "PIL", "Pillow",
        "IPython", "ipywidgets", "notebook",
        "joblib",
        "networkx",
        "pyaudio",
        "distributed", "dask",
        "tornado",
        "cryptography", "OpenSSL",
        "psutil",
        "lz4", "zstandard", "brotli",
    ],

    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,     # binaries go into COLLECT below
    name="POMSKI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,              # see module docstring above — MIDI picker needs a terminal
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "pomski.icns"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="POMSKI",
)

app = BUNDLE(
    coll,
    name="POMSKI.app",
    icon=str(ROOT / "pomski.icns"),
    bundle_identifier="io.thinkinsound.pomski",
    info_plist={
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleName": "POMSKI",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "10.15",
    },
)

# ── Post-process: Terminal launcher wrapper ───────────────────────────────────
# Finder launches give the process no terminal, so the console log (used for
# debugging) is invisible. Replace the bundle executable with a wrapper that
# re-launches the real binary inside Terminal.app when no tty is attached.
# (BUNDLE builds during construction above, so this runs after it exists.)
import os
import stat
import subprocess

_macos_dir = os.path.join(str(ROOT), "dist", "POMSKI.app", "Contents", "MacOS")
_real = os.path.join(_macos_dir, "POMSKI_bin")
_wrapper = os.path.join(_macos_dir, "POMSKI")

os.rename(_wrapper, _real)
with open(_wrapper, "w") as _f:
    _f.write(
        '#!/bin/bash\n'
        'DIR="$(cd "$(dirname "$0")" && pwd)"\n'
        'if [ -t 0 ]; then\n'
        '    exec "$DIR/POMSKI_bin" "$@"\n'
        'else\n'
        # Marker tells pomski_template.py this Terminal window was opened
        # just to give the MIDI picker a tty (vs. someone manually running
        # POMSKI_bin from their own terminal above) — see the picker/relaunch
        # hand-off near the top of pomski_template.py.
        '    mkdir -p "$HOME/Library/Logs/POMSKI"\n'
        '    touch "$HOME/Library/Logs/POMSKI/.launched_via_wrapper"\n'
        '    open -a Terminal "$DIR/POMSKI_bin"\n'
        'fi\n'
    )
os.chmod(_wrapper, os.stat(_wrapper).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

# Re-sign (ad-hoc) — editing the bundle invalidated PyInstaller's signature.
subprocess.run(
    ["codesign", "--force", "--deep", "-s", "-",
     os.path.join(str(ROOT), "dist", "POMSKI.app")],
    check=True,
)
