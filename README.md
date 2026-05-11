# Stremer

Stremer is a simple LAN screen-mirroring tool with mouse and keyboard control. One machine runs the server and shares its screen; the other machine connects as the client and displays the live feed.

## What’s Included

- `Code/server.py` - runs on the target PC and captures the screen.
- `Code/client.py` - runs on the viewer PC and receives the stream.
- `Code/app with UI.py` - optional Tkinter-based UI for scanning and connecting.
- `config.txt` - stores the target PC IPv4 address for the client.
- `StartwindowsService.bat` - helper script that launches the packaged server as administrator.

## Requirements

- Windows on both machines.
- Python 3.10+ if you want to run from source.
- The Python packages used by the scripts:
  - `mss`
  - `numpy`
  - `opencv-python`

## Setup From Source

1. Install the dependencies:

```bash
pip install mss numpy opencv-python
```

2. Make sure both PCs are on the same LAN.
3. Pick the target PC’s local IPv4 address and put it in `config.txt`.

## How To Run

### Target PC

Run `Code/server.py` on the machine whose screen you want to share.

The server listens on port `9999`, starts a control channel for mouse and keyboard input, and tries to add a Windows Firewall rule for that port.

### Viewer PC

Run `Code/client.py` on the machine you want to use for viewing and control.

The client reads the first valid IPv4 from `config.txt`. If the file is missing or empty, it prompts you for the target IP and saves it for next time.

Basic controls in the viewer window:

- Move mouse to control the remote PC.
- Left / right / middle click are forwarded to the target.
- `Q` quits.
- `F` toggles fullscreen.

### Optional GUI

`Code/app with UI.py` provides a graphical interface for scanning the local subnet and opening a viewer window.

## Packaged Files

This workspace also includes `server.exe` and `streamer.exe`. If you are using the packaged version instead of Python source files, `StartwindowsService.bat` is the launcher for the server side.

## Notes

- The server is designed for Windows and uses Windows-specific input handling.
- The stream is JPEG-encoded over TCP, so image quality and FPS are controlled by the settings in `Code/server.py`.
- If the client cannot connect, verify that the IP in `config.txt` is correct and that port `9999` is reachable.