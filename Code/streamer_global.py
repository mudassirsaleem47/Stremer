import os
import sys
import time
import json
import mss
import numpy as np
import cv2
import websocket
import pyaudio
import threading


CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'config_global.txt')

# Streaming settings
FPS = 15
QUALITY = 80
MONITOR = 1

def load_relay_url():
    """config_global.txt se relay URL padho ya user se lo."""
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            url = f.read().strip()
            if url:
                print(f"Relay URL loaded: {url}")
                return url
                
    url = input("Enter Relay WS URL (e.g. ws://localhost:8080 or wss://app.up.railway.app): ").strip()
    if not url:
        url = "ws://localhost:8080"
        
    with open(CONFIG_FILE, 'w') as f:
        f.write(url)
    return url

def start_stream():
    relay_url = load_relay_url()
    
    # Check producer path
    if not relay_url.endswith("/producer"):
        relay_url = relay_url.rstrip("/")
        producer_url = f"{relay_url}/producer"
    else:
        producer_url = relay_url
        
    print(f"Connecting to relay at {producer_url} ...")
    
    try:
        ws = websocket.create_connection(producer_url)
        try:
            ws.send(json.dumps({
                'role': 'producer',
                'hostname': os.environ.get('COMPUTERNAME', 'Unknown'),
                'device_id': os.environ.get('COMPUTERNAME', 'Unknown'),
                'connected_at': time.strftime('%Y-%m-%d %H:%M:%S')
            }))
        except Exception:
            pass
        print("Connected! Streaming active (Video + Voice). Press Ctrl+C to stop.")
    except Exception as e:
        print(f"Connection failed: {e}")
        sys.exit(1)

    ws_lock = threading.Lock()
    
    def send_safe(prefix, payload):
        try:
            with ws_lock:
                ws.send_binary(prefix + payload)
        except Exception as e:
            raise e

    def audio_thread_fn():
        p = pyaudio.PyAudio()
        try:
            audio_stream = p.open(format=pyaudio.paInt16,
                                  channels=1,
                                  rate=16000,
                                  input=True,
                                  frames_per_buffer=1024)
        except Exception as e:
            print(f"Microphone capture not available: {e}")
            p.terminate()
            return
            
        print("Microphone voice capture started.")
        try:
            while True:
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
            p.terminate()

    audio_thread = threading.Thread(target=audio_thread_fn, daemon=True)
    audio_thread.start()

    frame_time = 1.0 / FPS
    
    try:
        with mss.mss() as sct:
            monitor = sct.monitors[MONITOR]
            
            while True:
                t_start = time.time()
                
                # Grab screen frame
                img = np.array(sct.grab(monitor))
                img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                
                # Encode JPEG
                _, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, QUALITY])
                data = buf.tobytes()
                
                # Send packet
                try:
                    send_safe(b'v', data)
                except Exception as e:
                    print(f"Socket disconnected: {e}")
                    break
                
                # Control rate
                elapsed = time.time() - t_start
                sleep_time = frame_time - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)
                    
    except KeyboardInterrupt:
        print("\nStreaming stopped.")
    finally:
        try:
            ws.close()
        except:
            pass

if __name__ == '__main__':
    start_stream()
