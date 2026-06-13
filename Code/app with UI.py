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
from tkinter import Tk, StringVar, IntVar, ttk, scrolledtext, N, S, E, W, PhotoImage, messagebox, Menu, simpledialog

# Settings and constants
import traceback
CONFIG_FILE = "config.txt"
NAMES_FILE = "device_names.json"
DEFAULT_PORT = 9999

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

# =============================================================================
# CORE LOGIC WRAPPERS (Running in Threads)
# =============================================================================

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
        chunk = sock.recv(n - len(data))
        if not chunk:
            return None
        data += chunk
    return data



def check_ping(ip):
    """Socket se ping - subprocess spawn nahi hota"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        # Common ports try karo
        for port in [135, 139, 445, 80, 22]:
            try:
                result = s.connect_ex((ip, port))
                if result == 0:
                    s.close()
                    return True
            except:
                pass
        s.close()
        # ICMP fallback
        result = subprocess.run(
            ['ping', '-n', '1', '-w', '200', ip],
            capture_output=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            timeout=1
        )
        return result.returncode == 0
    except Exception:
        return False

def check_server_stream(ip):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.5)
        s.connect((ip, DEFAULT_PORT))
        raw_size = recv_exact(s, 4)
        if not raw_size:
            return False
        frame_size = struct.unpack('>I', raw_size)[0]
        if frame_size < 1024 or frame_size > 15 * 1024 * 1024:
            return False
        header = recv_exact(s, 2)
        s.close()
        return header == b'\xff\xd8'
    except Exception:
        return False

def resolve_hostname(ip):
    try:
        return socket.gethostbyaddr(ip)[0]
    except Exception:
        pass

    try:
        result = subprocess.run(
            ['ping', '-a', '-n', '1', '-w', '300', ip],
            capture_output=True,
            text=True,
            timeout=2,
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
            except: pass

        threads = []
        for i in range(1, 255):
            t = threading.Thread(target=scan_worker, args=(i,), daemon=True)
            threads.append(t)
            t.start()
            if len(threads) >= 40:
                for t in threads: t.join()
                threads = []
        for t in threads: t.join()
        callback_done()

    @staticmethod
    def run_viewer(ip, callback_log, callback_done):
        callback_log(f"Connecting to {ip}:{DEFAULT_PORT}...")
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.settimeout(5.0)
            sock.connect((ip, DEFAULT_PORT))
            callback_log("Connected to Stream!")
        except Exception as e:
            callback_log(f"Connection failed: {e}")
            callback_done()
            return



        def recv_exact(s, n):
            data = b''
            while len(data) < n:
                chunk = s.recv(n - len(data))
                if not chunk: return None
                data += chunk
            return data

        try:
            cv2.namedWindow('ScreenMirror Pro', cv2.WINDOW_NORMAL)
            fullscreen = False



            while True:
                raw_size = recv_exact(sock, 4)
                if not raw_size: break
                size = struct.unpack('>I', raw_size)[0]
                data = recv_exact(sock, size)
                if not data: break
                
                frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
                if frame is not None:
                    cv2.resizeWindow('ScreenMirror Pro', frame.shape[1], frame.shape[0])
                    cv2.imshow('ScreenMirror Pro', frame)
                
                key = cv2.waitKeyEx(1)
                if key in (ord('q'), ord('Q')): break
                if key in (ord('f'), ord('F')):
                    fullscreen = not fullscreen
                    cv2.setWindowProperty('ScreenMirror Pro', cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN if fullscreen else cv2.WINDOW_NORMAL)
                
                if cv2.getWindowProperty('ScreenMirror Pro', cv2.WND_PROP_VISIBLE) < 1: break
        except Exception as e:
            callback_log(f"Viewer Error: {e}")
        finally:
            sock.close()
            cv2.destroyAllWindows()
            callback_done()

    @staticmethod
    def run_global_viewer(relay_url, callback_log, callback_done):
        if not relay_url.endswith("/consumer"):
            relay_url = relay_url.rstrip("/") + "/consumer"
        callback_log(f"Connecting to global relay: {relay_url}...")
        
        try:
            import websocket
        except ImportError:
            callback_log("Error: 'websocket-client' package is missing. Run 'pip install websocket-client'.")
            callback_done()
            return
            
        try:
            import pyaudio
        except ImportError:
            pyaudio = None
            callback_log("Warning: 'pyaudio' is missing. Voice output will be disabled.")
        
        try:
            ws = websocket.create_connection(relay_url)
            callback_log("Connected to Global Stream!")
        except Exception as e:
            callback_log(f"Global connection failed: {e}")
            callback_done()
            return
            
        audio_queue = queue.Queue()
        audio_stream = None
        p = None
        
        if pyaudio:
            def audio_play_thread_fn():
                nonlocal p, audio_stream
                p = pyaudio.PyAudio()
                try:
                    audio_stream = p.open(format=pyaudio.paInt16,
                                          channels=1,
                                          rate=16000,
                                          output=True,
                                          frames_per_buffer=1024)
                except Exception as e:
                    callback_log(f"Speakers playback failed: {e}")
                    p.terminate()
                    p = None
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
                    if p:
                        p.terminate()

            audio_play_thread = threading.Thread(target=audio_play_thread_fn, daemon=True)
            audio_play_thread.start()
        
        fullscreen = False
        cv2.namedWindow('ScreenMirror Pro (Global)', cv2.WINDOW_NORMAL)
        cv2.resizeWindow('ScreenMirror Pro (Global)', 1280, 720)
        
        try:
            while True:
                try:
                    data = ws.recv()
                except Exception as e:
                    callback_log(f"Global Connection closed: {e}")
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
                        cv2.imshow('ScreenMirror Pro (Global)', frame)
                    
                key = cv2.waitKeyEx(1)
                if key in (ord('q'), ord('Q')):
                    break
                elif key in (ord('f'), ord('F')):
                    fullscreen = not fullscreen
                    if fullscreen:
                        cv2.setWindowProperty('ScreenMirror Pro (Global)', cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
                    else:
                        cv2.setWindowProperty('ScreenMirror Pro (Global)', cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_NORMAL)
                        
                if cv2.getWindowProperty('ScreenMirror Pro (Global)', cv2.WND_PROP_VISIBLE) < 1:
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

    @staticmethod
    def run_global_streamer(relay_url, callback_log, callback_done, stop_event):
        if not relay_url.endswith("/producer"):
            relay_url = relay_url.rstrip("/") + "/producer"
        callback_log(f"Connecting to global relay for streaming: {relay_url}...")
        
        try:
            import websocket
        except ImportError:
            callback_log("Error: 'websocket-client' package is missing. Run 'pip install websocket-client'.")
            callback_done()
            return
            
        try:
            import pyaudio
        except ImportError:
            pyaudio = None
            callback_log("Warning: 'pyaudio' is missing. Voice streaming will be disabled.")
            
        try:
            import mss
        except ImportError:
            callback_log("Error: 'mss' package is missing.")
            callback_done()
            return
        
        try:
            ws = websocket.create_connection(relay_url)
            callback_log("Connected! Global Screen Sharing Active (Video + Voice).")
        except Exception as e:
            callback_log(f"Global streaming connection failed: {e}")
            callback_done()
            return

        ws_lock = threading.Lock()
        
        def send_safe(prefix, payload):
            try:
                with ws_lock:
                    ws.send_binary(prefix + payload)
            except Exception as e:
                raise e

        audio_stream = None
        p = None
        if pyaudio:
            p = pyaudio.PyAudio()
            try:
                audio_stream = p.open(format=pyaudio.paInt16,
                                      channels=1,
                                      rate=16000,
                                      input=True,
                                      frames_per_buffer=1024)
                callback_log("Microphone voice capture started.")
            except Exception as e:
                callback_log(f"Microphone capture not available: {e}")
                p.terminate()
                p = None
                
        def audio_thread_fn():
            if not audio_stream:
                return
            try:
                while not stop_event.is_set():
                    audio_data = audio_stream.read(1024, exception_on_overflow=False)
                    send_safe(b'a', audio_data)
            except Exception:
                pass
            finally:
                try:
                    audio_stream.stop_stream()
                    audio_stream.close()
                except:
                    pass
                if p:
                    p.terminate()

        if audio_stream:
            audio_thread = threading.Thread(target=audio_thread_fn, daemon=True)
            audio_thread.start()

        FPS_VAL = 15
        QUALITY_VAL = 80
        MONITOR_VAL = 1
        frame_time = 1.0 / FPS_VAL

        try:
            with mss.mss() as sct:
                monitor = sct.monitors[MONITOR_VAL]
                
                while not stop_event.is_set():
                    t_start = time.time()
                    
                    img = np.array(sct.grab(monitor))
                    img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                    
                    _, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, QUALITY_VAL])
                    data = buf.tobytes()
                    
                    try:
                        send_safe(b'v', data)
                    except Exception as e:
                        callback_log(f"Socket disconnected: {e}")
                        break
                    
                    elapsed = time.time() - t_start
                    sleep_time = frame_time - elapsed
                    if sleep_time > 0:
                        steps = int(sleep_time / 0.05)
                        for _ in range(steps):
                            if stop_event.is_set():
                                break
                            time.sleep(0.05)
                        rem = sleep_time - (steps * 0.05)
                        if rem > 0 and not stop_event.is_set():
                            time.sleep(rem)
        except Exception as e:
            callback_log(f"Streaming error: {e}")
        finally:
            try:
                ws.close()
            except:
                pass
            callback_log("Global Screen Sharing Stopped.")
            callback_done()


# =============================================================================
# GUI APPLICATION
# =============================================================================

class ModernApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ScreenMirror Pro")
        self.root.geometry("900x650")
        
        self.style = ttk.Style()
        try: self.style.theme_use('vista')
        except: self.style.theme_use('clam')
            
        self.style.configure("Sidebar.TFrame", background="#f0f0f0")
        self.style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
        
        self.client_running = False
        self.scanner_running = False
        self.viewer_proc = None
        self._queue = queue.Queue()
        self.custom_names = self.load_custom_names()
        
        # Connection settings StringVars
        self.connection_mode = StringVar(value="local")
        self.relay_url_var = StringVar(value="ws://localhost:8080")
        self.global_role = StringVar(value="viewer")
        self.ip_entry_var = StringVar()
        self.streamer_running = False
        self.streamer_stop_event = None
        
        self.setup_ui()
        self.load_config()
        self.root.after(100, self._poll_queue)
        # Auto scan on start (disabled) -- user requested manual scan via dashboard

    def setup_ui(self):
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)
        
        sidebar = ttk.Frame(self.root, width=200, style="Sidebar.TFrame", padding=10)
        sidebar.grid(column=0, row=0, sticky=(N, S, E, W))
        sidebar.grid_propagate(False)
        
        self.pages = {}
        for text in ["Dashboard", "Scanner", "Settings", "Logs"]:
            ttk.Button(sidebar, text=text, command=lambda t=text: self.show_page(t)).pack(fill='x', pady=5)
            
        ttk.Label(sidebar, text="v1.2.0 (Stable)", background="#f0f0f0").pack(side='bottom', pady=(0, 5))
        ttk.Label(sidebar, text="Created by Mudassir Developer", font=("Segoe UI", 8, "italic"), background="#f0f0f0", foreground="#666").pack(side='bottom', pady=(0, 5))
        
        self.content_frame = ttk.Frame(self.root, padding=20)
        self.content_frame.grid(column=1, row=0, sticky=(N, S, E, W))
        self.content_frame.columnconfigure(0, weight=1)
        self.content_frame.rowconfigure(0, weight=1)
        
        self.create_dashboard_page()
        self.create_scanner_page()
        self.create_settings_page()
        self.create_logs_page()
        self.show_page("Dashboard")

    def _setup_row_context_menu(self, widget):
        menu = Menu(self.root, tearoff=0)
        menu.add_command(label="Copy ID", command=lambda w=widget: self.copy_row_id(w))
        menu.add_command(label="Edit Name", command=lambda w=widget: self.edit_row_name(w))

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
        self.log(f"Copied ID: {row_id}")

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
            self.log(f"Failed to save names: {e}")

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
        new_name = simpledialog.askstring("Edit Name", f"Enter name for {ip}:", initialvalue=current_name, parent=self.root)
        if new_name is None:
            return

        new_name = new_name.strip()
        if new_name:
            self.custom_names[ip] = new_name
        else:
            self.custom_names.pop(ip, None)
        self.save_custom_names()
        self.refresh_device_tables()
        self.log(f"Updated name for {ip}")

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

    def create_dashboard_page(self):
        page = ttk.Frame(self.content_frame); self.pages["Dashboard"] = page
        ttk.Label(page, text="System Dashboard", style="Title.TLabel").pack(anchor=W, pady=(0, 20))
        
        self.c_card = ttk.LabelFrame(page, text=" Live Viewer Client ", padding=15)
        self.c_card.pack(fill='x', pady=10)
        self.c_status_var = StringVar(value="Status: Ready")
        ttk.Label(self.c_card, textvariable=self.c_status_var, font=("Segoe UI", 10, "bold")).pack(side='left', padx=10)
        self.c_btn = ttk.Button(self.c_card, text="Open Viewer", command=self.toggle_client)
        self.c_btn.pack(side='right', padx=10)
        # Quick scan button on dashboard
        self.scan_dash_btn = ttk.Button(self.c_card, text="Scan Network", command=lambda: (self.show_page("Scanner"), self.start_scan()))
        self.scan_dash_btn.pack(side='right', padx=10)
        
        self.quick_connect_label = ttk.Label(page, text="Quick Connect - Online Devices", font=("Segoe UI", 10, "bold"))
        self.quick_connect_label.pack(anchor=W, pady=(20, 5))
        cols = ('IP Address', 'Hostname', 'Status')
        self.dash_tree = ttk.Treeview(page, columns=cols, show='headings', height=8)
        for col in cols:
            self.dash_tree.heading(col, text=col)
            self.dash_tree.column(col, width=150)
        self.dash_tree.pack(fill='both', expand=True, pady=(0, 10))
        self.dash_tree.bind('<<TreeviewSelect>>', lambda e: self.dash_connect_btn.config(state='normal'))
        self._setup_row_context_menu(self.dash_tree)
        
        self.dash_connect_btn = ttk.Button(page, text="Connect to Selected", state='disabled', command=self.apply_dash_ip)
        self.dash_connect_btn.pack(anchor=E)

        self.info_card = ttk.LabelFrame(page, text=" Connection Info ", padding=15)
        self.info_card.pack(fill='x', pady=10)
        self.target_ip_var = StringVar(value="Target IP: Not Set")
        ttk.Label(self.info_card, textvariable=self.target_ip_var).pack(anchor=W)

    def create_scanner_page(self):
        page = ttk.Frame(self.content_frame); self.pages["Scanner"] = page
        ttk.Label(page, text="Network Scanner", style="Title.TLabel").pack(anchor=W, pady=(0, 10))
        
        ctrl = ttk.Frame(page); ctrl.pack(fill='x', pady=10)
        self.scan_btn = ttk.Button(ctrl, text="Scan", command=self.start_scan)
        self.scan_btn.pack(side='left', padx=(0, 10))
        ttk.Button(ctrl, text="Clear List", command=self.clear_scanner_results).pack(side='left')
        
        cols = ('IP Address', 'Hostname', 'MAC Address', 'Status')
        self.tree = ttk.Treeview(page, columns=cols, show='headings', height=10)
        for col in cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=150)
        self.tree.pack(fill='both', expand=True, pady=10)
        self.tree.bind('<<TreeviewSelect>>', lambda e: self.apply_btn.config(state='normal'))
        self._setup_row_context_menu(self.tree)
        
        self.apply_btn = ttk.Button(page, text="Set Selected as Target", state='disabled', command=self.apply_selected_ip)
        self.apply_btn.pack(anchor=E, padx=20, pady=10)

    def create_settings_page(self):
        page = ttk.Frame(self.content_frame); self.pages["Settings"] = page
        ttk.Label(page, text="Configuration", style="Title.TLabel").pack(anchor=W, pady=(0, 20))
        
        form = ttk.Frame(page); form.pack(fill='both', expand=True)
        
        # Mode Selection
        ttk.Label(form, text="Connection Mode:", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky=W, pady=10)
        mode_frame = ttk.Frame(form)
        mode_frame.grid(row=0, column=1, sticky=W, padx=10)
        ttk.Radiobutton(mode_frame, text="Local LAN Mode", variable=self.connection_mode, value="local", command=self.on_mode_change).pack(side='left', padx=5)
        ttk.Radiobutton(mode_frame, text="Global Internet Mode", variable=self.connection_mode, value="global", command=self.on_mode_change).pack(side='left', padx=5)
        
        # Local Mode Section
        self.local_settings_frame = ttk.LabelFrame(form, text=" Local LAN Settings ", padding=10)
        self.local_settings_frame.grid(row=1, column=0, columnspan=2, sticky=(W, E), pady=10)
        
        ttk.Label(self.local_settings_frame, text="Target IP Address:").grid(row=0, column=0, sticky=W, pady=5)
        self.ip_entry = ttk.Entry(self.local_settings_frame, textvariable=self.ip_entry_var, width=30)
        self.ip_entry.grid(row=0, column=1, sticky=W, padx=10)
        
        # Global Mode Section
        self.global_settings_frame = ttk.LabelFrame(form, text=" Global Internet Settings ", padding=10)
        self.global_settings_frame.grid(row=2, column=0, columnspan=2, sticky=(W, E), pady=10)
        
        ttk.Label(self.global_settings_frame, text="Relay WS URL:").grid(row=0, column=0, sticky=W, pady=5)
        self.relay_url_entry = ttk.Entry(self.global_settings_frame, textvariable=self.relay_url_var, width=45)
        self.relay_url_entry.grid(row=0, column=1, sticky=W, padx=10)
        
        ttk.Label(self.global_settings_frame, text="Global Role:").grid(row=1, column=0, sticky=W, pady=5)
        role_frame = ttk.Frame(self.global_settings_frame)
        role_frame.grid(row=1, column=1, sticky=W, padx=10, pady=5)
        ttk.Radiobutton(role_frame, text="Watch Screen (Viewer)", variable=self.global_role, value="viewer").pack(side='left', padx=5)
        ttk.Radiobutton(role_frame, text="Share Screen & Voice (Streamer)", variable=self.global_role, value="streamer").pack(side='left', padx=5)
        
        # Save Button
        ttk.Button(page, text="Save Settings", command=self.save_config).pack(anchor=W, pady=20)
        
        # Trigger visibility update on start
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
        page = ttk.Frame(self.content_frame); self.pages["Logs"] = page
        self.log_area = scrolledtext.ScrolledText(page, wrap='word', height=20, bg="#1e1e1e", fg="#d4d4d4", font=("Consolas", 10))
        self.log_area.pack(fill='both', expand=True)

    def show_page(self, name):
        for n, p in self.pages.items():
            if n == name: p.pack(fill='both', expand=True)
            else: p.pack_forget()

    def log(self, text): self._queue.put(text)

    def _poll_queue(self):
        try:
            while True:
                msg = self._queue.get_nowait()
                # tuple ya string dono handle karo
                if isinstance(msg, tuple):
                    msg = msg[1] if len(msg) > 1 else str(msg)
                self.log_area.insert('end', f"{msg}\n")
                self.log_area.see('end')
        except queue.Empty: pass
        self.root.after(100, self._poll_queue)

    def load_config(self):
        # Read local IP
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                ip = f.read().strip()
                self.ip_entry_var.set(ip)
        
        # Read relay URL from config_global.txt
        global_config_path = "config_global.txt"
        if os.path.exists(global_config_path):
            with open(global_config_path, 'r') as f:
                url = f.read().strip()
                self.relay_url_var.set(url)
                
        # Read JSON UI config if it exists
        ui_config_path = "config_ui.json"
        if os.path.exists(ui_config_path):
            try:
                with open(ui_config_path, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                    self.connection_mode.set(cfg.get("connection_mode", "local"))
                    self.global_role.set(cfg.get("global_role", "viewer"))
            except Exception:
                pass
                
        self.refresh_device_tables()
        self.update_dashboard_ui()

    def save_config(self):
        # Save IP
        ip = self.ip_entry_var.get().strip()
        with open(CONFIG_FILE, 'w') as f: 
            f.write(ip)
            
        # Save Relay URL to config_global.txt
        url = self.relay_url_var.get().strip()
        with open("config_global.txt", 'w') as f: 
            f.write(url)
            
        # Save JSON UI config
        ui_config_path = "config_ui.json"
        cfg = {
            "connection_mode": self.connection_mode.get(),
            "global_role": self.global_role.get()
        }
        try:
            with open(ui_config_path, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, indent=2)
        except Exception as e:
            self.log(f"Failed to save UI config: {e}")
            
        self.update_dashboard_ui()
        self.log("Settings saved.")

    def start_scan(self):
        if self.scanner_running: return
        self.scanner_running = True
        self.scan_btn.config(state='disabled', text="Scanning...")
        self.tree.delete(*self.tree.get_children())
        self.dash_tree.delete(*self.dash_tree.get_children())
        
        def done():
            self.scanner_running = False
            self.root.after(0, lambda: self.scan_btn.config(state='normal', text="Refresh"))
            self.log("Scan Finished.")

        threading.Thread(target=AppLogic.scan_network, 
                         args=(self.log, self.add_device, done), daemon=True).start()

    def start_viewer(self, ip):
        if self.client_running:
            return

        try:
            ip = str(ipaddress.IPv4Address(ip.strip()))
        except Exception:
            messagebox.showwarning("Warning", "Please enter a valid IPv4 address.")
            return

        self.client_running = True
        self.c_status_var.set("Status: Running")
        self.c_btn.config(state='disabled')

        def viewer_done():
            self.root.after(0, lambda: self.on_process_exit("viewer"))

        threading.Thread(
            target=AppLogic.run_viewer,
            args=(ip, self.log, viewer_done),
            daemon=True
        ).start()

    def start_global_viewer(self, url):
        if self.client_running:
            return

        self.client_running = True
        self.c_status_var.set("Status: Running (Viewer)")
        self.c_btn.config(state='disabled')

        def viewer_done():
            self.root.after(0, lambda: self.on_process_exit("viewer"))

        threading.Thread(
            target=AppLogic.run_global_viewer,
            args=(url, self.log, viewer_done),
            daemon=True
        ).start()

    def toggle_global_streamer(self, url):
        if self.streamer_running:
            if self.streamer_stop_event:
                self.streamer_stop_event.set()
            return

        self.streamer_running = True
        self.c_status_var.set("Status: Sharing Screen")
        self.c_btn.config(text="Stop Sharing")
        self.streamer_stop_event = threading.Event()

        def streamer_done():
            self.root.after(0, self.on_streamer_exit)

        threading.Thread(
            target=AppLogic.run_global_streamer,
            args=(url, self.log, streamer_done, self.streamer_stop_event),
            daemon=True
        ).start()

    def on_streamer_exit(self):
        self.streamer_running = False
        self.streamer_stop_event = None
        self.update_dashboard_ui()

    def update_dashboard_ui(self):
        if not hasattr(self, 'c_card') or not hasattr(self, 'target_ip_var'):
            return
            
        mode = self.connection_mode.get()
        if mode == "local":
            self.c_card.config(text=" Live Viewer Client (Local LAN) ")
            if self.client_running:
                self.c_status_var.set("Status: Running")
                self.c_btn.config(text="Open Viewer", state='disabled')
            else:
                self.c_status_var.set("Status: Ready")
                self.c_btn.config(text="Open Viewer", state='normal')
            self.scan_dash_btn.pack(side='right', padx=10)
            self.quick_connect_label.pack(anchor=W, pady=(20, 5))
            self.dash_tree.pack(fill='both', expand=True, pady=(0, 10))
            self.dash_connect_btn.pack(anchor=E)
            self.target_ip_var.set(f"Target IP: {self.ip_entry_var.get()}")
            self.info_card.config(text=" Connection Info (Local LAN) ")
        else:
            role = self.global_role.get()
            self.scan_dash_btn.pack_forget()
            self.quick_connect_label.pack_forget()
            self.dash_tree.pack_forget()
            self.dash_connect_btn.pack_forget()
            
            if role == "viewer":
                self.c_card.config(text=" Live Viewer Client (Global Internet) ")
                if self.client_running:
                    self.c_status_var.set("Status: Running")
                    self.c_btn.config(text="Open Global Viewer", state='disabled')
                else:
                    self.c_status_var.set("Status: Ready")
                    self.c_btn.config(text="Open Global Viewer", state='normal')
            else:
                self.c_card.config(text=" Live Screen Share (Global Internet) ")
                if self.streamer_running:
                    self.c_status_var.set("Status: Sharing Screen")
                    self.c_btn.config(text="Stop Sharing", state='normal')
                else:
                    self.c_status_var.set("Status: Ready")
                    self.c_btn.config(text="Start Sharing", state='normal')
                    
            self.target_ip_var.set(f"Relay URL: {self.relay_url_var.get()}")
            self.info_card.config(text=" Connection Info (Global Internet) ")

    def _reader_thread(self, proc, mode):
        pass  # Not used anymore

    def add_device(self, d):
        ip = str(d[0])
        hostname = self.get_display_name(ip, str(d[1]))
        self.root.after(0, lambda: self.tree.insert('', 'end', values=(ip, hostname, d[2], d[3])))
        self.root.after(0, lambda: self.dash_tree.insert('', 'end', values=(ip, hostname, d[3])))

    def toggle_client(self):
        mode = self.connection_mode.get()
        if mode == "local":
            ip = self.ip_entry_var.get()
            if not ip:
                messagebox.showwarning("Warning", "Please set a Target IP first.")
                return
            self.start_viewer(ip)
        else:
            role = self.global_role.get()
            url = self.relay_url_var.get().strip()
            if not url:
                messagebox.showwarning("Warning", "Please set a Relay WS URL first.")
                return
            
            if role == "viewer":
                self.start_global_viewer(url)
            else:
                self.toggle_global_streamer(url)

    def clear_scanner_results(self):
        self.tree.delete(*self.tree.get_children())
        self.dash_tree.delete(*self.dash_tree.get_children())
        self.scan_btn.config(text="Scan")

    def on_process_exit(self, mode):
        if mode == "viewer":
            self.client_running = False
            self.viewer_proc = None
            self.c_status_var.set("Status: Ready")
            self.c_btn.config(state='normal')
            self.update_dashboard_ui()
            self.log("Viewer closed.")

    def apply_selected_ip(self):
        sel = self.tree.selection()
        if sel:
            ip = self.tree.item(sel[0], 'values')[0]
            self.ip_entry_var.set(ip); self.save_config(); self.show_page("Dashboard")

    def apply_dash_ip(self):
        sel = self.dash_tree.selection()
        if sel:
            ip = self.dash_tree.item(sel[0], 'values')[0]
            self.ip_entry_var.set(ip); self.save_config(); self.toggle_client()

if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    install_exception_hook()
    try:
        root = Tk()
        try:
            from ctypes import windll
            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
        app = ModernApp(root)
        root.mainloop()
    except KeyboardInterrupt:
        pass
    except Exception:
        write_crash_log(traceback.format_exc())
        raise