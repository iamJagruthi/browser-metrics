"""
server.py

FastAPI backend that exposes the dashboard validator over HTTP.
Run from the project root with:

    uvicorn server:app --reload --port 8000

Frontend (Vite/React dev server on http://localhost:5173) posts two
dashboard URLs to POST /api/validate and receives metrics + comparison.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from automation.validator import DashboardValidator

app = FastAPI(title="Browser Metrics Validator API")

# Allow the Vite dev server to call this API from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ValidateRequest(BaseModel):
    source_url: str
    target_url: str


@app.get("/api/health")
async def health():
    """
    Simple health check so the frontend can verify the API is up.
    """
    return {"status": "ok"}


@app.post("/api/validate")
async def validate(request: ValidateRequest):
    """
    Runs the validator against the two supplied URLs and returns
    metrics for each dashboard plus the KPI comparison between them.
    """

    if not request.source_url.strip() or not request.target_url.strip():
        raise HTTPException(
            status_code=400,
            detail="Both source_url and target_url are required.",
        )

    try:
        validator = DashboardValidator()

        links = [
            {"name": "Dashboard A", "url": request.source_url.strip()},
            {"name": "Dashboard B", "url": request.target_url.strip()},
        ]
        print(links,"surya")
        result = await validator.run_links(links)

        return result

    except Exception as e:
        print(f"Error handling /api/validate request: {e}")
        raise HTTPException(status_code=500, detail=str(e))