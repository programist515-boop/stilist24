from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import (
    ApiError,
    api_error_handler,
    http_error_handler,
    validation_error_handler,
)
from app.api.routes import (
    auth,
    color,
    events,
    feedback,
    gap_analysis,
    insights,
    outfits,
    recommendations,
    shopping,
    today,
    tryon,
    user_analysis,
    wardrobe,
)
from app.core.config import settings

app = FastAPI(title="AI Stylist API", version="0.1.0")

# CORS: the browser client (Next.js dev on :3000, prod build behind its own
# domain) talks to the API cross-origin and sends a custom ``X-User-Id``
# header, which forces a preflight on every non-simple request. The allowed
# origin list comes from settings so it can be widened via env in prod.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Unified error envelope: every HTTPException, ApiError, and Pydantic
# validation failure is rewritten into the shape documented in
# ``app/api/errors.py``. Routes do not need to be edited to benefit —
# the handlers wrap everything at the edge.
app.add_exception_handler(ApiError, api_error_handler)
app.add_exception_handler(HTTPException, http_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(user_analysis.router, prefix="/user", tags=["user"])
app.include_router(color.router, prefix="/color", tags=["color"])
app.include_router(gap_analysis.router, prefix="/wardrobe", tags=["wardrobe"])
app.include_router(wardrobe.router, prefix="/wardrobe", tags=["wardrobe"])
app.include_router(outfits.router, prefix="/outfits", tags=["outfits"])
app.include_router(tryon.router, prefix="/tryon", tags=["tryon"])
app.include_router(feedback.router, prefix="/feedback", tags=["feedback"])
app.include_router(events.router, prefix="/events", tags=["events"])
app.include_router(today.router, prefix="/today", tags=["today"])
app.include_router(insights.router, prefix="/insights", tags=["insights"])
app.include_router(
    recommendations.router, prefix="/recommendations", tags=["recommendations"]
)
app.include_router(shopping.router, prefix="/shopping", tags=["shopping"])


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
