# Agent handshake test

## Install
pip install -r requirements.txt

## Run (local)
python agent.py

## Run (custom URL)
VIZ_MATCH_WS_URL=ws://your-server/ws/agent python agent.py

## Notes
- Uses environment variable VIZ_MATCH_WS_URL; defaults to ws://localhost:8000/ws/agent
- Connects, waits for ready message, sends ping, verifies pong, exits cleanly
- No reconnection, auth, or job execution.
