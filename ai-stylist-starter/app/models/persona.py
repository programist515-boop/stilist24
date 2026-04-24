"""Persona — «лицо» внутри одного аккаунта.

Пользователь (``User``) — владелец аккаунта. Персоны — это люди, чей
гардероб и анализ внешности ведутся под этим аккаунтом: «я», «мама»,
«партнёр», «дочь». У каждой персоны собственный набор фото, вещей,
типажа и цветотипа.

Связь ``User 1:N Persona``. У каждого юзера есть ровно одна
``is_primary=True`` персона (автоматически создана миграцией для всех
существующих юзеров).
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Persona(Base):
    __tablename__ = "personas"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
