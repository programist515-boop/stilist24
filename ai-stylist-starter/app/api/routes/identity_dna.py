"""Identity DNA route — карточка «Кто ты стилистически».

Возвращает ассоциативный слой для подтипа персоны:
``associations``, ``motto``, ``philosophy``, ``key_principles``,
``celebrity_examples``. Контент наполнен для всех 13 классических
подтипов Kibbe (см. ``identity_subtype_profiles.yaml``).

Подтип берётся из активного ``StyleProfile`` персоны через
``style_profile_resolver`` — то есть уважает выбор пользователя между
алгоритмическим профилем и preference-quiz-профилем.
"""
from __future__ import annotations

import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_persona_id, get_db
from app.services.style_profile_resolver import get_active_profile_by_persona_id

router = APIRouter()


# ---------------------------------------------------------- schemas


class CelebrityOut(BaseModel):
    name: str
    era: str | None = None


class IdentityDNAOut(BaseModel):
    subtype: str | None
    display_name_ru: str | None
    display_name_en: str | None
    family: str | None
    associations: list[str]
    motto: str
    philosophy: str
    key_principles: list[str]
    celebrity_examples: list[CelebrityOut]


# ---------------------------------------------------------- loader


_YAML_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "config"
    / "rules"
    / "identity_subtype_profiles.yaml"
)


@lru_cache(maxsize=1)
def _load_all_profiles() -> dict[str, dict[str, Any]]:
    with _YAML_PATH.open("r", encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    return doc.get("identity_subtype_profiles", {}) or {}


def _empty() -> IdentityDNAOut:
    return IdentityDNAOut(
        subtype=None,
        display_name_ru=None,
        display_name_en=None,
        family=None,
        associations=[],
        motto="",
        philosophy="",
        key_principles=[],
        celebrity_examples=[],
    )


# ---------------------------------------------------------- route


@router.get("", response_model=IdentityDNAOut)
def get_identity_dna(
    db: Session = Depends(get_db),
    persona_id: uuid.UUID = Depends(get_current_persona_id),
) -> IdentityDNAOut:
    """Return identity DNA for the active persona's Kibbe subtype.

    If the user hasn't run ``/user/analyze`` yet (no subtype on file),
    returns an empty payload — the frontend can hide the card.
    """
    resolved = get_active_profile_by_persona_id(persona_id, db)
    subtype = resolved.kibbe_type
    if not subtype:
        return _empty()

    data = _load_all_profiles().get(subtype)
    if not data:
        return _empty()

    celebs_raw = data.get("celebrity_examples") or []
    celebs: list[CelebrityOut] = []
    for c in celebs_raw:
        if isinstance(c, dict) and c.get("name"):
            celebs.append(CelebrityOut(name=c["name"], era=c.get("era")))

    philosophy_raw = (data.get("philosophy") or "").strip()

    return IdentityDNAOut(
        subtype=subtype,
        display_name_ru=data.get("display_name_ru"),
        display_name_en=data.get("display_name_en"),
        family=data.get("family"),
        associations=list(data.get("associations") or []),
        motto=(data.get("motto") or "").strip(),
        philosophy=philosophy_raw,
        key_principles=list(data.get("key_principles") or []),
        celebrity_examples=celebs,
    )
