from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from api.routes.agent_ws import send_validation_job

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post('/api/agent/test-job')
async def test_job(payload: dict) -> dict:
    job_id = payload.get('job_id') if isinstance(payload, dict) else None
    if not job_id or not isinstance(job_id, str):
        raise HTTPException(status_code=400, detail='job_id is required')
    try:
        ack = await send_validation_job(job_id)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except (TimeoutError, ValueError) as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {'status': 'sent', 'ack': ack}
