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
        
        c_card = ttk.LabelFrame(page, text=" Live Viewer Client ", padding=15)
        c_card.pack(fill='x', pady=10)
        self.c_status_var = StringVar(value="Status: Ready")
        ttk.Label(c_card, textvariable=self.c_status_var, font=("Segoe UI", 10, "bold")).pack(side='left', padx=10)
        self.c_btn = ttk.Button(c_card, text="Open Viewer", command=self.toggle_client)
        self.c_btn.pack(side='right', padx=10)
        # Quick scan button on dashboard
        self.scan_dash_btn = ttk.Button(c_card, text="Scan Network", command=lambda: (self.show_page("Scanner"), self.start_scan()))
        self.scan_dash_btn.pack(side='right', padx=10)
        
        ttk.Label(page, text="Quick Connect - Online Devices", font=("Segoe UI", 10, "bold")).pack(anchor=W, pady=(20, 5))
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

        info = ttk.LabelFrame(page, text=" Connection Info ", padding=15)
        info.pack(fill='x', pady=10)
        self.target_ip_var = StringVar(value="Target IP: Not Set")
        ttk.Label(info, textvariable=self.target_ip_var).pack(anchor=W)

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
        form = ttk.Frame(page); form.pack(fill='x')
        ttk.Label(form, text="Target IP Address:").grid(row=0, column=0, sticky=W, pady=5)
        self.ip_entry_var = StringVar()
        ttk.Entry(form, textvariable=self.ip_entry_var, width=30).grid(row=0, column=1, sticky=W, padx=10)
        ttk.Button(page, text="Save Settings", command=self.save_config).pack(anchor=W, pady=20)

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
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r') as f:
                ip = f.read().strip()
                self.ip_entry_var.set(ip)
                self.target_ip_var.set(f"Target IP: {ip}")
        self.refresh_device_tables()

    def save_config(self):
        ip = self.ip_entry_var.get().strip()
        with open(CONFIG_FILE, 'w') as f: f.write(ip)
        self.target_ip_var.set(f"Target IP: {ip}")

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

        # Direct thread - subprocess loop fix
        threading.Thread(
            target=AppLogic.run_viewer,
            args=(ip, self.log, viewer_done),
            daemon=True
        ).start()

    def _reader_thread(self, proc, mode):
        pass  # Not used anymore

    def add_device(self, d):
        ip = str(d[0])
        hostname = self.get_display_name(ip, str(d[1]))
        self.root.after(0, lambda: self.tree.insert('', 'end', values=(ip, hostname, d[2], d[3])))
        self.root.after(0, lambda: self.dash_tree.insert('', 'end', values=(ip, hostname, d[3])))

    def toggle_client(self):
        ip = self.ip_entry_var.get()
        if not ip:
            messagebox.showwarning("Warning", "Please set a Target IP first.")
            return
        self.start_viewer(ip)

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