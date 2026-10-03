from fastapi import FastAPI

app = FastAPI(title="Seismic Streaming API")


@app.get("/health")
def health() -> dict[str, str]:
    """Report that the API process can respond to requests."""
    return {"status": "ok"}
