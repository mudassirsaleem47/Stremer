import asyncio
import os
import websockets

producers = set()
consumers = set()

async def handler(websocket, path=None):
    # Read path from request URL or fallback
    req_path = getattr(websocket, "path", path)
    if req_path is None:
        req_path = "/"
        
    print(f"Connection attempt on path: {req_path}")

    if req_path.startswith("/producer"):
        producers.add(websocket)
        print(f"Producer connected. Total producers: {len(producers)}")
        try:
            async for message in websocket:
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
            print(f"Producer disconnected. Total producers: {len(producers)}")

    elif req_path.startswith("/consumer"):
        consumers.add(websocket)
        print(f"Consumer connected. Total consumers: {len(consumers)}")
        try:
            async for message in websocket:
                pass
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            consumers.discard(websocket)
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
