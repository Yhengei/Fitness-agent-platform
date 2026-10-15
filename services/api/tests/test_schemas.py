import pytest
from pydantic import ValidationError

from app.schemas import CheckInInput, Exercise, LearningProposal


def test_checkin_rejects_out_of_range_readiness():
    with pytest.raises(ValidationError):
        CheckInInput(date="2026-10-14", energy=6, fatigue=2)


def test_exercise_rejects_impossible_load():
    with pytest.raises(ValidationError):
        Exercise(name="腿举", sets=3, reps=8, load_kg=-1)


def test_rest_day_allows_no_exercises():
    entry = CheckInInput(date="2026-10-14", energy=3, fatigue=2, did_train=False)
    assert entry.exercises == []


def test_learning_proposal_is_limited_to_supported_profile_parameter():
    with pytest.raises(ValidationError):
        LearningProposal(
            parameter="weekly_days",
            proposed_value=4,
            evidence_ids=["record-1"],
            sample_count=1,
            confidence="high",
            impact="low",
            rationale="unsupported parameter",
        )


def test_learning_proposal_rejects_out_of_range_rpe():
    with pytest.raises(ValidationError):
        LearningProposal(
            parameter="typical_rpe",
            proposed_value=11,
            evidence_ids=["record-1"],
            sample_count=1,
            confidence="high",
            impact="low",
            rationale="out of range",
        )
