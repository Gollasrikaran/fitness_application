"""FastAPI app.  Run:  uvicorn app.main:app --reload --port 8000"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.config import settings
from app.db import SessionLocal
from app.models import Condition
from app.routers import auth, doctor, patient
from app.seed import init_db, load_reference_data

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with SessionLocal() as db:  # first run: load conditions/exercises/safety rules
        if db.scalar(select(Condition).limit(1)) is None:
            load_reference_data(db)
            db.commit()
    yield


app = FastAPI(title="VitaInspire Medical Agent", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(auth.router)
app.include_router(patient.router)
app.include_router(doctor.router)


@app.get("/health")
def health():
    return {"status": "ok", "llm_configured": bool(settings.openrouter_api_key), "model": settings.llm_model}
