"""Beta telemetry — funnel events and free-form feedback.

Kept separate from ``app/schemas/feedback.py`` because the existing
``POST /feedback`` endpoint is reserved for typed reactions (item/outfit
like/dislike/worn) that feed the personalization profile. Those reactions
have a fixed enum and a side-effect on ``personalization_profiles``.

The closed-beta story needs two extra shapes:

* Funnel tracking (`page_viewed`, `analysis_completed`, `wardrobe_item_uploaded`,
  …) that should land in ``user_events`` without touching personalization.
* Free-form "what zapped / what annoyed" feedback with an optional contact
  string, so we can follow up with beta testers individually.

Both flow through the new ``app/api/routes/events.py`` routes.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


# Lowercase letters + digits + underscore + dot. Starts with a letter.
# Permissive enough to cover anything we'd emit from the client
# (``page_viewed``, ``funnel.analyze_started``, ``outfits_generated``) but
# locked down enough that nobody sneaks HTML into ``user_events.event_type``.
_EVENT_TYPE_RE = r"^[a-z][a-z0-9_\.]{0,62}[a-z0-9]$"


class TrackEventIn(BaseModel):
    """Funnel event: a thin record of "user did X" with a free-form payload."""

    event_type: str = Field(..., min_length=2, max_length=64, pattern=_EVENT_TYPE_RE)
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("event_type", mode="before")
    @classmethod
    def _strip(cls, v: Any) -> Any:
        return v.strip() if isinstance(v, str) else v


class BetaFeedbackIn(BaseModel):
    """Free-form beta feedback with optional follow-up contact."""

    message: str = Field(..., min_length=1, max_length=2000)
    # Telegram handle, email, or whatever the user prefers. Kept as an
    # opaque string because we don't want to reject valid contacts over a
    # picky regex — we'll just read it by hand from the DB.
    contact: str | None = Field(default=None, max_length=200)
    # Optional context the client can attach (current path, last action,
    # browser sniff). Helps us reproduce the problem the user is describing.
    context: dict[str, Any] = Field(default_factory=dict)

    @field_validator("message", mode="before")
    @classmethod
    def _strip_message(cls, v: Any) -> Any:
        # Trim before the min_length check so "   " (whitespace only) is
        # treated as blank and rejected, matching the intent of "free-form
        # feedback must actually contain words".
        return v.strip() if isinstance(v, str) else v

    @field_validator("contact", mode="before")
    @classmethod
    def _normalize_contact(cls, v: Any) -> Any:
        # The client sends an empty string when the user didn't fill the
        # contact field — normalize that to None so the DB row does not
        # store a trailing-whitespace empty string.
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v
