from fastapi import APIRouter, File, UploadFile
from app.services.identity_engine import IdentityEngine
from app.services.color_engine import ColorEngine

router = APIRouter()


@router.post("/analyze")
async def analyze_user(
    front_photo: UploadFile = File(...),
    side_photo: UploadFile = File(...),
    portrait_photo: UploadFile = File(...),
) -> dict:
    # Stub feature extraction; replace with real CV pipeline.
    user_features = {
        "vertical_line": 0.42,
        "compactness": 0.71,
        "width": 0.40,
        "bone_sharpness": 0.31,
        "bone_bluntness": 0.22,
        "softness": 0.74,
        "curve_presence": 0.69,
        "symmetry": 0.44,
        "facial_sharpness": 0.28,
        "facial_roundness": 0.67,
        "waist_definition": 0.73,
        "narrowness": 0.40,
        "relaxed_line": 0.20,
        "proportion_balance": 0.45,
        "moderation": 0.40,
        "line_contrast": 0.61,
        "small_scale": 0.66,
        "feature_juxtaposition": 0.58,
        "controlled_softness_or_sharpness": 0.33,
        "low_line_contrast": 0.39,
    }
    color_axes = {
        "undertone": "cool-neutral",
        "contrast": "medium-low",
        "depth": "medium",
        "chroma": "soft",
    }
    identity = IdentityEngine().analyze(user_features)
    color = ColorEngine().analyze(color_axes)
    style_vector = {"classic": 0.4, "romantic": 0.35, "natural": 0.25}
    return {"kibbe": identity, "color": color, "style_vector": style_vector}
