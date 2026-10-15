from __future__ import annotations

import operator
import re
import time
from typing import Annotated, Any, TypedDict
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import AgentRun
from app.provider import generate
from app.schemas import CoachOutput, SpecialistOutput, TrainingOutput


class State(TypedDict, total=False):
    run_id: str
    checkin: dict
    profile: dict
    history: list[dict]
    quality: dict
    recovery: dict
    training: dict
    fat_loss: dict
    review: dict
    coach: dict
    risk: dict
    conflicts: Annotated[list[dict], operator.add]
    events: Annotated[list[dict], operator.add]
    final_plan: dict
    status: str
    critical: bool


async def _call(state: State, agent: str, schema: type, context: dict[str, Any]) -> dict:
    started = time.perf_counter()
    run_record_id = uuid4()
    with SessionLocal() as session:
        session.add(AgentRun(id=run_record_id, planning_run_id=UUID(state["run_id"]), agent=agent, status="running"))
        session.commit()
    try:
        result = await generate(agent, context, schema)
        output = result.model_dump()
        output["_duration_ms"] = int((time.perf_counter() - started) * 1000)
        output["_provider"] = __import__("app.provider", fromlist=["PROVIDER"]).PROVIDER
        with SessionLocal() as session:
            record = session.get(AgentRun, run_record_id)
            record.status = "succeeded"
            record.output = output
            record.duration_ms = output["_duration_ms"]
            session.commit()
        return output
    except Exception as exc:
        with SessionLocal() as session:
            record = session.get(AgentRun, run_record_id)
            record.status = "failed"
            record.error = str(exc)[:1000]
            record.duration_ms = int((time.perf_counter() - started) * 1000)
            session.commit()
        raise


async def quality_node(state: State):
    result = await _call(state, "quality", SpecialistOutput, {"checkin": state["checkin"], "profile": state.get("profile", {})})
    return {"quality": result, "events": [{"node": "quality", "status": "succeeded", "output": result}]}


def pre_safety_node(state: State):
    notes = state["checkin"].get("notes", "")
    critical = bool(re.search(r"胸痛|胸闷|呼吸困难|晕厥|昏厥|严重头晕", notes))
    if state["checkin"].get("pain") or critical:
        return {"critical": True, "final_plan": {"title": "暂停训练并评估不适", "status": "stop", "summary": "安全规则在模型调用前检测到疼痛或可能需要及时处理的症状，不生成训练负荷。必要时寻求专业评估。", "exercises": []}, "status": "completed", "events": [{"node": "deterministic_pre_safety", "status": "blocked", "output": {"pain": bool(state["checkin"].get("pain")), "critical_symptom": critical}}]}
    return {"critical": False, "events": [{"node": "deterministic_pre_safety", "status": "passed"}]}


def pre_safety_route(state: State) -> str:
    return "stop" if state.get("critical") else "quality"


async def stopped_node(state: State):
    return {"status": "completed"}


async def recovery_node(state: State):
    result = await _call(state, "recovery", SpecialistOutput, {"checkin": state["checkin"], "history": state.get("history", [])[-14:]})
    return {"recovery": result, "events": [{"node": "recovery", "status": "succeeded", "output": result}]}


async def training_node(state: State):
    result = await _call(state, "training", TrainingOutput, {"checkin": state["checkin"], "profile": state.get("profile", {}), "history": state.get("history", [])[-28:]})
    return {"training": result, "events": [{"node": "training", "status": "succeeded", "output": result}]}


async def fat_loss_node(state: State):
    result = await _call(state, "fat_loss", SpecialistOutput, {"checkin": state["checkin"], "history": state.get("history", [])[-30:]})
    return {"fat_loss": result, "events": [{"node": "fat_loss", "status": "succeeded", "output": result}]}


async def detect_conflicts(state: State):
    conflicts = []
    recovery = state["recovery"]
    training = state["training"]
    if recovery.get("constraints", {}).get("allow_progression") is False and training.get("constraints", {}).get("allow_progression") is True:
        conflicts.append({"kind": "progression", "agents": ["recovery", "training"], "detail": "恢复 Agent 禁止进阶，但训练 Agent 提出进阶。"})
    if recovery.get("decision") != training.get("status"):
        conflicts.append({"kind": "readiness", "agents": ["recovery", "training"], "detail": "恢复与训练 Agent 对训练准备度判断不同。"})
    if state["checkin"].get("pain") and training.get("exercises"):
        conflicts.append({"kind": "pain_plan", "agents": ["training", "risk"], "detail": "存在疼痛记录，但训练草案仍包含动作。"})
    event = {"node": "conflict_detector", "status": "succeeded", "conflicts": conflicts}
    return {"conflicts": conflicts, "events": [event]}


def conflict_route(state: State) -> str:
    return "review" if state.get("conflicts") else "coach"


async def review_node(state: State):
    result = await _call(state, "review", SpecialistOutput, {"conflicts": state.get("conflicts", []), "recovery": state["recovery"], "training": state["training"]})
    return {"review": result, "events": [{"node": "targeted_review", "status": "succeeded", "output": result}]}


async def coach_node(state: State):
    context = {"checkin": state["checkin"], "recovery": state["recovery"], "training": state["training"], "fat_loss": state["fat_loss"], "conflicts": state.get("conflicts", []), "review": state.get("review")}
    result = await _call(state, "coach", CoachOutput, context)
    return {"coach": result, "events": [{"node": "coach", "status": "succeeded", "output": result}]}


async def risk_node(state: State):
    result = await _call(state, "risk", SpecialistOutput, {"checkin": state["checkin"], "profile": state.get("profile", {}), "candidate_plan": state["coach"]})
    return {"risk": result, "events": [{"node": "risk", "status": "succeeded", "output": result}]}


async def final_gate(state: State):
    coach = dict(state["coach"])
    risk = state["risk"]
    checkin = state["checkin"]
    blocked = checkin.get("pain") or risk.get("decision") == "stop"
    if blocked:
        coach.update({"title": "暂停训练并评估不适", "status": "stop", "summary": "风险审核或疼痛记录阻止了训练计划。请停止相关训练，必要时寻求专业评估。", "exercises": []})
    if state.get("recovery", {}).get("constraints", {}).get("allow_progression") is False and coach.get("status") == "train":
        coach["status"] = "reduce"
        coach["summary"] += " 恢复约束优先，取消进阶建议。"
    limitations = str(state.get("profile", {}).get("limitations", "")).lower()
    restricted_terms = {
        "knee": ("膝", "髌", "knee", "leg press", "lunge", "跑步机", "单车", "深蹲", "腿举"),
        "back": ("腰", "下背", "腰椎", "back", "deadlift", "硬拉", "划船"),
        "shoulder": ("肩", "肩袖", "shoulder", "press", "推举", "胸推", "下拉"),
    }
    blocked_exercises: set[str] = set()
    for group, terms in restricted_terms.items():
        if any(term in limitations for term in terms[:4]):
            blocked_exercises.update(term for term in terms[4:] if any(term in str(ex.get("name", "")).lower() for ex in coach.get("exercises", [])))
    if blocked_exercises:
        coach["exercises"] = [ex for ex in coach.get("exercises", []) if not any(term in str(ex.get("name", "")).lower() for term in blocked_exercises)]
        coach["status"] = "reduce" if coach["exercises"] else "stop"
        coach["summary"] += " 个人限制规则过滤了相关动作，请勿用引发不适的动作替换。"
    return {"final_plan": coach, "status": "completed", "events": [{"node": "deterministic_final_gate", "status": "blocked" if blocked else "passed", "output": {"status": coach["status"]}}]}


def build_graph(checkpointer=None):
    builder = StateGraph(State)
    builder.add_node("quality", quality_node)
    builder.add_node("pre_safety", pre_safety_node)
    builder.add_node("stopped", stopped_node)
    builder.add_node("recovery", recovery_node)
    builder.add_node("training", training_node)
    builder.add_node("fat_loss", fat_loss_node)
    builder.add_node("conflicts", detect_conflicts)
    builder.add_node("review", review_node)
    builder.add_node("coach", coach_node)
    builder.add_node("risk", risk_node)
    builder.add_node("final_gate", final_gate)
    builder.add_edge(START, "pre_safety")
    builder.add_conditional_edges("pre_safety", pre_safety_route, {"stop": "stopped", "quality": "quality"})
    builder.add_edge("stopped", END)
    builder.add_edge("quality", "recovery")
    builder.add_edge("quality", "training")
    builder.add_edge("quality", "fat_loss")
    builder.add_edge(["recovery", "training", "fat_loss"], "conflicts")
    builder.add_conditional_edges("conflicts", conflict_route, {"review": "review", "coach": "coach"})
    builder.add_edge("review", "coach")
    builder.add_edge("coach", "risk")
    builder.add_edge("risk", "final_gate")
    builder.add_edge("final_gate", END)
    return builder.compile(checkpointer=checkpointer)
