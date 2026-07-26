# PPSSPP MCP

**ENGLISH | [KOREAN](README_ko.md)**

PPSSPP MCP is a Windows-focused Model Context Protocol server for controlling and inspecting [PPSSPP](https://www.ppsspp.org/). It combines PPSSPP's WebSocket remote debugger with Windows process-memory inspection, input automation, process launching, and inactive-window screenshots.

> [!IMPORTANT]
> Debugger and input tools require PPSSPP's remote debugger to be enabled and a game to be loaded. Windows process-memory and window-capture tools operate locally on the PPSSPP process and are separate from the remote debugger connection.

## Features

- Inspect debugger, game, CPU, and thread status.
- Pause and resume emulation.
- Evaluate debugger expressions and disassemble PSP code.
- Send raw PPSSPP debugger events for advanced operations.
- Press digital buttons, set multiple button states, and send analog-stick input.
- Discover and launch PPSSPP processes.
- Enumerate PPSSPP windows and capture inactive windows to an image file.
- List Windows virtual-memory regions for a PPSSPP process.
- Read process memory and search for byte patterns with wildcard support.
- Convert text into search patterns using a selected encoding.

## Requirements

- Windows
- Python 3.10 or newer
- PPSSPP with **Allow remote debugger** enabled
- An MCP client that supports local stdio servers

The default remote debugger endpoint is `127.0.0.1:7378`.

## PPSSPP setup

In PPSSPP, open **Settings > Tools > Developer tools** and enable **Allow remote debugger**. The default port is `7378`.

Load a game before using debugger, disassembly, expression, or input tools. If the port is changed in PPSSPP, pass the same `host` and `port` values to the MCP tools.

## Installation

Open PowerShell in the repository directory:

```powershell
python -m pip install -e .
```

Run the server directly:

```powershell
python -m ppsspp_mcp
```

The server communicates over stdio, so it normally runs under an MCP client rather than in a standalone interactive terminal.

## Codex MCP configuration

To register PPSSPP MCP as a local stdio server in Codex, add the following blocks to `%USERPROFILE%\.codex\config.toml`. Replace `C:\path\to\PPSSPP_MCP` with the path where you cloned this repository.

```toml
[mcp_servers.ppsspp]
command = "python"
args = ["-m", "ppsspp_mcp"]
cwd = 'C:\path\to\PPSSPP_MCP'

[mcp_servers.ppsspp.env]
PYTHONPATH = 'C:\path\to\PPSSPP_MCP\src'
```

The `python` command must resolve to the interpreter where the project dependencies were installed. Restart Codex after changing `config.toml`.

## Typical workflow

1. Enable PPSSPP's remote debugger and load a game.
2. Call `debugger_status`, `game_status`, and `cpu_status` to confirm the connection and current state.
3. Use `pause` before stable inspection of threads, expressions, or disassembly.
4. Call `thread_list`, `evaluate`, or `disassemble` as required.
5. Use `input_button_press`, `input_buttons_send`, or `input_analog_send` for input automation.
6. Call `resume` when inspection is complete.

For visual inspection, use `list_ppsspp_windows` and then `capture_ppsspp_window`. The capture tool can temporarily restore a minimized window and return it to its prior state.

For host process-memory inspection, use `list_ppsspp_processes`, `list_process_regions`, and `find_process_pattern` before calling `read_process_memory` with a Windows virtual address.

## Debugger tools

| Area | Tools |
| --- | --- |
| Status | `debugger_status`, `game_status`, `cpu_status`, `thread_list` |
| Code inspection | `evaluate`, `disassemble` |
| Execution | `pause`, `resume` |
| Advanced protocol | `debugger_request` |
| Input | `input_button_press`, `input_buttons_send`, `input_analog_send` |

`debugger_request` sends a raw event and parameter object to PPSSPP. Prefer the dedicated tools when one exists, and use raw requests only when the event contract is known.

## Windows process and capture tools

| Area | Tools |
| --- | --- |
| Process control | `list_ppsspp_processes`, `launch_ppsspp` |
| Window capture | `list_ppsspp_windows`, `capture_ppsspp_window` |
| Memory regions | `list_process_regions` |
| Memory access | `read_process_memory`, `find_process_pattern`, `pattern_from_text` |

Process-memory addresses are Windows virtual addresses in the selected PPSSPP process, not automatically PSP emulated addresses. Process permissions, architecture, and the active PPSSPP instance can affect memory access.

## Safety

This server can control game input, pause or resume emulation, inspect the PPSSPP process, read large memory ranges, launch executables, and write screenshots to arbitrary paths. Keep it bound to local MCP clients and review tool arguments before approving sensitive operations.

Generated logs, screenshots, virtual environments, bytecode, and build outputs should remain outside version control.

## License

This project is distributed under the terms in [LICENSE](LICENSE).
