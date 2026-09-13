"""Candidate source boundaries and speech-preserving visual adjustments."""

from copy import deepcopy
from hashlib import sha256

from .models import BoundaryReview

REVIEW_VERSION = "cut-boundaries-v1"
MAX_SHIFT_MS = 120
BATCH_SIZE = 16


def candidate_boundaries(clips: list[dict], words: list[dict], duration_ms: int) -> list[dict]:
    boundaries = []
    for clip in clips:
        start, end = clip["source_start_ms"], clip["source_end_ms"]
        source_words = [w for w in words if w["source_id"] == clip["source_id"]]
        retained = [w for w in source_words if w["end_ms"] > start and w["start_ms"] < end]
        for side, timestamp in (("start", start), ("end", end)):
            lower, upper = max(0, timestamp - MAX_SHIFT_MS), min(duration_ms, timestamp + MAX_SHIFT_MS)
            if side == "start":
                lower = max(
                    lower, max((w["end_ms"] for w in source_words if w["end_ms"] <= start), default=0)
                )
                upper = min(upper, min((w["start_ms"] for w in retained), default=start), end - 1)
                neighbors = [c["source_end_ms"] for c in clips if c["source_end_ms"] <= start]
                if neighbors:
                    lower = max(lower, (max(neighbors) + start + 1) // 2)
            else:
                lower = max(lower, max((w["end_ms"] for w in retained), default=end), start + 1)
                upper = min(
                    upper,
                    min((w["start_ms"] for w in source_words if w["start_ms"] >= end), default=duration_ms),
                )
                neighbors = [c["source_start_ms"] for c in clips if c["source_start_ms"] >= end]
                if neighbors:
                    upper = min(upper, (min(neighbors) + end) // 2)
            # A candidate that intersects timestamped speech keeps its position for creator review.
            if lower > timestamp or upper < timestamp:
                lower = upper = timestamp
            boundaries.append(
                {
                    "id": "boundary_" + sha256(f"{clip['id']}:{side}".encode()).hexdigest()[:24],
                    "clip_id": clip["id"],
                    "source_id": clip["source_id"],
                    "side": side,
                    "timestamp_ms": timestamp,
                    "min_ms": lower,
                    "max_ms": upper,
                    "reason": clip["selection_reason"],
                    "words": [
                        w
                        for w in source_words
                        if w["end_ms"] > timestamp - 1500 and w["start_ms"] < timestamp + 1500
                    ],
                }
            )
    return boundaries


def apply_review(
    clips: list[dict], boundaries: list[dict], review: BoundaryReview
) -> tuple[list[dict], list[dict]]:
    expected = {b["id"]: b for b in boundaries}
    received = [d.boundary_id for d in review.decisions]
    if len(received) != len(set(received)) or set(received) != set(expected):
        raise ValueError("Boundary review must assess every requested boundary exactly once.")
    adjusted = deepcopy(clips)
    index = {c["id"]: c for c in adjusted}
    evidence = []
    for decision in review.decisions:
        boundary = expected[decision.boundary_id]
        safe = boundary["min_ms"] <= decision.timestamp_ms <= boundary["max_ms"]
        accepted = safe and decision.confidence >= 0.7
        timestamp = decision.timestamp_ms if accepted else boundary["timestamp_ms"]
        index[boundary["clip_id"]][f"source_{boundary['side']}_ms"] = timestamp
        evidence.append(
            {
                **decision.model_dump(),
                "candidate_ms": boundary["timestamp_ms"],
                "applied_ms": timestamp,
                "accepted": accepted,
                "needs_review": not accepted,
            }
        )
    for clip in adjusted:
        if clip["source_start_ms"] >= clip["source_end_ms"]:
            raise ValueError("Reviewed clip must retain positive duration.")
    return adjusted, evidence
