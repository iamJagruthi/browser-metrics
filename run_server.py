"""
run_server.py

Launches the FastAPI backend (server.py) directly, without going
through the `uvicorn` CLI.

Why this exists:
-----------------
Playwright launches the Edge browser as a subprocess. On Windows,
asyncio can only spawn subprocesses under the ProactorEventLoop —
the SelectorEventLoop raises NotImplementedError for any subprocess
call.

The old fix was `asyncio.set_event_loop_policy(...)`, but that API
is deprecated as of Python 3.14 and will be removed in 3.16. Its
replacement is passing `loop_factory` directly to `asyncio.run()`
(available since Python 3.12). The `uvicorn server:app` CLI calls
`asyncio.run()` internally and gives us no way to pass `loop_factory`
to it — so instead we call `uvicorn.Server.serve()` ourselves, inside
our own `asyncio.run(..., loop_factory=...)`.

Usage
-----
    python run_server.py

Note: this does not include uvicorn's --reload auto-restart-on-change
behaviour (that machinery lives outside Server.serve() and isn't
compatible with a custom loop_factory). During development, just
re-run this script after editing backend code. If you want file-watch
auto-restart back, run `pip install watchfiles --break-system-packages`
and wrap this script's call in a `watchfiles.run_process(...)` call.
"""

import asyncio
import sys

import uvicorn


async def run():
    config = uvicorn.Config(
        "server:app",
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    try:
        if sys.platform == "win32":
            asyncio.run(run(), loop_factory=asyncio.ProactorEventLoop)
        else:
            asyncio.run(run())

    except Exception as e:
        print(f"Failed to start server: {e}")