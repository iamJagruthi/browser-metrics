"""
server.py

FastAPI entrypoint for uvicorn and run_server.py.

Run from the project root:

    uvicorn server:app --reload --port 8000

Jagruthi — routes live under api/routes/; this module only exposes the app instance.
"""

from api.app import create_app

app = create_app()
