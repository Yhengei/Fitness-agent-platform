import pytest

from app.provider import fake_result
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
