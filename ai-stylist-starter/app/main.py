from fastapi import FastAPI
from app.api.routes import auth, user_analysis, color, wardrobe, outfits, tryon, feedback, today, insights

app = FastAPI(title="AI Stylist API", version="0.1.0")

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(user_analysis.router, prefix="/user", tags=["user"])
app.include_router(color.router, prefix="/color", tags=["color"])
app.include_router(wardrobe.router, prefix="/wardrobe", tags=["wardrobe"])
app.include_router(outfits.router, prefix="/outfits", tags=["outfits"])
app.include_router(tryon.router, prefix="/tryon", tags=["tryon"])
app.include_router(feedback.router, prefix="/feedback", tags=["feedback"])
app.include_router(today.router, prefix="/today", tags=["today"])
app.include_router(insights.router, prefix="/insights", tags=["insights"])

@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}
