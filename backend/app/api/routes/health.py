from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_session

router = APIRouter(tags=["health"])


@router.get("/health")
def liveness() -> dict:
    return {"status": "ok"}


@router.get("/health/db")
def db_roundtrip(session: Session = Depends(get_session)) -> dict:
    session.execute(text("SELECT 1"))
    return {"status": "ok"}
