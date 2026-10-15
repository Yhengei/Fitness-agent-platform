import asyncio
import os
import time
from uuid import UUID

from celery import Celery
from sqlalchemy import select
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.db import SessionLocal
from app.graph import build_graph
from app.models import AgentRun, CheckIn, LearningProfileVersion, LearningProposalRow, PlanningRun, Profile
from app.provider import generate
from app.schemas import LearningProposal

celery_app = Celery("fitness-agent", broker=os.getenv("REDIS_URL", "redis://localhost:6379/0"), backend=os.getenv("REDIS_URL", "redis://localhost:6379/0"))
CHECKPOINT_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://fitness:fitness@localhost:5433/fitness").replace("postgresql+psycopg://", "postgresql://")


async def execute_graph(state: dict, run_id: str):
    async with AsyncPostgresSaver.from_conn_string(CHECKPOINT_URL) as checkpointer:
        await checkpointer.setup()
        graph = build_graph(checkpointer=checkpointer)
        return await asyncio.wait_for(graph.ainvoke(state, config={"recursion_limit": 30, "configurable": {"thread_id": run_id}}), timeout=720)


@celery_app.task(name="fitness.run_planning")
def run_planning(run_id: str):
    with SessionLocal() as session:
        run = session.get(PlanningRun, UUID(run_id))
        if not run:
            return
        checkin = session.get(CheckIn, run.checkin_id)
        profile = session.scalar(select(Profile))
        history_rows = session.scalars(select(CheckIn).order_by(CheckIn.date)).all()
        run.status = "running"
        session.commit()
        profile_data = profile.data if profile else {}
        history = [{**row.data, "record_id": str(row.id)} for row in history_rows]
        state = {"run_id": run_id, "checkin": checkin.data, "profile": profile_data, "history": history}
        try:
            result = asyncio.run(execute_graph(state, run_id))
            run.status = result.get("status", "completed")
            run.plan = result.get("final_plan")
            run.conflicts = result.get("conflicts", [])
            if checkin.data.get("did_train"):
                learning_started = time.perf_counter()
                try:
                    rpe_records = [
                        row for row in history
                        if row.get("did_train") and isinstance(row.get("rpe"), (int, float)) and 1 <= row["rpe"] <= 10
                    ]
                    evidence_ids = [row["record_id"] for row in rpe_records]
                    old_value = profile_data.get("learned", {}).get("typical_rpe")
                    learning = asyncio.run(generate("learning", {
                        "checkin": checkin.data,
                        "plan": run.plan,
                        "history": history,
                        "evidence_ids": evidence_ids,
                        "old_value": old_value,
                    }, LearningProposal))
                    proposal = learning.model_dump()
                    cited_ids = set(proposal["evidence_ids"])
                    valid_evidence = cited_ids.issubset(set(evidence_ids)) and len(cited_ids) >= 3
                    safe_auto = (
                        proposal["parameter"] == "typical_rpe"
                        and proposal["sample_count"] == len(cited_ids)
                        and valid_evidence
                        and proposal["impact"] == "low"
                        and proposal["confidence"] in {"medium", "high"}
                    )
                    proposal_row = LearningProposalRow(parameter=proposal["parameter"], proposal=proposal, status="auto_applied" if safe_auto else "pending")
                    session.add(proposal_row)
                    session.flush()
                    session.add(AgentRun(planning_run_id=run.id, agent="learning", status="succeeded", output=proposal, duration_ms=int((time.perf_counter() - learning_started) * 1000)))
                    if proposal_row.status == "auto_applied":
                        learned_values = dict(profile_data.get("learned", {}))
                        learned_values[proposal["parameter"]] = proposal["proposed_value"]
                        profile_data["learned"] = learned_values
                        if profile:
                            profile.data = profile_data
                        session.add(LearningProfileVersion(values=learned_values, source_proposal_id=proposal_row.id))
                except Exception as learning_error:
                    session.add(AgentRun(planning_run_id=run.id, agent="learning", status="failed", error=str(learning_error)[:1000], duration_ms=int((time.perf_counter() - learning_started) * 1000)))
            else:
                session.add(
                    AgentRun(
                        planning_run_id=run.id,
                        agent="learning",
                        status="skipped",
                        output={
                            "reason": "本次记录没有实际训练反馈，学习 Agent 等待下一次训练数据。",
                            "next_step": "勾选今天进行了训练，并填写训练 RPE；动作明细可选。",
                        },
                        duration_ms=0,
                    )
                )
            session.commit()
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)[:1000]
            session.commit()
