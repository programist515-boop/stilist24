"""CRUD routes for personas — «лица» внутри одного аккаунта.

``/personas`` endpoints:

* ``GET /personas`` — list all personas of the authenticated user
  (primary first, then by creation date).
* ``POST /personas`` — create a new non-primary persona with a name.
* ``PATCH /personas/{id}`` — rename a persona.
* ``DELETE /personas/{id}`` — delete a non-primary persona. The
  primary persona cannot be deleted because it's the fallback for
  legacy requests that don't present an ``X-Persona-Id`` header.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_id, get_db
from app.repositories.persona_repository import PersonaRepository

router = APIRouter()


# ---------------------------------------------------------- schemas


class PersonaOut(BaseModel):
    id: uuid.UUID
    name: str
    is_primary: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PersonaCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class PersonaRenameIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class PersonaListOut(BaseModel):
    personas: list[PersonaOut]


# ---------------------------------------------------------- routes


@router.get("", response_model=PersonaListOut)
def list_personas(
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> PersonaListOut:
    repo = PersonaRepository(db)
    # Materialize primary-on-read: if the user has no personas yet (dev
    # user created mid-request by X-User-Id fallback), create the default
    # one so the response is never empty.
    repo.ensure_primary(current_user_id)
    personas = repo.list_by_user(current_user_id)
    return PersonaListOut(personas=[PersonaOut.model_validate(p) for p in personas])


@router.post("", response_model=PersonaOut, status_code=201)
def create_persona(
    payload: PersonaCreateIn,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> PersonaOut:
    repo = PersonaRepository(db)
    # Make sure the primary always exists before adding secondaries,
    # otherwise a brand-new user's first POST would leave them with
    # only a non-primary persona and break the fallback dependency.
    repo.ensure_primary(current_user_id)
    persona = repo.create(
        user_id=current_user_id, name=payload.name, is_primary=False
    )
    return PersonaOut.model_validate(persona)


@router.patch("/{persona_id}", response_model=PersonaOut)
def rename_persona(
    persona_id: uuid.UUID,
    payload: PersonaRenameIn,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> PersonaOut:
    repo = PersonaRepository(db)
    if not repo.belongs_to(persona_id, current_user_id):
        raise HTTPException(status_code=404, detail="persona not found")
    persona = repo.rename(persona_id, payload.name)
    if persona is None:
        raise HTTPException(status_code=404, detail="persona not found")
    return PersonaOut.model_validate(persona)


@router.delete("/{persona_id}", status_code=204)
def delete_persona(
    persona_id: uuid.UUID,
    current_user_id: uuid.UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
) -> None:
    repo = PersonaRepository(db)
    if not repo.belongs_to(persona_id, current_user_id):
        raise HTTPException(status_code=404, detail="persona not found")
    try:
        repo.delete(persona_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return None
