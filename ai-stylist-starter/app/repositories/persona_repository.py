"""Repository for :class:`Persona` — персоны внутри аккаунта."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.persona import Persona


class PersonaRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    # -------- reads --------

    def get_by_id(self, persona_id: uuid.UUID) -> Persona | None:
        return self.db.get(Persona, persona_id)

    def list_by_user(self, user_id: uuid.UUID) -> list[Persona]:
        stmt = (
            select(Persona)
            .where(Persona.user_id == user_id)
            .order_by(Persona.is_primary.desc(), Persona.created_at.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_primary(self, user_id: uuid.UUID) -> Persona | None:
        stmt = select(Persona).where(
            Persona.user_id == user_id, Persona.is_primary.is_(True)
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def belongs_to(self, persona_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        stmt = select(Persona.id).where(
            Persona.id == persona_id, Persona.user_id == user_id
        )
        return self.db.execute(stmt).first() is not None

    # -------- writes --------

    def create(
        self,
        *,
        user_id: uuid.UUID,
        name: str,
        is_primary: bool = False,
    ) -> Persona:
        persona = Persona(user_id=user_id, name=name, is_primary=is_primary)
        self.db.add(persona)
        self.db.commit()
        self.db.refresh(persona)
        return persona

    def rename(self, persona_id: uuid.UUID, new_name: str) -> Persona | None:
        persona = self.get_by_id(persona_id)
        if persona is None:
            return None
        persona.name = new_name
        self.db.commit()
        self.db.refresh(persona)
        return persona

    def delete(self, persona_id: uuid.UUID) -> bool:
        persona = self.get_by_id(persona_id)
        if persona is None:
            return False
        if persona.is_primary:
            # Primary personas can't be deleted — they're the default for
            # backward-compat queries. Callers must handle this error.
            raise ValueError("primary persona cannot be deleted")
        self.db.delete(persona)
        self.db.commit()
        return True

    def ensure_primary(self, user_id: uuid.UUID) -> Persona:
        """Return existing primary Persona, or create one named 'Я'.

        Used by :func:`get_current_persona_id` when a request has no
        ``X-Persona-Id`` header — we fall back to the primary persona.
        For brand-new dev users (created on-the-fly by ``X-User-Id``
        fallback), the primary persona must be created here since no
        migration backfill has run for them.
        """
        primary = self.get_primary(user_id)
        if primary is not None:
            return primary
        return self.create(user_id=user_id, name="Я", is_primary=True)
