import os
import time
import uuid
from collections import defaultdict, deque

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware

# --------------------------------------------------------------------------
# Config (assigned values)
# --------------------------------------------------------------------------
EMAIL = os.environ.get("EMAIL", "24f2006261@ds.study.iitm.ac.in")
ASSIGNED_ORIGIN = os.environ.get("ASSIGNED_ORIGIN", "https://app-y9c3j9.example.com")
# Origin of the exam/grader page itself. Set this via env var EXAM_ORIGIN
# (check your browser's address bar for the grading page and copy the
# scheme+host, e.g. https://tds.s-anand.net) before deploying.
EXAM_ORIGIN = os.environ.get("EXAM_ORIGIN", "https://exam.sanand.workers.dev")

RATE_LIMIT_MAX = 9          # B requests
RATE_LIMIT_WINDOW = 10.0    # seconds

ALLOWED_ORIGINS = list({ASSIGNED_ORIGIN, EXAM_ORIGIN})

app = FastAPI()


# --------------------------------------------------------------------------
# Middleware 1: Request context (innermost — runs closest to the endpoint)
# --------------------------------------------------------------------------
class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


# --------------------------------------------------------------------------
# Middleware 3: Per-client rate limiting
# --------------------------------------------------------------------------
class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_requests: int, window_seconds: float):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.buckets: dict[str, deque] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):
        # Don't rate-limit CORS preflight requests.
        if request.method == "OPTIONS":
            return await call_next(request)

        client_id = request.headers.get("X-Client-Id", "anonymous")
        now = time.monotonic()
        bucket = self.buckets[client_id]

        while bucket and now - bucket[0] > self.window_seconds:
            bucket.popleft()

        if len(bucket) >= self.max_requests:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded", "client_id": client_id},
            )

        bucket.append(now)
        return await call_next(request)


# --------------------------------------------------------------------------
# Middleware stack assembly
# --------------------------------------------------------------------------
# add_middleware() prepends to Starlette's user_middleware list, and the
# stack is built by wrapping in that list order -> the LAST middleware
# added ends up OUTERMOST (processes the request first).
#
# Desired outer -> inner order:
#   CORS (outermost: handles preflight, tags responses)
#   -> RequestContext
#   -> RateLimit
#   -> endpoint
#
# So we add them innermost-first: RateLimit, then RequestContext, then CORS.
app.add_middleware(RateLimitMiddleware, max_requests=RATE_LIMIT_MAX, window_seconds=RATE_LIMIT_WINDOW)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)


@app.get("/ping")
async def ping(request: Request):
    return {"email": EMAIL, "request_id": request.state.request_id}


@app.get("/")
async def root():
    return {"status": "ok", "endpoint": "/ping"}
