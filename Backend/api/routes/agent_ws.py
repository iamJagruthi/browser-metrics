from __future__ import annotations

import json
import logging
from typing import Any, Dict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/agent")
async def agent_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        # Send ready message
        await websocket.send_json({"type": "ready", "message": "agent websocket ready"})
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type") if isinstance(data, dict) else None
            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
            else:
                await websocket.send_json({"type": "ack", "received": msg_type})
    except WebSocketDisconnect:
        logger.info("agent websocket disconnected")
    except Exception as e:
        logger.warning(f"agent websocket error: {e}")
