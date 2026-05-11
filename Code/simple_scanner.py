"""
simple_scanner.py - Simple Command Line Network Scanner
Koi GUI nahi, bas command line par results
"""

import socket
import subprocess
import threading
import sys
import os
import struct
import ipaddress
import re

PORT = 9999

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return '192.168.1.1'

def ping(ip):
    try:
        result = subprocess.run(
            ['ping', '-n', '1', '-w', '300', ip],
            capture_output=True, text=True, timeout=2
        )
        return result.returncode == 0
    except:
        return False

def check_server_port(ip):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.5)
        result = s.connect_ex((ip, PORT))
        s.close()
        return result == 0
    except:
        return False


def check_ping(ip):
    try:
        result = subprocess.run(
            ['ping', '-n', '1', '-w', '300', ip],
            capture_output=True, text=True, timeout=2
        )
        return result.returncode == 0
    except:
        return False


def recv_exact(sock, n):
    data = b''
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            return None
        data += chunk
    return data


def check_server_stream(ip):
    """Port open hone ke saath stream format bhi verify karo (size + JPEG)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.5)
        s.connect((ip, PORT))

        raw_size = recv_exact(s, 4)
        if not raw_size:
            s.close()
            return False

        frame_size = struct.unpack('>I', raw_size)[0]
        # Basic sanity check taake random services false positive na dein.
        if frame_size < 1024 or frame_size > 15 * 1024 * 1024:
            s.close()
            return False

        header = recv_exact(s, 2)
        s.close()
        if not header:
            return False

        # JPEG SOI marker
        return header == b'\xff\xd8'
    except:
        return False

def get_hostname(ip):
    def _is_ip_like(value):
        try:
            ipaddress.IPv4Address(value)
            return True
        except Exception:
            return False

    try:
        name = socket.gethostbyaddr(ip)[0]
        if name and name != ip and not _is_ip_like(name):
            return name
    except:
        pass

    # Windows NetBIOS fallback. Useful when DNS/PTR records are absent.
    try:
        result = subprocess.run(
            ['nbtstat', '-A', ip],
            capture_output=True,
            text=True,
            timeout=4
        )
        for raw_line in result.stdout.splitlines():
            line = raw_line.strip()
            if '<00>' in line and 'UNIQUE' in line:
                parts = line.split()
                if parts:
                    name = parts[0].strip()
                    if name and name != ip and not _is_ip_like(name):
                        return name
    except:
        pass

    # Last fallback: ping -a can sometimes resolve a hostname when PTR/NetBIOS is missing.
    try:
        result = subprocess.run(
            ['ping', '-a', '-n', '1', '-w', '300', ip],
            capture_output=True,
            text=True,
            timeout=4
        )
        for raw_line in result.stdout.splitlines():
            line = raw_line.strip()
            if line.lower().startswith('pinging '):
                # Examples:
                # Pinging DESKTOP-12345 [192.168.10.55] with 32 bytes of data:
                # Pinging 192.168.10.55 with 32 bytes of data:
                match = re.match(r'^Pinging\s+(.+?)\s+\[(.+?)\]', line, re.IGNORECASE)
                if match:
                    candidate = match.group(1).strip()
                    if candidate and candidate != ip and not _is_ip_like(candidate):
                        return candidate
    except:
        pass

    return 'Unknown'


def get_mac_address(ip):
    """Get MAC address from ARP cache if available."""
    try:
        result = subprocess.run(
            ['arp', '-a', ip],
            capture_output=True,
            text=True,
            timeout=4
        )
        # Example line: 192.168.10.55          aa-bb-cc-dd-ee-ff     dynamic
        pattern = re.compile(rf'^{re.escape(ip)}\s+([0-9a-fA-F\-:]{{11,17}})\s+', re.MULTILINE)
        match = pattern.search(result.stdout)
        if match:
            return match.group(1).lower().replace(':', '-')
    except:
        pass

    return 'Unknown'

def save_config(ip):
    try:
        ipaddress.IPv4Address(ip)
    except Exception:
        print(f"\n[ERROR] Invalid IPv4, save cancel: {ip}")
        return

    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.txt')
    with open(config_path, 'w') as f:
        f.write(ip)
    print(f"\n[OK] Config saved! IP {ip} config.txt mein likha gaya.")

print("\n" + "="*60)
print("  Network Scanner - Simple Version")
print("="*60)

local_ip = get_local_ip()
network = '.'.join(local_ip.split('.')[:3])

print(f"\nYour IP: {local_ip}")
print(f"Network: {network}.0/24")
print("\nScanning...")

devices = []
lock = threading.Lock()

def scan_ip(i):
    ip = f"{network}.{i}"
    hostname = 'Unknown'
    has_server = False

    # Ping ko sirf extra signal ke taur par use karo; scanner ko us par depend mat karo.
    alive = check_ping(ip)

    # Primary signal: actual stream protocol.
    has_server = check_server_stream(ip)

    # Agar stream mila ya ping mila, tab hostname resolve karne ki koshish karo.
    if has_server or alive:
        hostname = get_hostname(ip)
        mac = get_mac_address(ip)
        is_me = ip == local_ip
        with lock:
            devices.append((ip, hostname, mac, has_server, is_me))

        if has_server:
            status = "[STREAM]"
        elif alive:
            status = "Alive"
        else:
            status = "Open"

        me_tag = " (Your PC)" if is_me else ""
        print(f"  {ip:15} | {hostname:24} | {mac:17} | {status:12} {me_tag}")

# Parallel scan
threads = []
for i in range(1, 255):
    t = threading.Thread(target=scan_ip, args=(i,), daemon=True)
    threads.append(t)
    t.start()
    if len(threads) >= 50:
        for t in threads:
            t.join()
        threads = []

for t in threads:
    t.join()

print("\n" + "="*60)

# Find server devices
server_devices = [d for d in devices if d[3]]

if server_devices:
    print(f"\n[FOUND] Found {len(server_devices)} device(s) with server running:\n")
    for idx, (ip, hostname, mac, _, _) in enumerate(server_devices, 1):
        print(f"{idx}. {ip:15} - {hostname} - {mac}")
    
    if len(server_devices) == 1:
        ip = server_devices[0][0]
        save_config(ip)
    else:
        print(f"\nEnter number (1-{len(server_devices)}):")
        try:
            choice = int(input("> ")) - 1
            if 0 <= choice < len(server_devices):
                ip = server_devices[choice][0]
                save_config(ip)
            else:
                print("Invalid choice!")
        except:
            print("Invalid input!")
else:
    print("\n[ERROR] Koi server nahi mila!")
    print("Dekho: Target PC par server.exe chal raha hai?")

print("\n" + "="*60)
print("Ab client.exe chalao!")
print("="*60 + "\n")

print("\nScan complete.")
