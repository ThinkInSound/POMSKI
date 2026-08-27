# pomski.spec — PyInstaller build spec for POMSKI
#
# Build a distributable Windows executable:
#   pip install pyinstaller
#   pyinstaller pomski.spec
#
# Output:  dist/POMSKI/POMSKI.exe   (--onedir, fast startup)
#
# For a single .exe instead (slower cold start, ~5-10s while extracting):
#   Change collect_all=False below and uncomment the onefile EXE block.
#
# Notes:
#   • Requires Python 3.10+ and all POMSKI dependencies installed in the
#     active environment before building.
#   • mido / rtmidi are optional — POMSKI works without them (no MIDI device
#     picker in the Prefs tab), so missing them is not fatal.
#   • The web UI assets are bundled into the exe automatically via datas.

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

    # Bundle the web UI assets.  Destination mirrors the source tree so that
    # web_ui.py's os.path.dirname(__file__)-based lookup still works inside
    # the bundle (PyInstaller sets __file__ to the _MEIPASS equivalent path).
    datas=[
        (str(ROOT / "subsequence" / "assets" / "web"),
         "subsequence/assets/web"),
        # aalink_bridge.exe is a separately-compiled PyInstaller onefile exe.
        # Build it first with:  pyinstaller aalink_bridge.spec
        # It lives alongside POMSKI.exe and is launched as a detached process.
        (str(ROOT / "dist" / "aalink_bridge.exe"), "."),
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
        ['urllib3', 'certifi', 'charset_normalizer', 'idna']
    ),

    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],

    # Trim the bundle — these are never needed at runtime.
    excludes=[
        "aalink",          # must NOT be bundled — aalink.Link() crashes in any
                           # frozen-Python context; the bridge runs under the
                           # system Python instead (see aalink_bridge.py).
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

# ── onedir build (recommended) ────────────────────────────────────────────────
# Produces dist/POMSKI/ with POMSKI.exe inside.
# Faster startup; can be zipped and shared as-is.
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
    console=True,              # keep the console — useful for error messages
                               # and the REPL output log
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "favicon.ico"),
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

# ── onefile build (single .exe, slower startup) ───────────────────────────────
# Uncomment this block and remove the onedir exe + coll blocks above to get a
# single POMSKI.exe in dist/.  Cold start adds ~5-10 seconds for extraction.
#
# exe = EXE(
#     pyz,
#     a.scripts,
#     a.binaries,
#     a.zipfiles,
#     a.datas,
#     [],
#     name="POMSKI",
#     debug=False,
#     bootloader_ignore_signals=False,
#     strip=False,
#     upx=True,
#     upx_exclude=[],
#     runtime_tmpdir=None,
#     console=True,
#     disable_windowed_traceback=False,
#     argv_emulation=False,
#     target_arch=None,
#     codesign_identity=None,
#     entitlements_file=None,
#     icon=None,
# )
