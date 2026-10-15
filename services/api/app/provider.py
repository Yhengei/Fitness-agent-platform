import asyncio
import json
import os
import threading
import weakref
from typing import Any

import httpx
from pydantic import BaseModel

PROVIDER = os.getenv("MODEL_PROVIDER", "fake")
MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
OLLAMA_URL = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
MODEL_GATES: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
MODEL_GATES_LOCK = threading.Lock()


def model_gate() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    with MODEL_GATES_LOCK:
        gate = MODEL_GATES.get(loop)
        if gate is None:
            gate = asyncio.Semaphore(1)
            MODEL_GATES[loop] = gate
        return gate


async def generate(agent: str, context: dict[str, Any], schema: type[BaseModel]) -> BaseModel:
    if PROVIDER == "fake":
        return fake_result(agent, context, schema)
    messages = [
        {"role": "system", "content": system_prompt(agent)},
        {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
    ]
    async with model_gate():
        last_error = None
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=90) as client:
                    response = await client.post(
                        f"{OLLAMA_URL.rstrip('/')}/api/chat",
                        json={"model": MODEL, "messages": messages, "stream": False, "format": schema.model_json_schema()},
                    )
                    response.raise_for_status()
                    raw = response.json()["message"]["content"]
                return schema.model_validate_json(raw)
            except Exception as exc:
                last_error = exc
                if attempt == 0:
                    messages.append({"role": "user", "content": "上次输出无效。请仅根据给定上下文重新生成，严格符合 JSON Schema。"})
        raise RuntimeError(f"{agent} provider failed after one retry: {last_error}") from last_error


def system_prompt(agent: str) -> str:
    roles = {
        "quality": "检查健身记录的数据缺失、冲突和异常。只输出 schema 要求的 JSON。不要编造数据。",
        "recovery": "评估训练准备度、疲劳和恢复约束。只输出 schema 要求的 JSON。不要制定完整训练计划。",
        "training": "根据训练历史生成下一次健身房训练，目标为减脂优先、力量维持。严格遵循恢复约束。只输出 JSON。",
        "fat_loss": "分析多日体重与执行趋势。不得根据单次体重判断减脂，不给缺乏依据的精确热量目标。只输出 JSON。",
        "coach": "基于真实专业 Agent 输出制定一份一致计划。明确接受/拒绝的意见，保守处理冲突。只输出 JSON。",
        "risk": "独立审核候选训练计划与疼痛、限制及恢复约束。疼痛优先，必要时停止。只输出 JSON。",
        "review": "针对给出的意见冲突进行一次复核，只分析指定冲突并输出 JSON。",
        "learning": "比较计划与实际训练及后续恢复，只能提议更新 typical_rpe（1 到 10 的数值）。sample_count 必须等于 evidence_ids 数量，且每个 evidence_id 必须来自输入。你只提案，不应用变更。只输出 JSON。",
    }
    return roles.get(agent, "分析输入并只输出符合 schema 的 JSON。")


def fake_result(agent: str, context: dict[str, Any], schema: type[BaseModel]) -> BaseModel:
    checkin = context.get("checkin", {})
    pain = checkin.get("pain", False)
    energy = checkin.get("energy", 3)
    fatigue = checkin.get("fatigue", 2)
    if agent == "training":
        status = "recover" if pain else "reduce" if energy <= 2 or fatigue >= 5 else "train"
        if "演示冲突" in checkin.get("notes", ""):
            status = "train"
        exercises = [] if status == "recover" else [
            {"name": "腿举", "sets": 2 if status == "reduce" else 3, "reps": 8, "load_kg": None},
            {"name": "坐姿划船", "sets": 2 if status == "reduce" else 3, "reps": 10, "load_kg": None},
        ]
        payload = {"agent": agent, "decision": status, "status": status, "confidence": "medium", "evidence": [], "constraints": {"allow_progression": status == "train"}, "rationale": "模拟运行：先保留主动作，训练量按恢复信号调整。", "exercises": exercises}
    elif agent == "recovery":
        status = "recover" if pain else "reduce" if energy <= 2 or fatigue >= 5 else "train"
        if "演示冲突" in checkin.get("notes", ""):
            status = "reduce"
        payload = {"agent": agent, "decision": status, "confidence": "medium", "evidence": [], "constraints": {"allow_progression": status == "train", "volume_multiplier": 0.65 if status == "reduce" else 1.0}, "rationale": f"模拟运行：精力 {energy}/5，疲劳 {fatigue}/5。"}
    elif agent == "risk":
        payload = {"agent": agent, "decision": "stop" if pain else "pass", "confidence": "high", "evidence": [], "constraints": {}, "rationale": "疼痛信号优先。" if pain else "未发现阻止计划的风险信号。"}
    elif agent == "coach":
        training = context.get("training", {})
        status = "recover" if pain else training.get("status", "train")
        payload = {"title": "恢复建议" if status == "recover" else "全身力量维持", "status": status, "summary": "模拟协调：基于专业 Agent 输出与安全约束形成候选方案。", "accepted_claims": ["recovery", "training", "fat_loss"], "rejected_claims": [], "exercises": training.get("exercises", [])}
    elif agent == "quality":
        payload = {"agent": agent, "decision": "usable", "confidence": "medium", "evidence": [], "constraints": {}, "rationale": "模拟运行：当前输入通过基础完整性检查。"}
    elif agent == "fat_loss":
        weights = [x.get("weight_kg") for x in context.get("history", []) if x.get("weight_kg") is not None]
        payload = {"agent": agent, "decision": "insufficient" if len(weights) < 4 else "trend_review", "confidence": "low" if len(weights) < 4 else "medium", "evidence": [], "constraints": {}, "rationale": f"模拟运行：可用体重记录 {len(weights)} 次，不据此推断单日变化。"}
    elif agent == "review":
        payload = {"agent": agent, "decision": "保守协调", "confidence": "medium", "evidence": [], "constraints": {"allow_progression": False}, "rationale": "模拟复核：冲突未能完全消除，建议不进阶并保留分歧。"}
    else:
        history = context.get("history", [])
        rpes = [row.get("rpe") for row in history if row.get("did_train") and row.get("rpe") is not None]
        samples = len(rpes)
        proposed = round(sum(rpes) / samples, 1) if samples else 7.0
        payload = {"parameter": "typical_rpe", "old_value": context.get("old_value"), "proposed_value": proposed, "evidence_ids": context.get("evidence_ids", []), "sample_count": samples, "confidence": "medium" if samples >= 3 else "low", "impact": "low", "rationale": "模拟运行：依据已记录训练 RPE 更新个人常见强度估计。" if samples >= 3 else "模拟运行：样本不足，作为待验证假设保存。"}
    return schema.model_validate(payload)
