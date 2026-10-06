import os
import sys
import asyncio
import websockets
import json

# Make Backend importable when running as separate process
try:
    _AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _AGENT_DIR = os.getcwd()
_BACKEND_DIR = os.path.abspath(os.path.join(_AGENT_DIR, "..", "Backend"))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)
# Also ensure parent directories on path for IDE/static analysis
_PARENT = os.path.abspath(os.path.join(_AGENT_DIR, ".."))
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

DashboardValidator = None
_IMPORT_ERROR = None
# Try import as 'orchestration.validator' (works when Backend is in sys.path)
try:
    from orchestration.validator import DashboardValidator  # type: ignore
except Exception as _e:
    _IMPORT_ERROR = _e
    # Try relative to parent (when running from repo root)
    try:
        import orchestration.validator as _m1
        DashboardValidator = _m1.DashboardValidator  # type: ignore
        _IMPORT_ERROR = None
    except Exception:
        # Try with Backend prefix
        try:
            import Backend.orchestration.validator as _m2
            DashboardValidator = _m2.DashboardValidator  # type: ignore
            _IMPORT_ERROR = None
        except Exception as _e2:
            _IMPORT_ERROR = _e2
            DashboardValidator = None

WS_URL = os.environ.get(
    "VIZ_MATCH_WS_URL",
    "wss://viz-match-171569128489.us-east4.run.app/ws/agent"
)


async def _handle_validation_job(websocket, msg):
    if not isinstance(msg, dict):
        return

    job_id = msg.get("job_id")
    links = msg.get("links")

    # Send job_ack immediately after receiving the job
    try:
        await websocket.send(json.dumps({"type": "job_ack", "job_id": job_id}))
        print(f"Sent job_ack for job_id={job_id}")
    except Exception as e:
        print(f"Failed to send job_ack for job_id={job_id}: {e}")
        return

    # Validate links
    if not isinstance(links, list) or len(links) < 2:
        print(f"Invalid/missing links for job_id={job_id}; not launching Edge")
        return

    valid = True
    for item in links:
        if not isinstance(item, dict):
            valid = False
            break
        if not item.get("url"):
            valid = False
            break
    if not valid:
        print(f"Invalid links structure for job_id={job_id}; not launching Edge")
        return

    if DashboardValidator is None:
        print(
            f"DashboardValidator unavailable (import error: {_IMPORT_ERROR}); "
            f"cannot run validation for job_id={job_id}"
        )
        return

    try:
        print(f"Invoking DashboardValidator.run_links for job_id={job_id} (links={len(links)})")
        validator = DashboardValidator()
        result = await validator.run_links(links)
        try:
            status = None
            if isinstance(result, dict) and isinstance(result.get("comparison"), dict):
                status = result.get("comparison", {}).get("status")
            print(f"Validation completed for job_id={job_id}: status={status}")
        except Exception:
            print(f"Validation completed for job_id={job_id}")
    except Exception as e:
        print(f"Validation error for job_id={job_id}: {e}")


async def main():
    uri = WS_URL
    print(f"Connecting to {uri}...")
    async with websockets.connect(uri) as websocket:
        try:
            # Handshake - ready
            ready = await websocket.recv()
            try:
                msg = json.loads(ready)
                print(f"Received: {msg}")
            except Exception:
                print(f"Received raw: {ready}")

            # ping/pong
            await websocket.send(json.dumps({"type": "ping"}))
            resp = await websocket.recv()
            try:
                print(f"Response: {json.loads(resp)}")
            except Exception:
                print(f"Response raw: {resp}")
            print("Handshake complete. Waiting for jobs...")

            # Keep alive, listen for jobs sequentially
            while True:
                try:
                    data = await websocket.recv()
                except websockets.ConnectionClosed:
                    print("WebSocket connection closed")
                    break
                except Exception as e:
                    print(f"Receive error: {e}")
                    break

                try:
                    msg = json.loads(data)
                except Exception:
                    msg = data

                if isinstance(msg, dict):
                    mtype = msg.get("type")
                else:
                    mtype = None

                if mtype == "validation_job":
                    await _handle_validation_job(websocket, msg)
                elif mtype == "ping":
                    await websocket.send(json.dumps({"type": "pong"}))
                else:
                    print(f"Received message: {msg}")
        except Exception as e:
            print(f"Error: {e}")
            return


if __name__ == "__main__":
    asyncio.run(main())
