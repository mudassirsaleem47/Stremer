"""
client.py - Apne main PC par chalao
Target PC ki screen live dekho
"""

import socket
import struct
import numpy as np
import cv2
import sys
import os
import ipaddress

import json
import threading
PORT = 9999
WINDOW_TITLE = 'Monitor'


def pause_exit():
    try:
        input("Press Enter to exit...")
    except EOFError:
        pass

def load_ip():
    """config.txt se first valid IPv4 padho, warna user se lo."""
    config_path = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'config.txt')
    
    if os.path.exists(config_path):
        with open(config_path, 'r') as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith('#'):
                    continue
                try:
                    ip = str(ipaddress.IPv4Address(line))
                    print(f"IP loaded from config.txt: {ip}")
                    return ip
                except Exception:
                    continue
    
    # config.txt nahi mila to user se poochho
    print("config.txt nahi mila!")
    ip = input("Target PC ka IPv4 enter karo (e.g. 192.168.1.15): ").strip()
    try:
        ip = str(ipaddress.IPv4Address(ip))
    except Exception:
        print("Invalid IPv4!")
        pause_exit()
        sys.exit(1)
    
    # Save kar lo agle baar ke liye
    with open(config_path, 'w') as f:
        f.write(ip)
    print(f"IP save ho gaya config.txt mein")
    return ip

def receive_stream():
    TARGET_IP = load_ip()
    print(f"Connecting to {TARGET_IP}:{PORT} ...")
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    sock.settimeout(10.0)
    send_lock = threading.Lock()
    
    try:
        sock.connect((TARGET_IP, PORT))
        print("Connected! Mouse aur keyboard input viewer window se remote PC ko jayega.")
        print("Press 'Q' to quit, 'F' for fullscreen.")
    except Exception as e:
        print(f"Connection failed: {e}")
        print(f"Check kar lo: server.py chal raha hai? IP sahi hai?")
        pause_exit()
        sys.exit(1)

    sock.settimeout(15.0)
    fullscreen = False
    
    cv2.namedWindow(WINDOW_TITLE, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_TITLE, 1280, 720)

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_MOUSEMOVE:
            send_control_message(sock, send_lock, {'type': 'mouse_move', 'x': x, 'y': y})
        elif event == cv2.EVENT_LBUTTONDOWN:
            send_control_message(sock, send_lock, {'type': 'mouse_button', 'button': 'left', 'action': 'down', 'x': x, 'y': y})
        elif event == cv2.EVENT_LBUTTONUP:
            send_control_message(sock, send_lock, {'type': 'mouse_button', 'button': 'left', 'action': 'up', 'x': x, 'y': y})
        elif event == cv2.EVENT_RBUTTONDOWN:
            send_control_message(sock, send_lock, {'type': 'mouse_button', 'button': 'right', 'action': 'down', 'x': x, 'y': y})
        elif event == cv2.EVENT_RBUTTONUP:
            send_control_message(sock, send_lock, {'type': 'mouse_button', 'button': 'right', 'action': 'up', 'x': x, 'y': y})
        elif event == cv2.EVENT_MBUTTONDOWN:
            send_control_message(sock, send_lock, {'type': 'mouse_button', 'button': 'middle', 'action': 'down', 'x': x, 'y': y})
        elif event == cv2.EVENT_MBUTTONUP:
            send_control_message(sock, send_lock, {'type': 'mouse_button', 'button': 'middle', 'action': 'up', 'x': x, 'y': y})

    cv2.setMouseCallback(WINDOW_TITLE, on_mouse)

    try:
        while True:
            # Pehle 4 bytes = frame size
            raw_size = recv_exact(sock, 4)
            if not raw_size:
                break
            frame_size = struct.unpack('>I', raw_size)[0]
            
            # Frame data receive karo
            data = recv_exact(sock, frame_size)
            if not data:
                break
            
            # Decode aur display
            buf = np.frombuffer(data, dtype=np.uint8)
            frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
            
            if frame is not None:
                cv2.imshow(WINDOW_TITLE, frame)
            
            # Key controls
            key = cv2.waitKeyEx(1)
            if key in (ord('q'), ord('Q')):
                break
            elif key in (ord('f'), ord('F')):
                fullscreen = not fullscreen
                if fullscreen:
                    cv2.setWindowProperty(WINDOW_TITLE, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
                else:
                    cv2.setWindowProperty(WINDOW_TITLE, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_NORMAL)
            elif key != -1:
                send_control_message(sock, send_lock, {'type': 'key_press', 'key': key})
            
            # Window band ho jaye to exit
            if cv2.getWindowProperty(WINDOW_TITLE, cv2.WND_PROP_VISIBLE) < 1:
                break
                
    except KeyboardInterrupt:
        print("\nBand kar diya.")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        sock.close()
        cv2.destroyAllWindows()

def recv_exact(sock, n):
    """Bilkul n bytes receive karo"""
    data = b''
    while len(data) < n:
        try:
            chunk = sock.recv(n - len(data))
            if not chunk:
                return None
            data += chunk
        except socket.timeout:
            return None
    return data

if __name__ == '__main__':
    receive_stream()