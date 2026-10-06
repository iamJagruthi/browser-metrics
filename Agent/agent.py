import os
import asyncio
import websockets
import json

WS_URL = os.environ.get(
    "VIZ_MATCH_WS_URL",
    "wss://viz-match-171569128489.us-east4.run.app/ws/agent"
)


async def handle_job(websocket):
    try:
        job = await websocket.recv()
        try:
            msg = json.loads(job)
        except Exception:
            msg = job
        print(f"Received job: {msg}")
        if isinstance(msg, dict) and msg.get("type") == "validation_job":
            await websocket.send(json.dumps({"type": "job_ack", "job_id": msg.get("job_id")}))
            print(f"Sent job_ack for job_id={msg.get('job_id')}")
    except Exception as e:
        print(f"Job receive error: {e}")


async def main():
    uri = WS_URL
    print(f"Connecting to {uri}...")
    async with websockets.connect(uri) as websocket:
        try:
            ready = await websocket.recv()
            try:
                msg = json.loads(ready)
                print(f"Received: {msg}")
            except Exception:
                print(f"Received raw: {ready}")
            await websocket.send(json.dumps({"type": "ping"}))
            resp = await websocket.recv()
            try:
                print(f"Response: {json.loads(resp)}")
            except Exception:
                print(f"Response raw: {resp}")
            print("Handshake complete. Waiting for jobs...")
            await handle_job(websocket)
            print("Done.")
        except Exception as e:
            print(f"Error: {e}")
            return


if __name__ == "__main__":
    asyncio.run(main())
