"""Wardrobe item attribute schema v2.

Each attribute is a structured field that carries the value alongside
its provenance (source) and confidence, and whether the user can edit it.

``source`` vocabulary:
  - ``cv``     — detected by computer vision
  - ``manual`` — set by the user via confirm/edit endpoint
  - ``import`` — imported from an external data source
  - ``default`` — fallback when no detection succeeded
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AttributeField(BaseModel):
    """A single attribute value with its provenance metadata."""

    model_config = ConfigDict(extra="forbid")

    value: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source: Literal["cv", "manual", "import", "default"] = "default"
    editable: bool = True

    @classmethod
    def from_cv(cls, value: str | None, confidence: float = 0.7) -> "AttributeField":
        return cls(value=value, confidence=confidence, source="cv", editable=True)

    @classmethod
    def from_manual(cls, value: str | None) -> "AttributeField":
        return cls(value=value, confidence=1.0, source="manual", editable=True)

    @classmethod
    def default(cls, value: str | None = None) -> "AttributeField":
        return cls(value=value, confidence=0.0, source="default", editable=True)


class WardrobeAttributesV2(BaseModel):
    """Structured attribute set for a wardrobe item.

    All fields are :class:`AttributeField` so each carries confidence,
    source, and editability alongside the value. Fields that do not
    apply to a given category (e.g. ``neckline`` on trousers) are
    represented as ``None``-valued AttributeField with source "default".
    """

    model_config = ConfigDict(extra="forbid")

    category: AttributeField = Field(default_factory=AttributeField.default)
    subcategory: AttributeField = Field(default_factory=AttributeField.default)
    primary_color: AttributeField = Field(default_factory=AttributeField.default)
    pattern: AttributeField = Field(default_factory=AttributeField.default)
    material: AttributeField = Field(default_factory=AttributeField.default)
    fit: AttributeField = Field(default_factory=AttributeField.default)
    silhouette: AttributeField = Field(default_factory=AttributeField.default)
    neckline: AttributeField = Field(default_factory=AttributeField.default)
    sleeve_length: AttributeField = Field(default_factory=AttributeField.default)
    occasion: AttributeField = Field(default_factory=AttributeField.default)
    seasonality: AttributeField = Field(default_factory=AttributeField.default)
    layer_role: AttributeField = Field(default_factory=AttributeField.default)

    def to_legacy_dict(self) -> dict:
        """Return a flat {key: value} dict for backward-compat code."""
        return {k: (v.value if v else None) for k, v in self.model_dump().items()}

    def apply_manual_update(self, updates: dict[str, str]) -> "WardrobeAttributesV2":
        """Return a new instance with the supplied fields set to manual source."""
        data = self.model_dump()
        for field_name, new_value in updates.items():
            if field_name in data:
                data[field_name] = AttributeField.from_manual(new_value).model_dump()
        return WardrobeAttributesV2.model_validate(data)


__all__ = ["AttributeField", "WardrobeAttributesV2"]
