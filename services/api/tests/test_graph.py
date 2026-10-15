from uuid import uuid4

import pytest

import app.graph as graph_module
from app.provider import fake_result


@pytest.mark.asyncio
async def test_safety_rule_short_circuits_all_model_agents(monkeypatch):
    calls = []

    async def fake_call(state, agent, schema, context):
        calls.append(agent)
        return fake_result(agent, context, schema).model_dump()

    monkeypatch.setattr(graph_module, "_call", fake_call)
    result = await graph_module.build_graph().ainvoke({
        "run_id": str(uuid4()),
        "checkin": {"pain": True, "notes": "膝部疼痛"},
        "profile": {},
        "history": [],
    })

    assert calls == []
    assert result["status"] == "completed"
    assert result["final_plan"]["status"] == "stop"


@pytest.mark.asyncio
async def test_specialists_fan_in_and_conflict_triggers_one_review(monkeypatch):
    calls = []

    async def fake_call(state, agent, schema, context):
        calls.append(agent)
        return fake_result(agent, context, schema).model_dump()

    monkeypatch.setattr(graph_module, "_call", fake_call)
    result = await graph_module.build_graph().ainvoke({
        "run_id": str(uuid4()),
        "checkin": {
            "energy": 3,
            "fatigue": 2,
            "pain": False,
            "notes": "演示冲突",
        },
        "profile": {},
        "history": [],
    })

    assert {"quality", "recovery", "training", "fat_loss", "review", "coach", "risk"}.issubset(calls)
    assert calls.count("review") == 1
    assert result["conflicts"]
    assert result["final_plan"]["status"] == "reduce"
    assert result["status"] == "completed"
