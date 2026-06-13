import os
import sys
import json
import numpy as np
import cv2
import websocket
import pyaudio
import queue
import threading


CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])), 'config_global.txt')
WINDOW_TITLE = 'Global Stream Monitor'

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

def start_viewer():
    relay_url = load_relay_url()
    
    # Check consumer path
    if not relay_url.endswith("/consumer"):
        relay_url = relay_url.rstrip("/")
        consumer_url = f"{relay_url}/consumer"
    else:
        consumer_url = relay_url
        
    print(f"Connecting to relay at {consumer_url} ...")
    
    try:
        ws = websocket.create_connection(consumer_url)
        try:
            ws.send(json.dumps({
                'role': 'consumer',
                'hostname': os.environ.get('COMPUTERNAME', 'Unknown'),
                'device_id': os.environ.get('COMPUTERNAME', 'Unknown'),
                'connected_at': time.strftime('%Y-%m-%d %H:%M:%S')
            }))
        except Exception:
            pass
        print("Connected! Display window active (Video + Voice).")
        print("Press 'Q' to quit, 'F' for fullscreen.")
    except Exception as e:
        print(f"Connection failed: {e}")
        sys.exit(1)

    audio_queue = queue.Queue()
    
    def audio_play_thread_fn():
        p = pyaudio.PyAudio()
        try:
            audio_stream = p.open(format=pyaudio.paInt16,
                                  channels=1,
                                  rate=16000,
                                  output=True,
                                  frames_per_buffer=1024)
        except Exception as e:
            print(f"Speakers playback failed: {e}")
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
    
    try:
        while True:
            # Receive image frame
            try:
                data = ws.recv()
            except Exception as e:
                print(f"Connection closed: {e}")
                break
                
            if not data or not isinstance(data, bytes):
                continue
                
            prefix = data[0:1]
            payload = data[1:]
            
            if prefix == b'a':
                audio_queue.put(payload)
            elif prefix == b'v':
                # Decode JPEG
                buf = np.frombuffer(payload, dtype=np.uint8)
                frame = cv2.imdecode(buf, cv2.IMREAD_COLOR)
                
                if frame is not None:
                    cv2.imshow(WINDOW_TITLE, frame)
                
            # Local window keys
            key = cv2.waitKeyEx(1)
            if key in (ord('q'), ord('Q')):
                break
            elif key in (ord('f'), ord('F')):
                fullscreen = not fullscreen
                if fullscreen:
                    cv2.setWindowProperty(WINDOW_TITLE, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
                else:
                    cv2.setWindowProperty(WINDOW_TITLE, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_NORMAL)
                    
            # Check if viewer closed
            if cv2.getWindowProperty(WINDOW_TITLE, cv2.WND_PROP_VISIBLE) < 1:
                break
                
    except KeyboardInterrupt:
        print("\nViewer stopped.")
    finally:
        audio_queue.put(None)
        try:
            ws.close()
        except:
            pass
        cv2.destroyAllWindows()

if __name__ == '__main__':
    start_viewer()
