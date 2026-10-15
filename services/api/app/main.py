import asyncio
import json
import os
from statistics import median
from datetime import date
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db import SessionLocal, get_session
from app.models import AgentRun, CheckIn, LearningProfileVersion, LearningProposalRow, PlanningRun, Profile
from app.provider import MODEL, PROVIDER, configuration_error, runtime_metadata
from app.reports import weekly_recommendations
from app.schemas import AgentRunView, CheckInInput, PlanningRunView, ProfileInput
from app.worker import run_planning

app = FastAPI(title="Fitness Agent Platform", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://localhost:{os.getenv('WEB_PORT', '8080')}",
        f"http://127.0.0.1:{os.getenv('WEB_PORT', '8080')}",
    ],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)


@app.get("/api/v1/health/live")
def live():
    return {"status": "ok"}


@app.get("/api/v1/health/ready")
def ready(session: Session = Depends(get_session)):
    try:
        session.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(503, detail=f"database unavailable: {exc}") from exc
    return {"status": "ready", "database": "ok", "redis": "configured", "provider": PROVIDER}


@app.get("/api/v1/system/runtime")
def runtime():
    return runtime_metadata()


@app.post("/api/v1/profile")
def save_profile(payload: ProfileInput, session: Session = Depends(get_session)):
    profile = session.scalar(select(Profile).limit(1))
    if not profile:
        profile = Profile(data=payload.model_dump())
        session.add(profile)
    else:
        profile.data = payload.model_dump()
    session.commit()
    return {"id": str(profile.id), "data": profile.data}


@app.get("/api/v1/profile")
def get_profile(session: Session = Depends(get_session)):
    profile = session.scalar(select(Profile).limit(1))
    return {"id": str(profile.id), "data": profile.data} if profile else {"id": None, "data": {}}


@app.post("/api/v1/check-ins")
def create_checkin(payload: CheckInInput, session: Session = Depends(get_session)):
    entry_date = date.fromisoformat(payload.date)
    if entry_date > date.today():
        raise HTTPException(422, detail="check-in date cannot be in the future")
    checkin = session.scalar(select(CheckIn).where(CheckIn.date == entry_date))
    if checkin:
        checkin.data = payload.model_dump()
    else:
        checkin = CheckIn(date=entry_date, data=payload.model_dump())
        session.add(checkin)
    session.commit()
    return {"id": str(checkin.id), "data": checkin.data}


@app.get("/api/v1/check-ins")
def list_checkins(session: Session = Depends(get_session)):
    entries = session.scalars(select(CheckIn).order_by(CheckIn.date.desc())).all()
    return [{"id": str(entry.id), "date": entry.date.isoformat(), "data": entry.data} for entry in entries]


@app.post("/api/v1/planning-runs", status_code=202)
def create_run(checkin_id: UUID, session: Session = Depends(get_session)):
    if error := configuration_error():
        raise HTTPException(503, detail=error)
    checkin = session.get(CheckIn, checkin_id)
    if not checkin:
        raise HTTPException(404, detail="check-in not found")
    run = PlanningRun(checkin_id=checkin.id, provider=PROVIDER, model=MODEL, status="queued")
    session.add(run)
    session.commit()
    try:
        run_planning.delay(str(run.id))
    except Exception as exc:
        run.status = "failed"
        run.error = f"task enqueue failed: {str(exc)[:900]}"
        session.commit()
        raise HTTPException(503, detail="planning worker is unavailable; run was not started") from exc
    return {"id": str(run.id), "status": run.status}


def run_view(run: PlanningRun) -> PlanningRunView:
    return PlanningRunView(id=run.id, status=run.status, provider=run.provider, model=run.model, plan=run.plan, conflicts=run.conflicts or [], agents=[AgentRunView.model_validate({"id": a.id, "agent": a.agent, "status": a.status, "output": a.output, "error": a.error, "duration_ms": a.duration_ms}) for a in run.agents])


@app.get("/api/v1/planning-runs/{run_id}", response_model=PlanningRunView)
def get_run(run_id: UUID, session: Session = Depends(get_session)):
    run = session.get(PlanningRun, run_id)
    if not run:
        raise HTTPException(404, detail="run not found")
    return run_view(run)


@app.get("/api/v1/plans/latest")
def latest_plan(session: Session = Depends(get_session)):
    run = session.scalar(select(PlanningRun).where(PlanningRun.plan.is_not(None)).order_by(PlanningRun.created_at.desc()).limit(1))
    return run_view(run) if run else {"plan": None}


@app.get("/api/v1/planning-runs", response_model=list[PlanningRunView])
def list_runs(limit: int = 20, session: Session = Depends(get_session)):
    safe_limit = min(max(limit, 1), 100)
    runs = session.scalars(select(PlanningRun).order_by(PlanningRun.created_at.desc()).limit(safe_limit)).all()
    return [run_view(run) for run in runs]


@app.get("/api/v1/learning-proposals")
def learning_proposals(session: Session = Depends(get_session)):
    rows = session.scalars(select(LearningProposalRow).order_by(LearningProposalRow.created_at.desc())).all()
    return [{"id": str(row.id), "status": row.status, **row.proposal} for row in rows]


@app.post("/api/v1/learning-proposals/{proposal_id}/approve")
def approve_proposal(proposal_id: UUID, session: Session = Depends(get_session)):
    row = session.get(LearningProposalRow, proposal_id)
    if not row:
        raise HTTPException(404, detail="learning proposal not found")
    if row.status not in {"pending", "rejected"}:
        raise HTTPException(409, detail=f"proposal is already {row.status}")
    proposed_value = row.proposal.get("proposed_value")
    if row.parameter != "typical_rpe" or not isinstance(proposed_value, (int, float)) or not 1 <= proposed_value <= 10:
        raise HTTPException(409, detail="proposal does not contain an allowed learning update")
    profile = session.scalar(select(Profile).limit(1))
    if not profile:
        raise HTTPException(409, detail="profile is required")
    values = dict(profile.data.get("learned", {}))
    values[row.parameter] = proposed_value
    profile.data = {**profile.data, "learned": values}
    row.status = "approved"
    session.add(LearningProfileVersion(values=values, source_proposal_id=row.id))
    session.commit()
    return {"id": str(row.id), "status": row.status, "values": values}


@app.post("/api/v1/learning-proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: UUID, session: Session = Depends(get_session)):
    row = session.get(LearningProposalRow, proposal_id)
    if not row:
        raise HTTPException(404, detail="learning proposal not found")
    if row.status != "pending":
        raise HTTPException(409, detail=f"proposal is already {row.status}")
    row.status = "rejected"
    session.commit()
    return {"id": str(row.id), "status": row.status}


@app.get("/api/v1/learning-profile/versions")
def learning_versions(session: Session = Depends(get_session)):
    rows = session.scalars(select(LearningProfileVersion).order_by(LearningProfileVersion.created_at.desc())).all()
    return [{"id": str(row.id), "values": row.values, "created_at": row.created_at.isoformat()} for row in rows]


@app.post("/api/v1/learning-profile/rollback")
def rollback_learning(version_id: UUID, session: Session = Depends(get_session)):
    version = session.get(LearningProfileVersion, version_id)
    profile = session.scalar(select(Profile).limit(1))
    if not version or not profile:
        raise HTTPException(404, detail="version or profile not found")
    profile.data = {**profile.data, "learned": version.values}
    restored = LearningProfileVersion(values=version.values)
    session.add(restored)
    session.commit()
    return {"id": str(restored.id), "values": restored.values}


@app.get("/api/v1/reports/weekly/latest")
def weekly_report(session: Session = Depends(get_session)):
    from datetime import timedelta

    start = date.today() - timedelta(days=6)
    rows = session.scalars(select(CheckIn).where(CheckIn.date >= start, CheckIn.date <= date.today()).order_by(CheckIn.date)).all()
    entries = [row.data for row in rows]
    workouts = [entry for entry in entries if entry.get("did_train")]
    weights = [entry["weight_kg"] for entry in entries if entry.get("weight_kg") is not None]
    rpes = [entry["rpe"] for entry in workouts if entry.get("rpe") is not None]
    tracked = [entry for entry in entries if entry.get("completion") != "none"]
    completion = {"full": 1.0, "partial": 0.5, "missed": 0.0}
    adherence = round(sum(completion.get(entry.get("completion"), 0.0) for entry in tracked) / len(tracked) * 100) if tracked else None
    weight_delta = round(weights[-1] - weights[0], 1) if len(weights) >= 4 and len(weights) > 1 else None
    pain_days = sum(bool(entry.get("pain")) for entry in entries)
    recommendations = weekly_recommendations(
        pain_days=pain_days,
        adherence_pct=adherence,
        median_rpe=median(rpes) if rpes else None,
        weight_sample_count=len(weights),
        weight_delta_kg=weight_delta,
    )
    median_rpe = median(rpes) if rpes else None
    return {
        "start": start.isoformat(), "end": date.today().isoformat(), "record_count": len(entries),
        "sessions": len(workouts), "adherence_pct": adherence, "median_rpe": median_rpe,
        "weight_sample_count": len(weights), "weight_delta_kg": weight_delta,
        "pain_days": pain_days, "recommendations": recommendations,
        "confidence": "medium" if len(entries) >= 5 else "low",
    }


@app.get("/api/v1/data/export")
def export_data(session: Session = Depends(get_session)):
    checkins = session.scalars(select(CheckIn).order_by(CheckIn.date)).all()
    runs = session.scalars(select(PlanningRun).order_by(PlanningRun.created_at)).all()
    proposals = session.scalars(select(LearningProposalRow).order_by(LearningProposalRow.created_at)).all()
    profile = session.scalar(select(Profile).limit(1))
    return {
        "profile": profile.data if profile else None,
        "check_ins": [{"date": row.date.isoformat(), "data": row.data} for row in checkins],
        "planning_runs": [{"id": str(row.id), "status": row.status, "plan": row.plan, "conflicts": row.conflicts} for row in runs],
        "learning_proposals": [{"id": str(row.id), "status": row.status, "proposal": row.proposal} for row in proposals],
    }


@app.delete("/api/v1/data")
def delete_data(session: Session = Depends(get_session)):
    session.query(AgentRun).delete(synchronize_session=False)
    session.query(PlanningRun).delete(synchronize_session=False)
    session.query(CheckIn).delete(synchronize_session=False)
    session.query(LearningProfileVersion).delete(synchronize_session=False)
    session.query(LearningProposalRow).delete(synchronize_session=False)
    session.query(Profile).delete(synchronize_session=False)
    session.commit()
    return {"deleted": True}


@app.get("/api/v1/planning-runs/{run_id}/events")
def run_events(run_id: UUID, session: Session = Depends(get_session)):
    if not session.get(PlanningRun, run_id):
        raise HTTPException(404, detail="run not found")

    async def stream():
        seen: dict[str, str] = {}
        while True:
            with SessionLocal() as current:
                run = current.get(PlanningRun, run_id)
                rows = current.scalars(select(AgentRun).where(AgentRun.planning_run_id == run_id).order_by(AgentRun.created_at)).all()
                for row in rows:
                    if seen.get(str(row.id)) == row.status:
                        continue
                    seen[str(row.id)] = row.status
                    payload = {"id": str(row.id), "agent": row.agent, "status": row.status, "output": row.output, "error": row.error, "duration_ms": row.duration_ms}
                    yield f"event: agent\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            state = {"run_id": str(run.id), "status": run.status, "plan": run.plan, "conflicts": run.conflicts or [], "error": run.error}
            yield f"event: run\ndata: {json.dumps(state, ensure_ascii=False)}\n\n"
            if state["status"] in {"completed", "failed"}:
                break
            await asyncio.sleep(0.7)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})



