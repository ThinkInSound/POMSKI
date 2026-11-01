### Technical Specification: Real-Time Playhead Token Highlighting System

**Architecture Scope:** Pure Python backend running a live-coding execution engine + Vanilla HTML/JS frontend using a custom dual-layer text display layout (No GUI/Editor Framework Dependencies). 

### 1. System Architecture Overview

To achieve visual accuracy matching compiled environments like Sonic Pi, this architecture separates calculation execution from network transmission using a **three-tier execution layer**: 

[ Python Compilation Layer ] ──► Rewrites AST to inject source tokens into functions
            │
            ▼
[ Python Audio Timing Loop ]  ──► Executes bytecode AoT, issuing cues with future monotonic timestamps
            │
            ▼  (WebSocket Packet / Jitter Buffer)
            ▼
[ Browser Rendering Loop ]    ──► Uses requestAnimationFrame + NTP clock sync to draw overlapping boxes

### 2. Python Backend Implementation

This module provides the core transformation engine. It intercepts user code snippets from the REPL, runs them through an ast.NodeTransformer macro to inject code block grid coordinates directly into function signature calls, and manages scheduling queues. 

python

import ast
import json
import time
import asyncio
import websockets

# --- STEP 1: RUNTIME METADATA INJECTION VIA AST MACRO ---
class TokenMetadataInjector(ast.NodeTransformer):
    """
    Walks the code AST and rewrites specific function calls on the fly.
    Turns an expression like `play(60)` into `play(60, _meta=(line, start_col, end_line, end_col))`
    """
    def __init__(self, target_functions):
        self.target_functions = target_functions

    def visit_Call(self, node):
        # Continue processing nested nodes first
        self.generic_visit(node)
        
        # Check if function name matches our telemetry targets (e.g., play, sample)
        func_name = getattr(node.func, 'id', None)
        if func_name in self.target_functions:
            # Map start and end positions (Python AST lines are 1-indexed; convert to 0-indexed)
            start_line = node.lineno - 1
            start_col = node.col_offset
            end_line = getattr(node, 'end_lineno', node.lineno) - 1
            end_col = getattr(node, 'end_col_offset', node.col_offset + 5)

            # Generate the AST representation for the '_meta' keyword argument tuple
            meta_keyword = ast.keyword(
                arg='_meta',
                value=ast.Tuple(
                    elts=[
                        ast.Constant(value=start_line),
                        ast.Constant(value=start_col),
                        ast.Constant(value=end_line),
                        ast.Constant(value=end_col)
                    ],
                    ctx=ast.Load()
                )
            )
            node.keywords.append(meta_keyword)
        return node

# --- STEP 2: AUDIO ENGINE RUNTIME FUNCTION DEFINITIONS ---
# A global thread-safe state container tracking connected websocket clients
ACTIVE_CLIENTS = set()

def play(note, *args, _meta=None, **kwargs):
    """
    The target function executed inside the live-code user environment.
    """
    if _meta:
        start_line, start_col, end_line, end_col = _meta
        # Calculate Ahead-of-Time (AoT) execution window to combat network flight latency
        # Schedule the UI to light up exactly 60ms into the future
        target_render_time_ms = int(time.monotonic() * 1000) + 60
        
        packet = {
            "type": "NOTE_TRIGGER",
            "timestamp": target_render_time_ms,
            "start_line": start_line,
            "start_col": start_col,
            "end_line": end_line,
            "end_col": end_col
        }
        
        # Dispatch the telemetry message over the websocket message broker
        if ACTIVE_CLIENTS:
            payload = json.dumps(packet)
            for client in ACTIVE_CLIENTS:
                asyncio.run_coroutine_threadsafe(client.send(payload), asyncio.get_event_loop())
                
    print(f"[Engine Audio Output] Synthesizing note: {note}")

# --- STEP 3: REPL COMPILATION AND HOT-SWAPPING LAYER ---
def live_compile_and_run(user_code_string, global_context):
    """
    Compiles raw string snippets cleanly without file-system backing constraints,
    preserving coordinate scopes.
    """
    # Parse code into raw AST
    parsed_tree = ast.parse(user_code_string)
    
    # Inject metadata decorators via custom visitor macro
    transformer = TokenMetadataInjector(target_functions={"play", "sample"})
    transformed_tree = transformer.visit(parsed_tree)
    ast.fix_missing_locations(transformed_tree)
    
    # Compile into system bytecode objects
    bytecode = compile(transformed_tree, filename="<live_repl>", mode="exec")
    
    # Safely evaluate bytecode in target execution environment memory space
    exec(bytecode, global_context)

# --- STEP 4: WEBSOCKET INTERFACES & PROTOCOL BROKER ---
async def network_broker_handler(websocket):
    ACTIVE_CLIENTS.add(websocket)
    try:
        async for message in websocket:
            data = json.loads(message)
            
            # High-precision NTP/Cristian's algorithm clock sync response handlers
            if data.get("type") == "CLOCK_SYNC_REQUEST":
                response = {
                    "type": "CLOCK_SYNC_RESPONSE",
                    "client_id": data.get("client_id"),
                    "server_time_ms": int(time.monotonic() * 1000)
                }
                await websocket.send(json.dumps(response))
    finally:
        ACTIVE_CLIENTS.remove(websocket)

async def main():
    async with websockets.serve(network_broker_handler, "localhost", 8765):
        await asyncio.Future()  # Keep server loop running infinitely

if __name__ == "__main__":
    # To test locally, boot up the network worker server loop:
    # asyncio.run(main())
    pass

Use code with caution.

### 3. Frontend Implementation

This single HTML file contains the synchronized dual-layer overlapping components, an NTP clock estimation routine, and a lookahead queue driven by a high-resolution animation loop. 

html

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Hand-Rolled Live Code Execution Playhead</title>
    <style>
        body {
            background-color: #121214;
            color: #e1e1e6;
            font-family: sans-serif;
            padding: 20px;
        }

        /* Container boundary settings locking elements into matching coordinate frames */
        .editor-container {
            position: relative;
            width: 800px;
            height: 450px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.5);
            border-radius: 6px;
            overflow: hidden;
        }

        /* 
           Crucial CSS Specifications: 
           Text rendering variables must match perfectly between layers 
        */
        .editor-layer {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            margin: 0;
            padding: 16px;
            border: 2px solid #29292e;
            box-sizing: border-box;
            
            /* Text Layout Anchors */
            font-family: 'Fira Code', 'Courier New', Courier, monospace;
            font-size: 15px;
            line-height: 24px; /* Explicit pixel line height prevents browser-specific calculation drift */
            tab-size: 4;
            
            white-space: pre-wrap;
            word-wrap: break-word;
            overflow-y: auto;
        }

        /* LAYER 1: Dynamic Highlight Vector Field (Bottom Stack) */
        #highlight-layer {
            background-color: #19191d;
            color: transparent; /* Render text invisible to allow visual tokens to peak through */
            z-index: 1;
            pointer-events: none; /* Let cursor click layers slide right past to interactive input */
        }

        /* LAYER 2: Text Interactive Interface Field (Top Stack) */
        #interactive-textarea {
            background: transparent;
            color: #e1e1e6;
            z-index: 2;
            caret-color: #50fa7b;
            resize: none;
            outline: none;
        }

        /* Sonic Pi Highlight Box styling elements */
        .live-code-playhead-box {
            position: relative;
            border: 2px solid #50fa7b;
            background-color: rgba(80, 250, 123, 0.15);
            border-radius: 4px;
            box-shadow: 0 0 10px rgba(80, 250, 123, 0.4);
            
            /* Box Padding Offset Counteracting Margin Bounds */
            margin: -2px -1px;
            display: inline-block;
            vertical-align: top;
        }
    </style>
</head>
<body>

    <h2>Live-Coding Script Editor</h2>
    <div class="editor-container">
        <div id="highlight-layer" class="editor-layer"></div>
        <textarea id="interactive-textarea" class="editor-layer" spellcheck="false" autocomplete="off">def pattern_sequence():
    play(60)
    sleep(0.5)
    play(64)
    # Testing a multi-line statement block integration structure
    play(
        67
    )</textarea>
    </div>

    <script>
        const textarea = document.getElementById('interactive-textarea');
        const highlightLayer = document.getElementById('highlight-layer');

        // Global Synchronization Clock States
        let serverTimeOffset = 0;
        let visualTimelineQueue = [];
        let currentActiveMarker = null;

        // --- STEP 1: DOM COORDINATE SYNCHRONIZATION EVENT LOOPS ---
        textarea.addEventListener('scroll', () => {
            highlightLayer.scrollTop = textarea.scrollTop;
            highlightLayer.scrollLeft = textarea.scrollLeft;
        });

        textarea.addEventListener('input', () => {
            refreshVisualEditorLayout();
        });

Use code with caution.