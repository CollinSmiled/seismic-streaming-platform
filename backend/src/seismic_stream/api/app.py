"""HTTP reads over the committed earthquake projection."""

import math
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from psycopg_pool import ConnectionPool, PoolTimeout

from seismic_stream.api.repository import (
    ChangePage,
    EarthquakePage,
    EarthquakeRead,
    decode_cursor,
    get_earthquake,
    list_changes,
    list_earthquakes,
)
from seismic_stream.api.stream import change_stream


def require_pool(request: Request) -> ConnectionPool:
    pool: ConnectionPool | None = getattr(request.app.state, "pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="Database is not configured")
    return pool


def aware(value: datetime | None, name: str) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise HTTPException(status_code=422, detail=f"{name} must include a UTC offset")
    return value


def create_app(database_pool: ConnectionPool | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if database_pool is not None:
            app.state.pool = database_pool
            yield
            return
        database_url = os.getenv("DATABASE_URL")
        if not database_url:
            app.state.pool = None
            yield
            return
        with ConnectionPool(database_url, min_size=1, max_size=4) as pool:
            app.state.pool = pool
            yield

    api = FastAPI(title="Seismic Streaming API", lifespan=lifespan)

    @api.exception_handler(RequestValidationError)
    def validation_error(
        _request: Request, _error: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": "Invalid request parameters",
                }
            },
        )

    @api.exception_handler(HTTPException)
    def http_error(_request: Request, error: HTTPException) -> JSONResponse:
        codes = {404: "not_found", 422: "invalid_request", 503: "unavailable"}
        return JSONResponse(
            status_code=error.status_code,
            content={
                "error": {
                    "code": codes.get(error.status_code, "request_failed"),
                    "message": str(error.detail),
                }
            },
        )

    @api.get("/health")
    def health() -> dict[str, str]:
        """Report that the API process can respond to requests."""
        return {"status": "ok"}

    @api.get("/api/v1/earthquakes", response_model=EarthquakePage)
    def historical_earthquakes(
        pool: Annotated[ConnectionPool, Depends(require_pool)],
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
        cursor: Annotated[str | None, Query(max_length=512)] = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        min_lon: Annotated[float | None, Query(ge=-180, le=180)] = None,
        min_lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
        max_lon: Annotated[float | None, Query(ge=-180, le=180)] = None,
        max_lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    ) -> EarthquakePage:
        start_time = aware(start_time, "start_time")
        end_time = aware(end_time, "end_time")
        if start_time is not None and end_time is not None and start_time > end_time:
            raise HTTPException(
                status_code=422, detail="start_time must not exceed end_time"
            )
        supplied_bounds = (min_lon, min_lat, max_lon, max_lat)
        if any(
            value is not None and not math.isfinite(value) for value in supplied_bounds
        ):
            raise HTTPException(status_code=422, detail="Map bounds must be finite")
        if any(value is not None for value in supplied_bounds) and not all(
            value is not None for value in supplied_bounds
        ):
            raise HTTPException(
                status_code=422, detail="All four map bounds are required"
            )
        bounds: tuple[float, float, float, float] | None = None
        if all(value is not None for value in supplied_bounds):
            assert min_lon is not None and min_lat is not None
            assert max_lon is not None and max_lat is not None
            if min_lat > max_lat:
                raise HTTPException(
                    status_code=422, detail="min_lat must not exceed max_lat"
                )
            bounds = (min_lon, min_lat, max_lon, max_lat)
        try:
            decoded_cursor = decode_cursor(cursor) if cursor is not None else None
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        try:
            return list_earthquakes(
                pool,
                limit=limit,
                cursor=decoded_cursor,
                start_time=start_time,
                end_time=end_time,
                bounds=bounds,
            )
        except (psycopg.Error, PoolTimeout) as error:
            raise HTTPException(
                status_code=503, detail="Database is unavailable"
            ) from error

    @api.get("/api/v1/earthquakes/changes", response_model=ChangePage)
    def earthquake_changes(
        pool: Annotated[ConnectionPool, Depends(require_pool)],
        after: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ) -> ChangePage:
        try:
            return list_changes(pool, after=after, limit=limit)
        except (psycopg.Error, PoolTimeout) as error:
            raise HTTPException(
                status_code=503, detail="Database is unavailable"
            ) from error

    @api.get("/api/v1/earthquakes/stream")
    async def earthquake_stream(
        request: Request,
        pool: Annotated[ConnectionPool, Depends(require_pool)],
        after: Annotated[int, Query(ge=0)] = 0,
    ) -> StreamingResponse:
        return StreamingResponse(
            change_stream(request, pool, after=after),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @api.get("/api/v1/earthquakes/{event_id}", response_model=EarthquakeRead)
    def earthquake_detail(
        event_id: Annotated[str, Path(min_length=1, max_length=128)],
        pool: Annotated[ConnectionPool, Depends(require_pool)],
    ) -> EarthquakeRead:
        if event_id.strip() != event_id or any(char.isspace() for char in event_id):
            raise HTTPException(status_code=422, detail="Invalid earthquake ID")
        try:
            event = get_earthquake(pool, event_id)
        except (psycopg.Error, PoolTimeout) as error:
            raise HTTPException(
                status_code=503, detail="Database is unavailable"
            ) from error
        if event is None:
            raise HTTPException(status_code=404, detail="Earthquake not found")
        return event

    return api


app = create_app()
