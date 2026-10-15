import json

import httpx
import pytest

import app.provider as provider
from app.provider import ProviderError, fake_result
from app.schemas import SpecialistOutput, TrainingOutput


def test_fake_provider_can_create_reviewable_conflict():
    context = {"checkin": {"energy": 3, "fatigue": 2, "pain": False, "notes": "演示冲突"}}
    recovery = fake_result("recovery", context, SpecialistOutput)
    training = fake_result("training", context, TrainingOutput)
    assert recovery.decision == "reduce"
    assert recovery.constraints["allow_progression"] is False
    assert training.status == "train"
    assert training.constraints["allow_progression"] is True


def test_pain_stops_fake_training():
    context = {"checkin": {"energy": 5, "fatigue": 1, "pain": True, "notes": ""}}
    training = fake_result("training", context, TrainingOutput)
    assert training.status == "recover"
    assert training.exercises == []


@pytest.mark.parametrize("weights,confidence", [([], "low"), ([70, 69.8, 69.7, 69.5], "medium")])
def test_fat_loss_requires_multiple_weight_samples(weights, confidence):
    context = {"checkin": {}, "history": [{"weight_kg": value} for value in weights]}
    result = fake_result("fat_loss", context, SpecialistOutput)
    assert result.confidence == confidence


def specialist_payload() -> dict:
    return {
        "agent": "recovery",
        "decision": "train",
        "confidence": "medium",
        "evidence": [],
        "constraints": {"allow_progression": True},
        "rationale": "恢复状态允许正常训练。",
    }


def configure_cloud(monkeypatch):
    monkeypatch.setattr(provider, "MODEL_BASE_URL", "https://example.test/v1")
    monkeypatch.setattr(provider, "MODEL_NAME", "qwen-plus")
    monkeypatch.setattr(provider, "MODEL_API_KEY", "sk-test-secret-8A2F")


def mock_client(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(provider, "_client", lambda: httpx.AsyncClient(transport=transport))


@pytest.mark.asyncio
async def test_cloud_provider_accepts_fenced_json(monkeypatch):
    configure_cloud(monkeypatch)
    content = f"```json\n{json.dumps(specialist_payload(), ensure_ascii=False)}\n```"
    mock_client(monkeypatch, lambda request: httpx.Response(200, json={"choices": [{"message": {"content": content}}]}))

    result = await provider.generate_openai_compatible("recovery", {}, SpecialistOutput)

    assert result.decision == "train"


@pytest.mark.asyncio
async def test_invalid_output_is_retried_once(monkeypatch):
    configure_cloud(monkeypatch)
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        content = "not json" if calls == 1 else json.dumps(specialist_payload())
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    mock_client(monkeypatch, handler)
    monkeypatch.setattr(provider.asyncio, "sleep", lambda _: _completed())

    result = await provider.generate_openai_compatible("recovery", {}, SpecialistOutput)

    assert calls == 2
    assert result.agent == "recovery"


async def _completed():
    return None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500, 503])
async def test_retryable_http_status_retries_once(monkeypatch, status):
    configure_cloud(monkeypatch)
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(status)

    mock_client(monkeypatch, handler)
    monkeypatch.setattr(provider.asyncio, "sleep", lambda _: _completed())

    with pytest.raises(ProviderError, match="temporarily unavailable"):
        await provider.generate_openai_compatible("recovery", {}, SpecialistOutput)

    assert calls == 2


@pytest.mark.asyncio
async def test_timeout_retries_once_without_leaking_key(monkeypatch):
    configure_cloud(monkeypatch)
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("request timed out", request=request)

    mock_client(monkeypatch, handler)
    monkeypatch.setattr(provider.asyncio, "sleep", lambda _: _completed())

    with pytest.raises(ProviderError) as error:
        await provider.generate_openai_compatible("recovery", {}, SpecialistOutput)

    assert calls == 2
    assert "sk-test-secret-8A2F" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_auth_failure_does_not_retry_or_leak_key(monkeypatch, status):
    configure_cloud(monkeypatch)
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(status, text="bad token sk-test-secret-8A2F")

    mock_client(monkeypatch, handler)

    with pytest.raises(ProviderError) as error:
        await provider.generate_openai_compatible("recovery", {}, SpecialistOutput)

    assert calls == 1
    assert "sk-test-secret-8A2F" not in str(error.value)


@pytest.mark.asyncio
async def test_missing_cloud_key_fails_before_network(monkeypatch):
    configure_cloud(monkeypatch)
    monkeypatch.setattr(provider, "MODEL_API_KEY", "")

    with pytest.raises(ProviderError, match="not configured"):
        await provider.generate_openai_compatible("recovery", {}, SpecialistOutput)


def test_runtime_metadata_masks_cloud_key(monkeypatch):
    configure_cloud(monkeypatch)
    monkeypatch.setattr(provider, "PROVIDER", "openai_compatible")
    monkeypatch.setattr(provider, "MODEL", "qwen-plus")

    metadata = provider.runtime_metadata()

    assert metadata["mode"] == "live-cloud"
    assert metadata["provider_label"] == "Alibaba Cloud Bailian"
    assert metadata["api_key_configured"] is True
    assert metadata["api_key_hint"] == "****8A2F"
    assert "sk-test-secret" not in json.dumps(metadata)


def test_cloud_configuration_error_is_explicit(monkeypatch):
    monkeypatch.setattr(provider, "PROVIDER", "openai_compatible")
    monkeypatch.setattr(provider, "MODEL_BASE_URL", "https://example.test/v1")
    monkeypatch.setattr(provider, "MODEL_NAME", "qwen-plus")
    monkeypatch.setattr(provider, "MODEL_API_KEY", "")

    error = provider.configuration_error()

    assert error is not None
    assert "MODEL_API_KEY" in error
