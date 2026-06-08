"""
FloodOps v3 — Entry point.

Starts the FastAPI server with uvicorn.
Run with: python -m floodops.main
Or: uvicorn floodops.main:app --reload
"""

from floodops.api.app import create_app
from floodops.config import API_HOST, API_PORT

app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "floodops.main:app",
        host=API_HOST,
        port=API_PORT,
        reload=True,
        log_level="info",
    )
