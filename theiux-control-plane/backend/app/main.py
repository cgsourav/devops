import time
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import current_user
from app.errors import ApiErrorEnvelope
from app.metrics import record_request
from app.models import User
from app.observability import metrics_export_payload, worker_status_payload
from app.quotas import limits_and_usage
from app.routers import v1 as v1_router
from app.schemas import LimitsOut, MetricsExportOut, WorkersStatusOut
from app.seed import seed_app_presets, seed_bootstrap_admin, seed_plans

UNSAFE_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})
EXEMPT_PATHS = frozenset({'/v1/auth/login', '/v1/auth/register'})

OPENAPI_TAGS = [
    {'name': 'auth', 'description': 'Authentication, refresh, logout, and cookie sessions.'},
    {'name': 'plans', 'description': 'Subscription plan catalog.'},
    {'name': 'benches', 'description': 'Logical benches, source apps, and bench-scoped deployments.'},
    {'name': 'apps', 'description': 'User-owned applications.'},
    {'name': 'deployments', 'description': 'Deployments, retries, and state transitions.'},
    {'name': 'sites', 'description': 'Sites and migrations.'},
    {'name': 'logs', 'description': 'Plain-text and structured deployment logs.'},
    {'name': 'audit', 'description': 'User-scoped audit trail.'},
    {'name': 'system', 'description': 'Health and in-process metrics.'},
    {'name': 'observability', 'description': 'Operations metrics, worker visibility, and quota usage.'},
    {'name': 'admin', 'description': 'Privileged platform operations (theiux init).'},
]

app = FastAPI(
    title='Theiux Control Plane API',
    version='1.0.0',
    openapi_tags=OPENAPI_TAGS,
    description='Public API is versioned under `/v1`. Errors use a consistent JSON envelope.',
)


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        description=app.description,
        routes=app.routes,
    )
    openapi_schema.setdefault('components', {}).setdefault('schemas', {})['ApiErrorEnvelope'] = ApiErrorEnvelope.model_json_schema()
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.middleware('http')
async def security_and_request_logging(request: Request, call_next):
    started = time.monotonic()
    record_request()

    if settings.auth_secure_cookies and request.method in UNSAFE_METHODS:
        path = request.url.path
        if path.startswith('/v1') and path not in EXEMPT_PATHS:
            auth = request.headers.get('authorization') or ''
            if not auth.lower().startswith('bearer '):
                if request.cookies.get('access_token') or request.cookies.get('refresh_token'):
                    header = request.headers.get('X-CSRF-Token') or request.headers.get('X-Csrf-Token')
                    cookie = request.cookies.get('csrf_token')
                    if not cookie or cookie != header:
                        return JSONResponse(
                            status_code=403,
                            content={
                                'code': 'csrf_failed',
                                'message': 'CSRF token missing or invalid',
                                'category': 'auth_error',
                                'details': None,
                            },
                        )

    response = await call_next(request)
    elapsed_ms = int((time.monotonic() - started) * 1000)
    print(f"[request] {request.method} {request.url.path} status={response.status_code} duration_ms={elapsed_ms}")
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict) and detail.get('code') and 'message' in detail:
        body = {
            'code': detail['code'],
            'message': detail['message'],
            'category': detail.get('category', ''),
            'details': detail.get('details'),
        }
    else:
        msg = detail if isinstance(detail, str) else str(detail)
        body = {
            'code': f'http_{exc.status_code}',
            'message': msg,
            'category': 'client_error' if exc.status_code < 500 else 'server_error',
            'details': None,
        }
    headers = dict(getattr(exc, 'headers', None) or {})
    return JSONResponse(status_code=exc.status_code, content=body, headers=headers)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            'code': 'validation_error',
            'message': 'Request validation failed',
            'category': 'client_error',
            'details': exc.errors(),
        },
    )


@app.on_event('startup')
def startup_event():
    seed_plans()
    seed_app_presets()
    seed_bootstrap_admin()


app.include_router(v1_router.router, prefix='/v1')


@app.get('/metrics', include_in_schema=False, response_model=MetricsExportOut, tags=['observability'])
def metrics_root(_: User = Depends(current_user)) -> MetricsExportOut:
    return MetricsExportOut(**metrics_export_payload())


@app.get('/workers/status', include_in_schema=False, response_model=WorkersStatusOut, tags=['observability'])
def workers_status_root(_: User = Depends(current_user)) -> WorkersStatusOut:
    return WorkersStatusOut(**worker_status_payload())


@app.get('/limits', include_in_schema=False, response_model=LimitsOut, tags=['observability'])
def limits_root(db: Session = Depends(get_db), user: User = Depends(current_user)) -> LimitsOut:
    return LimitsOut(**limits_and_usage(db, user.id))


@app.get('/health', include_in_schema=False)
def health_root(db: Session = Depends(get_db)):
    return v1_router.health_check(db)
