"""Shopping evaluator route — POST /shopping/evaluate.

Accepts either an image upload (runs GarmentRecognizer) or plain JSON
attributes, evaluates the candidate against the user's wardrobe, and
returns a buy / maybe / skip decision with full explanation.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Body, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_persona_id, get_current_user_id, get_db
from app.models.shopping_candidate import ShoppingCandidate
from app.repositories.wardrobe_repository import WardrobeRepository
from app.schemas.shopping import PurchaseEvalOut, ShoppingCandidateIn
from app.services.shopping.candidate_parser import parse_from_attrs, parse_from_image
from app.services.shopping.purchase_evaluator import PurchaseEvaluator
from app.services.user_context import build_user_context_from_db

router = APIRouter()


_build_user_context = build_user_context_from_db


def _wardrobe_as_dicts(db: Session, persona_id: uuid.UUID) -> list[dict]:
    repo = WardrobeRepository(db)
    return [
        {
            **(i.attributes_json or {}),
            "id": str(i.id),
            "category": i.category,
            "attributes": i.attributes_json or {},
            "cost": i.cost,
            "wear_count": i.wear_count or 0,
        }
        for i in repo.list_by_persona(persona_id)
    ]


@router.post("/evaluate", response_model=PurchaseEvalOut)
async def evaluate_purchase(
    image: UploadFile | None = File(default=None),
    category: str | None = Form(default=None),
    price: float | None = Form(default=None),
    retailer: str | None = Form(default=None),
    db: Session = Depends(get_db),
    user_id: uuid.UUID = Depends(get_current_user_id),
    persona_id: uuid.UUID = Depends(get_current_persona_id),
) -> dict:
    """Evaluate a prospective purchase.

    Accepts an optional image upload for attribute inference.  Any form fields
    (``category``, ``price``, ``retailer``) are passed through as hints.
    If no image is provided, a minimal candidate is built from the form fields.

    Returns ``decision`` (buy/maybe/skip), ``confidence``, ``reasons``,
    ``warnings``, ``pairs_with_count``, and per-scorer ``subscores``.
    """
    wardrobe = _wardrobe_as_dicts(db, persona_id)
    user_context = _build_user_context(db, user_id)

    if image is not None:
        data = await image.read()
        candidate = parse_from_image(
            data,
            hint_category=category,
            price=price,
        )
        data_source = "image"
    else:
        attrs: dict = {}
        if category:
            attrs["category"] = category
        candidate = parse_from_attrs(attrs, price=price)
        data_source = "manual" if (category or price) else "minimal"

    if retailer:
        candidate["retailer"] = retailer

    result = PurchaseEvaluator(wardrobe, user_context).evaluate(candidate)

    from app.services.explainer import explain_shopping
    explanation = explain_shopping(result).to_dict()

    # Persist the candidate so the evaluation can be referenced later
    _persist_candidate(db, user_id, candidate)

    return {
        "decision": result["decision"],
        "summary": explanation["summary"],
        "reasons": explanation["reasons"],
        "warnings": explanation["warnings"],
        "confidence": result["confidence"],
    }


def _persist_candidate(
    db: Session,
    user_id: uuid.UUID,
    candidate: dict,
) -> None:
    """Save the shopping candidate to the DB (fire-and-forget; errors are swallowed)."""
    try:
        import uuid as _uuid
        row = ShoppingCandidate(
            id=_uuid.UUID(str(candidate["id"])),
            user_id=user_id,
            attributes_json=candidate.get("attributes") or {},
            price=candidate.get("cost"),
            retailer=candidate.get("retailer"),
            image_key=candidate.get("image_key"),
            image_url=candidate.get("image_url"),
            inferred_confidence=candidate.get("_inferred_confidence"),
        )
        db.add(row)
        db.commit()
    except Exception:
        db.rollback()
