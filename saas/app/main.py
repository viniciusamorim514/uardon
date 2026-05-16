from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .db import create_job, create_lead, get_job, init_db, list_jobs, list_leads
from .schemas import CreateJobRequest, CreateLeadRequest, JobResponse, LeadResponse
from .settings import DEFAULT_USER_ID
from .worker import enqueue_job


app = FastAPI(title="Poder em Jogo API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    init_db()


def user_id_from_header(x_user_id: str | None) -> str:
    return x_user_id or DEFAULT_USER_ID


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "poder-em-jogo-api"}


@app.post("/v1/jobs", response_model=JobResponse)
def create_cut_job(payload: CreateJobRequest, x_user_id: str | None = Header(default=None)) -> dict:
    user_id = user_id_from_header(x_user_id)
    request = payload.model_dump(mode="json")
    job = create_job(str(uuid4()), user_id, str(payload.url), request)
    enqueue_job(job["id"])
    return job


@app.get("/v1/jobs", response_model=list[JobResponse])
def get_jobs(x_user_id: str | None = Header(default=None), limit: int = 30) -> list[dict]:
    user_id = user_id_from_header(x_user_id)
    return list_jobs(user_id, max(1, min(100, limit)))


@app.get("/v1/jobs/{job_id}", response_model=JobResponse)
def get_cut_job(job_id: str, x_user_id: str | None = Header(default=None)) -> dict:
    user_id = user_id_from_header(x_user_id)
    job = get_job(job_id, user_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job nao encontrado")
    return job


@app.post("/v1/leads", response_model=LeadResponse, status_code=201)
def create_crm_lead(payload: CreateLeadRequest, x_user_id: str | None = Header(default=None)) -> dict:
    user_id = user_id_from_header(x_user_id)
    return create_lead(
        str(uuid4()),
        user_id,
        payload.name.strip(),
        payload.phone.strip(),
        payload.city.strip(),
        payload.project_type.strip(),
        payload.message.strip(),
        payload.source.strip() or "landing-page",
        payload.metadata,
    )


@app.get("/v1/leads", response_model=list[LeadResponse])
def get_leads(x_user_id: str | None = Header(default=None), limit: int = 50) -> list[dict]:
    user_id = user_id_from_header(x_user_id)
    return list_leads(user_id, max(1, min(200, limit)))
