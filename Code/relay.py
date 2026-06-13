import asyncio
import json
import os
import time

import websockets

producers = set()
consumers = set()
registry = {}


def now_text():
    return time.strftime('%Y-%m-%d %H:%M:%S')


def registry_key(websocket, meta, default_role):
    hostname = str(meta.get('hostname') or getattr(websocket, 'host', None) or 'Unknown').strip() or 'Unknown'
    device_id = str(meta.get('device_id') or f'{hostname}:{default_role}:{id(websocket)}').strip()
    return device_id


def register_device(websocket, req_path, meta, role):
    device_id = registry_key(websocket, meta, role)
    registry[device_id] = {
        'device_id': device_id,
        'hostname': str(meta.get('hostname') or 'Unknown'),
        'role': str(meta.get('role') or role),
        'path': req_path,
        'status': 'ACTIVE',
        'connected_at': meta.get('connected_at') or now_text(),
        'last_seen': now_text(),
    }
    websocket._registry_device_id = device_id
    return device_id


def touch_device(websocket):
    device_id = getattr(websocket, '_registry_device_id', None)
    if device_id and device_id in registry:
        registry[device_id]['last_seen'] = now_text()


def unregister_device(websocket):
    device_id = getattr(websocket, '_registry_device_id', None)
    if device_id:
        registry.pop(device_id, None)


def registry_snapshot():
    return sorted(registry.values(), key=lambda item: (item.get('role', ''), item.get('hostname', ''), item.get('device_id', '')))


def extract_request_path(websocket, fallback_path=None):
    # websockets versions expose request path differently. Try stable sources first.
    direct = getattr(websocket, 'path', None)
    if isinstance(direct, str) and direct:
        return direct

    request = getattr(websocket, 'request', None)
    req_path = getattr(request, 'path', None) if request else None
    if isinstance(req_path, str) and req_path:
        return req_path

    if isinstance(fallback_path, str) and fallback_path:
        return fallback_path

    return '/'


async def read_hello(websocket):
    meta = {}
    try:
        first_message = await asyncio.wait_for(websocket.recv(), timeout=3)
        if isinstance(first_message, str):
            try:
                parsed = json.loads(first_message)
                if isinstance(parsed, dict):
                    meta = parsed
            except Exception:
                meta = {'raw': first_message}
    except asyncio.TimeoutError:
        pass
    except websockets.exceptions.ConnectionClosed:
        raise
    except Exception:
        pass
    return meta

async def handler(websocket, path=None):
    req_path = extract_request_path(websocket, path)
        
    print(f"Connection attempt on path: {req_path}")

    if req_path.startswith('/registry'):
        try:
            await websocket.send(json.dumps({'devices': registry_snapshot()}))
        finally:
            await websocket.close()
        return

    if req_path.startswith("/producer"):
        producers.add(websocket)
        print(f"Producer connected. Total producers: {len(producers)}")
        try:
            meta = await read_hello(websocket)
            register_device(websocket, req_path, meta, 'producer')
            async for message in websocket:
                touch_device(websocket)
                # Forward binary frame to all consumers
                if consumers:
                    await asyncio.gather(
                        *[consumer.send(message) for consumer in consumers.copy()],
                        return_exceptions=True
                    )
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            producers.discard(websocket)
            unregister_device(websocket)
            print(f"Producer disconnected. Total producers: {len(producers)}")

    elif req_path.startswith("/consumer"):
        consumers.add(websocket)
        print(f"Consumer connected. Total consumers: {len(consumers)}")
        try:
            meta = await read_hello(websocket)
            register_device(websocket, req_path, meta, 'consumer')
            async for message in websocket:
                touch_device(websocket)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            consumers.discard(websocket)
            unregister_device(websocket)
            print(f"Consumer disconnected. Total consumers: {len(consumers)}")
    else:
        print(f"Default request path handler: {req_path}")
        try:
            await websocket.send("Relay Server is Running!")
        except Exception:
            pass
        finally:
            await websocket.close()

async def main():
    # Railway binds to port given by $PORT
    port = int(os.environ.get("PORT", 8080))
    print(f"Starting relay server on 0.0.0.0:{port} ...")
    async with websockets.serve(handler, "0.0.0.0", port):
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Server stopped.")
