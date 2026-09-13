from copy import deepcopy

import pytest
from editmaxxing.boundaries import apply_review, candidate_boundaries
from editmaxxing.models import BoundaryDecision, BoundaryReview


def case():
    words = [
        {"id": "before", "source_id": "body", "text": "Flub", "start_ms": 500, "end_ms": 900},
        {"id": "keep", "source_id": "body", "text": "Hello", "start_ms": 1100, "end_ms": 1800},
        {"id": "after", "source_id": "body", "text": "Retake", "start_ms": 2000, "end_ms": 2300},
    ]
    clips = [
        {
            "id": "c",
            "source_id": "body",
            "source_start_ms": 1000,
            "source_end_ms": 1900,
            "selection_reason": "Complete take",
        }
    ]
    return clips, candidate_boundaries(clips, words, 3000)


def review(boundaries, timestamps, confidence=1):
    return BoundaryReview(
        decisions=[
            BoundaryDecision(
                boundary_id=b["id"], timestamp_ms=t, confidence=confidence, reason="Mouth at rest"
            )
            for b, t in zip(boundaries, timestamps)
        ]
    )


def test_visual_adjustment_preserves_selected_word_and_excludes_neighboring_takes():
    clips, boundaries = case()
    adjusted, evidence = apply_review(clips, boundaries, review(boundaries, [1100, 1800]))
    assert adjusted[0]["source_start_ms"] == 1100
    assert adjusted[0]["source_end_ms"] == 1800
    assert clips[0]["source_start_ms"] == 1000
    assert all(e["accepted"] for e in evidence)
    for timestamps in ([1101, 1799], [879, 2021]):
        adjusted, evidence = apply_review(clips, boundaries, review(boundaries, timestamps))
        assert adjusted == clips
        assert all(e["needs_review"] for e in evidence)


def test_uncertain_review_retains_candidate_and_marks_playback():
    clips, boundaries = case()
    adjusted, evidence = apply_review(clips, boundaries, review(boundaries, [1100, 1800], 0.5))
    assert adjusted == clips
    assert all(e["needs_review"] for e in evidence)


@pytest.mark.parametrize("kind", ["missing", "duplicate", "unknown"])
def test_every_boundary_must_be_assessed_once(kind):
    clips, boundaries = case()
    result = review(boundaries, [1100, 1800])
    if kind == "missing":
        result.decisions.pop()
    elif kind == "duplicate":
        result.decisions[1] = deepcopy(result.decisions[0])
    else:
        result.decisions[1].boundary_id = "unknown"
    with pytest.raises(ValueError, match="exactly once"):
        apply_review(clips, boundaries, result)


def test_internal_silence_boundaries_share_gap_without_overlapping():
    words = [
        {"id": "a", "source_id": "body", "text": "A", "start_ms": 0, "end_ms": 500},
        {"id": "b", "source_id": "body", "text": "B", "start_ms": 900, "end_ms": 1400},
    ]
    clips = [
        {
            "id": "a",
            "source_id": "body",
            "source_start_ms": 0,
            "source_end_ms": 600,
            "selection_reason": "Silence",
        },
        {
            "id": "b",
            "source_id": "body",
            "source_start_ms": 800,
            "source_end_ms": 1400,
            "selection_reason": "Silence",
        },
    ]
    boundaries = candidate_boundaries(clips, words, 1400)
    assert boundaries[0]["min_ms"] == 0
    assert boundaries[-1]["max_ms"] == 1400
    assert boundaries[1]["max_ms"] <= boundaries[2]["min_ms"]
