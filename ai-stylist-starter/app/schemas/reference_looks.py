"""Pydantic-схемы для роута ``/reference-looks`` (Фаза 7).

Контракт: каждый лук из ``config/rules/reference_looks/<subtype>.yaml``
отдаётся вместе с собранным матчем из гардероба пользователя. UI рисует
«скелет» лука по ``slot_order`` и подсвечивает закрытые/пустые слоты.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class MatchedItemOut(BaseModel):
    slot: str
    item_id: str
    match_quality: float = Field(ge=0.0, le=1.0)
    match_reasons: list[str] = Field(default_factory=list)


class MissingSlotOut(BaseModel):
    slot: str
    requires: dict = Field(default_factory=dict)
    shopping_hint: str


class ReferenceLookOut(BaseModel):
    look_id: str
    title: str
    occasion: str | None = None
    image_url: str | None = None
    description: str | None = None
    matched_items: list[MatchedItemOut] = Field(default_factory=list)
    missing_slots: list[MissingSlotOut] = Field(default_factory=list)
    completeness: float = Field(ge=0.0, le=1.0)
    slot_order: list[str] = Field(default_factory=list)


class ReferenceLooksResponse(BaseModel):
    subtype: str | None = Field(
        None,
        description=(
            "Активный подтип пользователя (из style_profile_resolver). "
            "None, если профиль ещё не определён — тогда looks=[]."
        ),
    )
    looks: list[ReferenceLookOut] = Field(default_factory=list)
