from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

router = APIRouter()

_connected_websocket: Optional[WebSocket] = None
_connection_lock = asyncio.Lock()
_job_ack_event: Optional[asyncio.Event] = None
_last_ack: Optional[Dict[str, Any]] = None


@router.websocket('/ws/agent')
async def agent_websocket(websocket: WebSocket) -> None:
    global _connected_websocket, _job_ack_event, _last_ack
    await websocket.accept()
    async with _connection_lock:
        _connected_websocket = websocket
        _job_ack_event = asyncio.Event()
        _last_ack = None
    logger.info('agent websocket connected')
    try:
        await websocket.send_json({'type': 'ready', 'message': 'agent websocket ready'})
        while True:
            data = await websocket.receive_json()
            msg_type = data.get('type') if isinstance(data, dict) else None
            if msg_type == 'ping':
                await websocket.send_json({'type': 'pong'})
            elif msg_type == 'job_ack':
                async with _connection_lock:
                    _last_ack = data
                    if _job_ack_event:
                        _job_ack_event.set()
            else:
                await websocket.send_json({'type': 'ack', 'received': msg_type})
    except WebSocketDisconnect:
        logger.info('agent websocket disconnected')
    except Exception as e:
        logger.warning(f'agent websocket error: {e}')
    finally:
        async with _connection_lock:
            if _connected_websocket is websocket:
                _connected_websocket = None
            if _job_ack_event:
                _job_ack_event.set()
                _job_ack_event = None
            _last_ack = None
        logger.info('agent websocket connection cleared')


async def send_validation_job(job_id: str, timeout: float = 5.0) -> Dict[str, Any]:
    global _connected_websocket, _job_ack_event, _last_ack
    async with _connection_lock:
        websocket = _connected_websocket
        event = asyncio.Event()
        _job_ack_event = event
        _last_ack = None
    if websocket is None:
        raise RuntimeError('no agent connected')
    await websocket.send_json({'type': 'validation_job', 'job_id': job_id})
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        raise TimeoutError('timeout waiting for job_ack')
    async with _connection_lock:
        resp = _last_ack
    if not isinstance(resp, dict):
        raise ValueError('invalid ack response')
    if resp.get('type') != 'job_ack':
        raise ValueError(f"unexpected ack type: {resp.get('type')}")
    if resp.get('job_id') != job_id:
        raise ValueError(f"job_id mismatch in ack: {resp.get('job_id')}")
    return resp
