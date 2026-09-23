"""Prometheus HTTP metrics shared by every service (`/metrics` endpoint + middleware)."""

import time

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware

HTTP_REQUESTS = Counter("http_requests_total", "HTTP requests",
                        ["service", "method", "route", "status"])
HTTP_LATENCY = Histogram("http_request_duration_seconds", "HTTP request latency",
                         ["service", "method", "route"],
                         buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60))


class MetricsMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, service: str):
        super().__init__(app)
        self.service = service

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")  # template, e.g. /orders/{order_id}
        if path != "/metrics":
            HTTP_REQUESTS.labels(self.service, request.method, path, response.status_code).inc()
            HTTP_LATENCY.labels(self.service, request.method, path).observe(
                time.perf_counter() - start)
        return response


def instrument(app: FastAPI, service: str) -> None:
    app.add_middleware(MetricsMiddleware, service=service)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
