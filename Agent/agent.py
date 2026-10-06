import os
import asyncio
import websockets
import json

WS_URL = os.environ.get("VIZ_MATCH_WS_URL", "wss://viz-match-171569128489.us-east4.run.app/ws/agent")


async def main():
    uri = WS_URL
    print(f"Connecting to {uri}...")
    async with websockets.connect(uri) as websocket:
        try:
            # wait for ready
            ready = await websocket.recv()
            try:
                msg = json.loads(ready)
                print(f"Received: {msg}")
            except Exception:
                print(f"Received raw: {ready}")
            # send ping
            await websocket.send(json.dumps({"type": "ping"}))
            resp = await websocket.recv()
            try:
                print(f"Response: {json.loads(resp)}")
            except Exception:
                print(f"Response raw: {resp}")
            print("Handshake complete. Exiting.")
        except Exception as e:
            print(f"Error: {e}")
            return


if __name__ == "__main__":
    asyncio.run(main())
