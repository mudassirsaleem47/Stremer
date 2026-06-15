import sys
import threading
import subprocess
import queue
import os
import json
import time
import socket
import struct
import ipaddress
import traceback
import numpy as np
import cv2
from tkinter import Tk, StringVar, IntVar, ttk, scrolledtext, N, S, E, W, messagebox, Menu, simpledialog, Entry

CONFIG_FILE = "config.txt"
NAMES_FILE = "device_names.json"
DEFAULT_PORT = 9999
GLOBAL_CONFIG_FILE = "config_global.txt"
UI_CONFIG_FILE = "config_ui.json"
AUDIO_RATE = 44100  # High-quality voice

def write_crash_log(exc_text):
    try:
        base_dir = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
        log_path = os.path.join(base_dir, 'startup_error.log')
        with open(log_path, 'w', encoding='utf-8') as f:
            f.write(exc_text)
    except Exception:
        pass

def install_exception_hook():
    def _hook(exc_type, exc, tb):
        text = ''.join(traceback.format_exception(exc_type, exc, tb))
        write_crash_log(text)
        try:
            print(text, flush=True)
        except Exception:
            pass
    sys.excepthook = _hook

def app_base_dir():
    return os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))

def normalize_relay_url(url):
    url = (url or '').strip()
    if not url:
        return ''
    url = url.replace('https://', 'wss://', 1)
    url = url.replace('http://', 'ws://', 1)
    if url.startswith('wss://') or url.startswith('ws://'):
        return url.rstrip('/')
    return f'wss://{url}'.rstrip('/')

def load_pyaudio():
    try:
        import importlib
        return importlib.import_module('pyaudio')
    except Exception:
        return None

def get_placeholder_frame(text="Waiting for Stream..."):
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    font = cv2.FONT_HERSHEY_SIMPLEX
    text_size = cv2.getTextSize(text, font, 1.2, 2)[0]
    text_x = (1280 - text_size[0]) // 2
    text_y = (720 + text_size[1]) // 2
    cv2.putText(frame, text, (text_x, text_y), font, 1.2, (200, 200, 200), 2, cv2.LINE_AA)
    return frame

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return '192.168.1.1'

def recv_exact(sock, n):
    data = b''
    while len(data) < n:
        try:
            chunk = sock.recv(n - len(data))
            if not chunk:
                return None
            data += chunk
        except socket.timeout:
            continue
        except Exception:
            return None
    return data

def check_ping(ip):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.4)
        for port in [135, 139, 445, 80, 22]:
            try:
                result = s.connect_ex((ip, port))
                if result == 0:
                    s.close()
                    return True
            except:
                pass
        s.close()

        result = subprocess.run(
            ['ping', '-n', '1', '-w', '150', ip],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            timeout=1
        )
        return result.returncode == 0
    except:
        return False

def check_server_stream(ip):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.2)
        s.connect((ip, DEFAULT_PORT))
        raw_size = recv_exact(s, 4)
        if not raw_size:
            s.close()
            return False
        
        size = struct.unpack('>I', raw_size)[0]
        if size < 1 or size > 15 * 1024 * 1024:
            s.close()
            return False

        header = recv_exact(s, 3)  # type (1 byte) + jpegSOI (2 bytes)
        s.close()
        if not header:
            return False
        
        # JPEG SOI marker on index 1 (index 0 is packet prefix)
        return header[1:3] == b'\xff\xd8'
    except Exception:
        return False

def resolve_hostname(ip):
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        pass

    try:
        result = subprocess.run(
            ['ping', '-a', '-n', '1', '-w', '200', ip],
            capture_output=True,
            text=True,
            timeout=1.5,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
        if result.stdout:
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.lower().startswith('pinging ') and '[' in line:
                    name_part = line[len('Pinging '):].split('[', 1)[0].strip()
                    if name_part and name_part.lower() != ip.lower():
                        return name_part
    except Exception:
        pass

    return "Unknown"

class AppLogic:
    @staticmethod
    def scan_network(callback_log, callback_device, callback_done):
        local_ip = get_local_ip()
        network = '.'.join(local_ip.split('.')[:3])
        callback_log(f"Scanning {network}.0/24...")

        def scan_worker(i):
            ip = f"{network}.{i}"
            try:
                alive = check_ping(ip)
                is_stream = check_server_stream(ip)
                if is_stream or alive:
                    hostname = resolve_hostname(ip)
                    status = "[STREAM]" if is_stream else "Alive"
                    me = " (Your PC)" if ip == local_ip else ""
                    callback_device((ip, hostname, "Unknown", f"{status}{me}"))
            except:
                pass

        threads = []
        for i in range(1, 255):
            t = threading.Thread(target=scan_worker, args=(i,), daemon=True)
            threads.append(t)
            t.start()
            if len(threads) >= 40:
                for t in threads:
                    t.join()
                threads = []
        for t in threads:
            t.join()
        callback_done()

    @staticmethod
    def fetch_global_devices(relay_url, callback_log):
        ok, devices, _ = AppLogic.test_relay_connection(relay_url, callback_log)
        return devices if ok else []

    @staticmethod
    def test_relay_connection(relay_url, callback_log):
        relay_url = normalize_relay_url(relay_url)
        if not relay_url:
            return False, [], "Relay URL is empty"

        registry_url = relay_url.rstrip('/') + '/registry'
        try:
            import websocket
        except ImportError:
            return False, [], "websocket-client package is missing"

        try:
            ws = websocket.create_connection(registry_url, timeout=5)
            try:
                payload = ws.recv()
            finally:
                ws.close()

            if isinstance(payload, bytes):
                payload = payload.decode('utf-8', errors='ignore')

            if not isinstance(payload, str) or not payload.strip():
                return False, [], "Relay response is empty"

            data = json.loads(payload)
            devices = data.get('devices', []) if isinstance(data, dict) else []
            return True, devices, f"Connected. Active devices: {len(devices)}"
        except Exception as e:
            callback_log(f"Global connection test failed: {e}")
            return False, [], str(e)

    @staticmethod
    def run_viewer(ip, callback_log, callback_done):
        WINDOW_TITLE = 'ScreenMirror Pro'
        callback_log(f"Connecting to Local LAN device: {ip}:{DEFAULT_PORT}...")
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(1.0)
            sock.connect((ip, DEFAULT_PORT))
            callback_log("Connected! Initializing stream...")
        except Exception as e:
            callback_log(f"Connection failed: {e}")
            callback_done()
            return

        pyaudio = load_pyaudio()
        audio_queue = queue.Queue()
        
        def audio_play_thread_fn():
            if not pyaudio:
                return
            p = pyaudio.PyAudio()
            try:
                audio_stream = p.open(format=pyaudio.paInt16,
                                      channels=1,
                                      rate=AUDIO_RATE,
                                      output=True,
                                      frames_per_buffer=1024)
            except Exception as e:
                callback_log(f"Speakers playback failed: {e}")
                p.terminate()
                return

            try:
                while True:
                    chunk = audio_queue.get()
                    if chunk is None:
                        break
                    try:
                        audio_stream.write(chunk)
                    except Exception:
                        break
            finally:
                try:
                    audio_stream.stop_stream()
                    audio_stream.close()
                except:
                    pass
                p.terminate()

        audio_play_thread = threading.Thread(target=audio_play_thread_fn, daemon=True)
        audio_play_thread.start()

        fullscreen = False
        cv2.namedWindow(WINDOW_TITLE, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(WINDOW_TITLE, 1280, 720)
        
        last_frame_time = time.time()
        has_received_frame = False
        
        cv2.imshow(WINDOW_TITLE, get_placeholder_frame("Connecting / Waiting for Stream..."))

        try:
            while True:
                try:
                    # Receive size prefix (4 bytes)
                    raw_size = recv_exact(sock, 4)
                    if not raw_size:
                        key = cv2.waitKeyEx(1)
                        if key in (ord('q'), ord('Q')):
                            break
                        elif key in (ord('f'), ord('F')):
                            fullscreen = not fullscreen
                            cv2.setWindowProperty(WINDOW_TITLE, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN if fullscreen else cv2.WINDOW_NORMAL)
                        
                        if not has_received_frame or (time.time() - last_frame_time > 3.0):
                            cv2.imshow(WINDOW_TITLE, get_placeholder_frame("Waiting for Stream..."))
                        if cv2.getWindowProperty(WINDOW_TITLE, cv2.WND_PROP_VISIBLE) < 1:
                            break
                        continue

                    size = struct.unpack('>I', raw_size)[0]
                    if size < 1 or size > 15 * 1024 * 1024:
                        break

                    data = recv_exact(sock, size)
                    if not data:
                        break

                    prefix = data[0:1]
                    payload = data[1:]

                    if prefix == b'a':
                        if pyaudio:
                            audio_queue.put(payload)
                    elif prefix == b'v':
                        buf = np.frombuffer(payload, dtype=np.uint8)
                        frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
                        if frame is not None:
                            cv2.imshow(WINDOW_TITLE, frame)
                            last_frame_time = time.time()
                            has_received_frame = True

                except socket.timeout:
                    key = cv2.waitKeyEx(1)
                    if key in (ord('q'), ord('Q')):
                        break
                    elif key in (ord('f'), ord('F')):
                        fullscreen = not fullscreen
                        cv2.setWindowProperty(WINDOW_TITLE, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN if fullscreen else cv2.WINDOW_NORMAL)
                    
                    if not has_received_frame or (time.time() - last_frame_time > 3.0):
                        cv2.imshow(WINDOW_TITLE, get_placeholder_frame("Waiting for Stream..."))
                    if cv2.getWindowProperty(WINDOW_TITLE, cv2.WND_PROP_VISIBLE) < 1:
                        break
                    continue
                except Exception as e:
                    callback_log(f"Stream error: {e}")
                    break

                key = cv2.waitKeyEx(1)
                if key in (ord('q'), ord('Q')):
                    break
                if cv2.getWindowProperty(WINDOW_TITLE, cv2.WND_PROP_VISIBLE) < 1:
                    break
        finally:
            audio_queue.put(None)
            sock.close()
            cv2.destroyAllWindows()
            callback_done()

    @staticmethod
    def run_global_viewer(relay_url, callback_log, callback_done):
        WINDOW_TITLE = 'ScreenMirror Pro (Global)'
        if not relay_url.endswith("/consumer"):
            relay_url = relay_url.rstrip("/") + "/consumer"
        callback_log(f"Connecting to global relay: {relay_url}...")
        
        try:
            import websocket
        except ImportError:
            callback_log("Error: 'websocket-client' package is missing.")
            callback_done()
            return
            
        pyaudio = load_pyaudio()
        if not pyaudio:
            callback_log("Warning: 'pyaudio' is missing. Speakers audio will be disabled.")
        
        try:
            ws = websocket.create_connection(relay_url)
            ws.settimeout(1.0)
            ws.send(json.dumps({
                'role': 'consumer',
                'hostname': socket.gethostname(),
                'device_id': socket.gethostname(),
                'connected_at': time.strftime('%Y-%m-%d %H:%M:%S')
            }))
            callback_log("Connected to Global Relay Server!")
        except Exception as e:
            callback_log(f"Global connection failed: {e}")
            callback_done()
            return
            
        audio_queue = queue.Queue()
        
        def audio_play_thread_fn():
            if not pyaudio:
                return
            p = pyaudio.PyAudio()
            try:
                audio_stream = p.open(format=pyaudio.paInt16,
                                      channels=1,
                                      rate=AUDIO_RATE,
                                      output=True,
                                      frames_per_buffer=1024)
            except Exception as e:
                callback_log(f"Speakers playback failed: {e}")
                p.terminate()
                return
                
            try:
                while True:
                    chunk = audio_queue.get()
                    if chunk is None:
                        break
                    try:
                        audio_stream.write(chunk)
                    except Exception:
                        break
            finally:
                try:
                    audio_stream.stop_stream()
                    audio_stream.close()
                except:
                    pass
                p.terminate()

        audio_play_thread = threading.Thread(target=audio_play_thread_fn, daemon=True)
        audio_play_thread.start()
        
        fullscreen = False
        cv2.namedWindow(WINDOW_TITLE, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(WINDOW_TITLE, 1280, 720)
        
        last_frame_time = time.time()
        has_received_frame = False
        
        cv2.imshow(WINDOW_TITLE, get_placeholder_frame("Connecting / Waiting for Stream..."))
        
        try:
            while True:
                try:
                    data = ws.recv()
                except websocket.WebSocketTimeoutException:
                    key = cv2.waitKeyEx(1)
                    if key in (ord('q'), ord('Q')):
                        break
                    elif key in (ord('f'), ord('F')):
                        fullscreen = not fullscreen
                        cv2.setWindowProperty(WINDOW_TITLE, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN if fullscreen else cv2.WINDOW_NORMAL)
                    
                    if not has_received_frame or (time.time() - last_frame_time > 3.0):
                        cv2.imshow(WINDOW_TITLE, get_placeholder_frame("Waiting for Stream..."))
                    if cv2.getWindowProperty(WINDOW_TITLE, cv2.WND_PROP_VISIBLE) < 1:
                        break
                    continue
                except Exception as e:
                    callback_log(f"Global connection closed: {e}")
                    break
                    
                if not data or not isinstance(data, bytes):
                    continue
                    
                prefix = data[0:1]
                payload = data[1:]
                
                if prefix == b'a':
                    if pyaudio:
                        audio_queue.put(payload)
                elif prefix == b'v':
                    buf = np.frombuffer(payload, dtype=np.uint8)
                    frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
                    
                    if frame is not None:
                        cv2.imshow(WINDOW_TITLE, frame)
                        last_frame_time = time.time()
                        has_received_frame = True
                    
                key = cv2.waitKeyEx(1)
                if key in (ord('q'), ord('Q')):
                    break
                elif key in (ord('f'), ord('F')):
                    fullscreen = not fullscreen
                    cv2.setWindowProperty(WINDOW_TITLE, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN if fullscreen else cv2.WINDOW_NORMAL)
                        
                if cv2.getWindowProperty(WINDOW_TITLE, cv2.WND_PROP_VISIBLE) < 1:
                    break
        except Exception as e:
            callback_log(f"Global Viewer Error: {e}")
        finally:
            audio_queue.put(None)
            try:
                ws.close()
            except:
                pass
            cv2.destroyAllWindows()
            callback_done()

class ModernApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ScreenMirror Pro Dashboard")
        self.root.geometry("900x650")
        
        self.style = ttk.Style()
        try:
            self.style.theme_use('vista')
        except:
            self.style.theme_use('clam')
            
        self.style.configure("Sidebar.TFrame", background="#f0f0f0")
        self.style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
        
        self.client_running = False
        self.scanner_running = False
        self.global_refresh_running = False
        self._queue = queue.Queue()
        self.custom_names = self.load_custom_names()
        
        self.connection_mode = StringVar(value="local")
        self.relay_url_var = StringVar(value="wss://stremer-production.up.railway.app")
        self.ip_entry_var = StringVar()
        self.global_devices = {}
        
        self.setup_ui()
        self.load_config()
        self.root.after(100, self._poll_queue)

    def setup_ui(self):
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)
        
        # Sidebar Panel
        sidebar = ttk.Frame(self.root, width=200, style="Sidebar.TFrame", padding=10)
        sidebar.grid(column=0, row=0, sticky=(N, S, E, W))
        sidebar.grid_propagate(False)
        
        self.pages = {}
        for text in ["Dashboard", "Scanner", "Settings", "Logs"]:
            ttk.Button(sidebar, text=text, command=lambda t=text: self.show_page(t)).pack(fill='x', pady=5)
            
        ttk.Label(sidebar, text="v2.0.0 (High-Q Voice)", background="#f0f0f0").pack(side='bottom', pady=(0, 5))
        ttk.Label(sidebar, text="Created by Mudassir Developer", font=("Segoe UI", 8, "italic"), background="#f0f0f0", foreground="#666").pack(side='bottom', pady=(0, 5))
        
        # Content Panel
        self.content_frame = ttk.Frame(self.root, padding=20)
        self.content_frame.grid(column=1, row=0, sticky=(N, S, E, W))
        self.content_frame.columnconfigure(0, weight=1)
        self.content_frame.rowconfigure(0, weight=1)
        
        # Create different views
        self.create_dashboard_page()
        self.create_scanner_page()
        self.create_settings_page()
        self.create_logs_page()
        self.show_page("Dashboard")
        
        self.root.after(1000, self.refresh_global_devices_periodically)

    def _setup_row_context_menu(self, widget):
        menu = Menu(self.root, tearoff=0)
        menu.add_command(label="Copy ID / IP", command=lambda w=widget: self.copy_row_id(w))
        menu.add_command(label="Assign Custom Name", command=lambda w=widget: self.edit_row_name(w))

        def on_right_click(event):
            row_id = widget.identify_row(event.y)
            if not row_id:
                return
            widget.selection_set(row_id)
            widget.focus(row_id)
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        widget.bind("<Button-3>", on_right_click)

    def copy_row_id(self, widget):
        sel = widget.selection()
        if not sel:
            return
        values = widget.item(sel[0], "values")
        if not values:
            return
        row_id = str(values[0])
        self.root.clipboard_clear()
        self.root.clipboard_append(row_id)
        self.log(f"Copied: {row_id}")

    def load_custom_names(self):
        try:
            if os.path.exists(NAMES_FILE):
                with open(NAMES_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return {str(k): str(v) for k, v in data.items() if str(v).strip()}
        except Exception:
            pass
        return {}

    def save_custom_names(self):
        try:
            with open(NAMES_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.custom_names, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.log(f"Failed to save custom names: {e}")

    def get_display_name(self, ip, hostname):
        custom_name = self.custom_names.get(str(ip), "").strip()
        return custom_name if custom_name else hostname

    def edit_row_name(self, widget):
        sel = widget.selection()
        if not sel:
            return
        values = widget.item(sel[0], "values")
        if not values:
            return

        ip = str(values[0])
        current_name = self.custom_names.get(ip, str(values[1]) if len(values) > 1 else "")
        new_name = simpledialog.askstring("Custom Name", f"Assign name to {ip}:", initialvalue=current_name, parent=self.root)
        if new_name is None:
            return

        new_name = new_name.strip()
        if new_name:
            self.custom_names[ip] = new_name
        else:
            self.custom_names.pop(ip, None)
        
        self.save_custom_names()
        self.refresh_device_tables()
        self.log(f"Updated display name for: {ip}")

    def refresh_device_tables(self):
        for tree in (self.tree, self.dash_tree):
            for item in tree.get_children():
                values = list(tree.item(item, "values"))
                if not values:
                    continue
                ip = str(values[0])
                if len(values) > 1:
                    values[1] = self.get_display_name(ip, str(values[1]))
                tree.item(item, values=values)

    def refresh_global_devices(self):
        if self.global_refresh_running:
            return
        self.global_refresh_running = True

        def worker():
            try:
                devices = AppLogic.fetch_global_devices(self.relay_url_var.get(), self.log)
                # Filter producers
                self.global_devices = {
                    str(item.get('device_id', '')): item 
                    for item in devices 
                    if isinstance(item, dict) and item.get('role') == 'producer'
                }
                self.root.after(0, self.render_global_devices)
            finally:
                self.global_refresh_running = False

        threading.Thread(target=worker, daemon=True).start()

    def refresh_global_devices_periodically(self):
        try:
            if self.connection_mode.get() == 'global':
                self.refresh_global_devices()
        finally:
            self.root.after(5000, self.refresh_global_devices_periodically)

    def render_global_devices(self):
        if not hasattr(self, 'global_tree'):
            return
        for item in self.global_tree.get_children():
            self.global_tree.delete(item)

        for device in self.global_devices.values():
            device_id = str(device.get('device_id', 'Unknown'))
            display_name = self.get_display_name(device_id, str(device.get('hostname', 'Unknown')))
            status = str(device.get('status', 'ACTIVE'))
            last_seen = str(device.get('last_seen', ''))
            self.global_tree.insert('', 'end', values=(device_id, display_name, status, last_seen))

    def create_dashboard_page(self):
        page = ttk.Frame(self.content_frame)
        self.pages["Dashboard"] = page
        ttk.Label(page, text="[SYS.MONITOR.DASHBOARD]", style="Title.TLabel").pack(anchor=W, pady=(0, 20))
        
        self.c_card = ttk.LabelFrame(page, text=" [ RECEIVER CONTROL INTERFACE ] ", padding=15)
        self.c_card.pack(fill='x', pady=10)
        self.c_status_var = StringVar(value="Status: CONNECT_READY")
        
        ttk.Label(self.c_card, textvariable=self.c_status_var, font=("Segoe UI", 10, "bold")).pack(side='left', padx=10)
        self.c_btn = ttk.Button(self.c_card, text="Open Viewer", command=self.toggle_client)
        self.c_btn.pack(side='right', padx=10)
        
        self.scan_dash_btn = ttk.Button(self.c_card, text="Scan LAN Devices", command=lambda: (self.show_page("Scanner"), self.start_scan()))
        self.scan_dash_btn.pack(side='right', padx=10)
        
        # Local LAN Active Tree
        self.local_list_label = ttk.Label(page, text="Local LAN Devices", font=("Segoe UI", 10, "bold"))
        self.local_list_label.pack(anchor=W, pady=(15, 5))
        
        cols = ('IP Address', 'Hostname', 'Status')
        self.dash_tree = ttk.Treeview(page, columns=cols, show='headings', height=5)
        for col in cols:
            self.dash_tree.heading(col, text=col)
            self.dash_tree.column(col, width=150)
        self.dash_tree.pack(fill='both', expand=True, pady=(0, 10))
        self.dash_tree.bind('<<TreeviewSelect>>', lambda e: self.dash_connect_btn.config(state='normal'))
        self._setup_row_context_menu(self.dash_tree)
        
        self.dash_connect_btn = ttk.Button(page, text="Connect to Selected", state='disabled', command=self.apply_dash_ip)
        self.dash_connect_btn.pack(anchor=E)
        
        # Global active devices list
        self.global_list_label = ttk.Label(page, text="Global Streamers (Internet Relay)", font=("Segoe UI", 10, "bold"))
        self.global_list_label.pack(anchor=W, pady=(15, 5))
        
        global_cols = ('Device ID', 'Display Name', 'Status', 'Last Seen')
        self.global_tree = ttk.Treeview(page, columns=global_cols, show='headings', height=5)
        for col in global_cols:
            self.global_tree.heading(col, text=col)
            self.global_tree.column(col, width=150)
        self.global_tree.pack(fill='both', expand=True, pady=(0, 10))
        self.global_tree.bind('<<TreeviewSelect>>', lambda e: self.dash_connect_btn.config(state='normal'))
        self._setup_row_context_menu(self.global_tree)

        self.info_card = ttk.LabelFrame(page, text=" Target Connection Info ", padding=10)
        self.info_card.pack(fill='x', pady=10)
        self.target_ip_var = StringVar(value="Target Config: Not Set")
        ttk.Label(self.info_card, textvariable=self.target_ip_var).pack(anchor=W)

    def create_scanner_page(self):
        page = ttk.Frame(self.content_frame)
        self.pages["Scanner"] = page
        ttk.Label(page, text="LAN Network Scanner", style="Title.TLabel").pack(anchor=W, pady=(0, 10))
        
        ctrl = ttk.Frame(page)
        ctrl.pack(fill='x', pady=10)
        self.scan_btn = ttk.Button(ctrl, text="Scan LAN", command=self.start_scan)
        self.scan_btn.pack(side='left', padx=(0, 10))
        ttk.Button(ctrl, text="Clear", command=self.clear_scanner_results).pack(side='left')
        
        cols = ('IP Address', 'Hostname', 'MAC Address', 'Status')
        self.tree = ttk.Treeview(page, columns=cols, show='headings', height=12)
        for col in cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=150)
        self.tree.pack(fill='both', expand=True, pady=10)
        self.tree.bind('<<TreeviewSelect>>', lambda e: self.apply_btn.config(state='normal'))
        self._setup_row_context_menu(self.tree)
        
        self.apply_btn = ttk.Button(page, text="Set Selected as Target", state='disabled', command=self.apply_selected_ip)
        self.apply_btn.pack(anchor=E, padx=20, pady=10)

    def create_settings_page(self):
        page = ttk.Frame(self.content_frame)
        self.pages["Settings"] = page
        ttk.Label(page, text="Configuration", style="Title.TLabel").pack(anchor=W, pady=(0, 20))
        
        form = ttk.Frame(page)
        form.pack(fill='both', expand=True)
        
        ttk.Label(form, text="Connection Mode:", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky=W, pady=10)
        mode_frame = ttk.Frame(form)
        mode_frame.grid(row=0, column=1, sticky=W, padx=10)
        ttk.Radiobutton(mode_frame, text="Local LAN Mode", variable=self.connection_mode, value="local", command=self.on_mode_change).pack(side='left', padx=5)
        ttk.Radiobutton(mode_frame, text="Global Internet Mode", variable=self.connection_mode, value="global", command=self.on_mode_change).pack(side='left', padx=5)
        
        # LAN Form
        self.local_settings_frame = ttk.LabelFrame(form, text=" Local LAN Settings ", padding=10)
        self.local_settings_frame.grid(row=1, column=0, columnspan=2, sticky=(W, E), pady=10)
        ttk.Label(self.local_settings_frame, text="Target IP Address:").grid(row=0, column=0, sticky=W, pady=5)
        self.ip_entry = ttk.Entry(self.local_settings_frame, textvariable=self.ip_entry_var, width=30)
        self.ip_entry.grid(row=0, column=1, sticky=W, padx=10)
        
        # Global Form
        self.global_settings_frame = ttk.LabelFrame(form, text=" Global Internet Settings ", padding=10)
        self.global_settings_frame.grid(row=2, column=0, columnspan=2, sticky=(W, E), pady=10)
        
        ttk.Label(self.global_settings_frame, text="Relay WS URL:").grid(row=0, column=0, sticky=W, pady=5)
        self.relay_url_entry = ttk.Entry(self.global_settings_frame, textvariable=self.relay_url_var, width=45)
        self.relay_url_entry.grid(row=0, column=1, sticky=W, padx=10)
        
        self.relay_test_var = StringVar(value="Relay Status: Not tested")
        ttk.Button(self.global_settings_frame, text="Test Relay Connection", command=self.test_relay_connection).grid(row=1, column=0, sticky=W, pady=8)
        ttk.Label(self.global_settings_frame, textvariable=self.relay_test_var).grid(row=1, column=1, sticky=W, padx=10)
        
        ttk.Button(page, text="Save Settings", command=self.save_config).pack(anchor=W, pady=20)
        self.on_mode_change()

    def on_mode_change(self):
        mode = self.connection_mode.get()
        if mode == "local":
            self.local_settings_frame.grid()
            self.global_settings_frame.grid_remove()
        else:
            self.local_settings_frame.grid_remove()
            self.global_settings_frame.grid()

    def create_logs_page(self):
        page = ttk.Frame(self.content_frame)
        self.pages["Logs"] = page
        self.log_area = scrolledtext.ScrolledText(page, wrap='word', height=20, bg="#1e1e1e", fg="#d4d4d4", font=("Consolas", 10))
        self.log_area.pack(fill='both', expand=True)

    def show_page(self, name):
        for n, p in self.pages.items():
            if n == name:
                p.pack(fill='both', expand=True)
            else:
                p.pack_forget()

    def log(self, text):
        self._queue.put(text)

    def _poll_queue(self):
        try:
            while True:
                msg = self._queue.get_nowait()
                if isinstance(msg, tuple):
                    msg = msg[1] if len(msg) > 1 else str(msg)
                self.log_area.insert('end', f"{msg}\n")
                self.log_area.see('end')
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def load_config(self):
        # Local IP config
        local_config_path = os.path.join(app_base_dir(), CONFIG_FILE)
        if os.path.exists(local_config_path):
            with open(local_config_path, 'r', encoding='utf-8') as f:
                self.ip_entry_var.set(f.read().strip())
        
        # Global URL config
        global_config_path = os.path.join(app_base_dir(), GLOBAL_CONFIG_FILE)
        if os.path.exists(global_config_path):
            with open(global_config_path, 'r', encoding='utf-8') as f:
                self.relay_url_var.set(normalize_relay_url(f.read().strip()))
                
        # UI options config
        ui_config_path = os.path.join(app_base_dir(), UI_CONFIG_FILE)
        if os.path.exists(ui_config_path):
            try:
                with open(ui_config_path, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                    self.connection_mode.set(cfg.get("connection_mode", "local"))
            except Exception:
                pass
                
        self.refresh_device_tables()
        self.update_dashboard_ui()

    def save_config(self):
        # IP
        ip = self.ip_entry_var.get().strip()
        with open(os.path.join(app_base_dir(), CONFIG_FILE), 'w', encoding='utf-8') as f: 
            f.write(ip)
            
        # URL
        url = normalize_relay_url(self.relay_url_var.get().strip())
        self.relay_url_var.set(url)
        with open(os.path.join(app_base_dir(), GLOBAL_CONFIG_FILE), 'w', encoding='utf-8') as f: 
            f.write(url)
            
        # UI JSON
        ui_config_path = os.path.join(app_base_dir(), UI_CONFIG_FILE)
        try:
            with open(ui_config_path, 'w', encoding='utf-8') as f:
                json.dump({"connection_mode": self.connection_mode.get()}, f, indent=2)
        except Exception as e:
            self.log(f"Failed to save UI JSON: {e}")
            
        self.update_dashboard_ui()
        self.log("Configurations saved successfully.")

    def test_relay_connection(self):
        relay_url = normalize_relay_url(self.relay_url_var.get().strip())
        self.relay_url_var.set(relay_url)

        if not relay_url:
            self.relay_test_var.set("Relay Status: Not connected")
            messagebox.showwarning("Warning", "Please configure a valid Relay WS URL first.")
            return

        self.relay_test_var.set("Relay Status: Testing...")
        def worker():
            ok, devices, message = AppLogic.test_relay_connection(relay_url, self.log)
            def done():
                if ok:
                    self.relay_test_var.set(f"Relay Status: Connected ({len(devices)} active)")
                    messagebox.showinfo("Relay Connection", message)
                else:
                    self.relay_test_var.set("Relay Status: Connection Failed")
                    messagebox.showerror("Relay Connection", f"Failed: {message}")
            self.root.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def start_scan(self):
        if self.scanner_running:
            return
        self.scanner_running = True
        self.scan_btn.config(state='disabled', text="Scanning...")
        self.tree.delete(*self.tree.get_children())
        self.dash_tree.delete(*self.dash_tree.get_children())
        
        def done():
            self.scanner_running = False
            self.root.after(0, lambda: self.scan_btn.config(state='normal', text="Scan LAN"))
            self.log("LAN scan completed.")

        threading.Thread(target=AppLogic.scan_network, 
                         args=(self.log, self.add_device, done), daemon=True).start()

    def add_device(self, d):
        ip = str(d[0])
        hostname = self.get_display_name(ip, str(d[1]))
        self.root.after(0, lambda: self.tree.insert('', 'end', values=(ip, hostname, d[2], d[3])))
        self.root.after(0, lambda: self.dash_tree.insert('', 'end', values=(ip, hostname, d[3])))

    def start_viewer(self, ip):
        if self.client_running:
            return
        self.client_running = True
        self.c_status_var.set("Status: LINK_ACTIVE (LOCAL)")
        self.c_btn.config(state='disabled')

        def viewer_done():
            self.root.after(0, self.on_viewer_closed)

        threading.Thread(
            target=AppLogic.run_viewer,
            args=(ip, self.log, viewer_done),
            daemon=True
        ).start()

    def start_global_viewer(self, url):
        if self.client_running:
            return
        self.client_running = True
        self.c_status_var.set("Status: LINK_ACTIVE (GLOBAL)")
        self.c_btn.config(state='disabled')

        def viewer_done():
            self.root.after(0, self.on_viewer_closed)

        threading.Thread(
            target=AppLogic.run_global_viewer,
            args=(url, self.log, viewer_done),
            daemon=True
        ).start()

    def toggle_client(self):
        mode = self.connection_mode.get()
        if mode == "local":
            ip = self.ip_entry_var.get().strip()
            if not ip:
                messagebox.showwarning("Warning", "Please set a Local Target IP address.")
                return
            self.start_viewer(ip)
        else:
            # Global Mode: Select selected device in table or fallback to URL directly
            sel = self.global_tree.selection()
            url = self.relay_url_var.get().strip()
            if not url:
                messagebox.showwarning("Warning", "Please set a Relay URL first.")
                return

            if sel:
                # Custom selection target format
                device_id = self.global_tree.item(sel[0], 'values')[0]
                # ws consumer registers connection directly, routing rules are handled via relay mapping
                target_url = f"{url.rstrip('/')}/consumer?target={device_id}"
                self.start_global_viewer(target_url)
            else:
                self.start_global_viewer(url)

    def on_viewer_closed(self):
        self.client_running = False
        self.c_status_var.set("Status: CONNECT_READY")
        self.c_btn.config(state='normal')
        self.update_dashboard_ui()
        self.log("Viewer window closed.")

    def update_dashboard_ui(self):
        if not hasattr(self, 'c_card') or not hasattr(self, 'target_ip_var'):
            return
            
        mode = self.connection_mode.get()
        if mode == "local":
            self.c_card.config(text=" [ Receiver Client - Direct TCP LAN Mode ] ")
            self.scan_dash_btn.pack(side='right', padx=10)
            self.local_list_label.pack(anchor=W, pady=(15, 5))
            self.dash_tree.pack(fill='both', expand=True, pady=(0, 10))
            self.dash_connect_btn.pack(anchor=E)
            self.target_ip_var.set(f"Target Config: LOCAL_IP = {self.ip_entry_var.get()}")
            self.global_list_label.pack_forget()
            self.global_tree.pack_forget()
        else:
            self.c_card.config(text=" [ Receiver Client - Cloud WS Relay Mode ] ")
            self.scan_dash_btn.pack_forget()
            self.local_list_label.pack_forget()
            self.dash_tree.pack_forget()
            self.dash_connect_btn.pack_forget()
            self.target_ip_var.set(f"Target Config: RELAY_ENDPOINT = {self.relay_url_var.get()}")
            self.global_list_label.pack(anchor=W, pady=(15, 5))
            self.global_tree.pack(fill='both', expand=True, pady=(0, 10))

        if self.client_running:
            self.c_status_var.set("Status: FEED_ACTIVE")
            self.c_btn.config(state='disabled')
        else:
            self.c_status_var.set("Status: CONNECT_READY")
            self.c_btn.config(state='normal')

    def apply_selected_ip(self):
        sel = self.tree.selection()
        if sel:
            ip = self.tree.item(sel[0], 'values')[0]
            self.ip_entry_var.set(ip)
            self.save_config()
            self.show_page("Dashboard")

    def apply_dash_ip(self):
        sel = self.dash_tree.selection()
        if sel:
            ip = self.dash_tree.item(sel[0], 'values')[0]
            self.ip_entry_var.set(ip)
            self.save_config()
            self.toggle_client()

    def clear_scanner_results(self):
        self.tree.delete(*self.tree.get_children())
        self.dash_tree.delete(*self.dash_tree.get_children())

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    install_exception_hook()
    try:
        root = Tk()
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except:
            pass
        app = ModernApp(root)
        root.mainloop()
    except KeyboardInterrupt:
        pass
    except Exception:
        write_crash_log(traceback.format_exc())
        raise
