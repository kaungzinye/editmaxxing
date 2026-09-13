"""Compile editorial word references into source-anchored, revisionable edits."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from heapq import heappop, heappush
from itertools import pairwise
from typing import Any

from .models import Plan


class EditError(ValueError):
    pass


def _record(value: Any) -> dict:
    return value.model_dump() if hasattr(value, "model_dump") else dict(value)


def _identity(prefix: str, *parts: Any) -> str:
    return f"{prefix}_{sha256('|'.join(map(str, parts)).encode()).hexdigest()[:24]}"


def _words(words: list[dict], sources: dict[str, dict]) -> dict[str, dict]:
    index = {}
    for item in words:
        word = _record(item)
        if word["id"] in index:
            raise EditError(f"Word {word['id']} appears more than once.")
        source = sources.get(word["source_id"])
        if source is None:
            raise EditError(f"Word {word['id']} references an unknown source.")
        if not 0 <= word["start_ms"] < word["end_ms"] <= source["duration_ms"]:
            raise EditError(f"Word {word['id']} has an invalid source range.")
        index[word["id"]] = word
    return index


def _take_words(take: dict, index: dict[str, dict]) -> list[dict]:
    ids = take.get("word_ids", [])
    if not ids or len(ids) != len(set(ids)):
        raise EditError(f"Take {take['id']} needs distinct word references.")
    try:
        words = [index[word_id] for word_id in ids]
    except KeyError as exc:
        raise EditError(f"Take {take['id']} references an unknown word.") from exc
    if len({word["source_id"] for word in words}) != 1:
        raise EditError(f"Take {take['id']} spans multiple sources.")
    if words != sorted(words, key=lambda w: (w["start_ms"], w["end_ms"], w["id"])):
        raise EditError(f"Take {take['id']} word references need chronological order.")
    if not set(take.get("emphasis_word_ids", [])).issubset(ids):
        raise EditError(f"Take {take['id']} emphasis references a different take.")
    return words


def clips_for_take(
    take: dict,
    words: list[dict],
    sources: dict[str, dict],
    silence_maps: dict[str, list[dict]] | None = None,
    dead_space_enabled: bool = True,
) -> list[dict]:
    take = _record(take)
    sources = {key: _record(value) for key, value in sources.items()}
    index = _words(words, sources)
    chosen = _take_words(take, index)
    source_id = chosen[0]["source_id"]
    source_words = sorted(
        (word for word in index.values() if word["source_id"] == source_id),
        key=lambda word: (word["start_ms"], word["end_ms"], word["id"]),
    )
    speech_start, speech_end = chosen[0]["start_ms"], max(w["end_ms"] for w in chosen)
    previous_end = max((w["end_ms"] for w in source_words if w["end_ms"] <= speech_start), default=0)
    next_start = min(
        (w["start_ms"] for w in source_words if w["start_ms"] >= speech_end),
        default=sources[source_id]["duration_ms"],
    )
    start = max(0, speech_start - 150, previous_end)
    end = min(sources[source_id]["duration_ms"], speech_end + 150, next_start)
    detected = None if silence_maps is None else silence_maps.get(source_id)
    if detected is not None:
        left = [
            max(start, s["start_ms"])
            for s in detected
            if s["start_ms"] < speech_start and s["end_ms"] >= start
        ]
        right = [min(end, s["end_ms"]) for s in detected if s["end_ms"] > speech_end and s["start_ms"] <= end]
        start = min(left) if left else speech_start
        end = max(right) if right else speech_end
    script = next(
        (s for s in sources[source_id].get("hook_scripts", []) if s["hook_id"] == take["line_id"]), None
    )
    if script and script["action_start_ms"] is not None:
        if script["action_start_ms"] > speech_start:
            raise EditError("The physical action must begin before the first spoken word.")
        start = script["action_start_ms"]
    cuts = []
    if dead_space_enabled:
        audible = [w for w in source_words if w["end_ms"] > start and w["start_ms"] < end]
        covered_until = start
        for word in audible:
            gap_start, gap_end = covered_until, word["start_ms"]
            if gap_start > start and gap_end - gap_start > 700:
                intervals = [{"start_ms": gap_start, "end_ms": gap_end}] if detected is None else detected
                for silence in intervals:
                    left = max(gap_start, silence["start_ms"])
                    right = min(gap_end, silence["end_ms"])
                    if right - left > 700:
                        cuts.append((left + 125, right - 125))
            covered_until = max(covered_until, word["end_ms"])
    ranges, cursor = [], start
    for left, right in sorted(cuts):
        if left > cursor and right > left:
            ranges.append((cursor, left))
            cursor = right
    if end > cursor:
        ranges.append((cursor, end))
    return [
        {
            "id": _identity("clip", take["id"], number),
            "source_id": source_id,
            "line_id": take["line_id"],
            "take_id": take["id"],
            "role": take["role"],
            "source_start_ms": left,
            "source_end_ms": right,
            "selection_reason": take.get("reason", "Selected take"),
        }
        for number, (left, right) in enumerate(ranges)
    ]


def _caption_chunks(words: list[dict]) -> list[list[dict]]:
    runs, current, covered_until = [], [], 0
    for word in words:
        if current and word["start_ms"] - covered_until > 700:
            runs.append(current)
            current = []
        current.append(word)
        covered_until = max(covered_until, word["end_ms"])
    if current:
        runs.append(current)
    chunks = []
    for run in runs:
        count = (len(run) + 3) // 4
        size, extra = divmod(len(run), count)
        cursor = 0
        for number in range(count):
            end = cursor + size + (number < extra)
            chunks.append(run[cursor:end])
            cursor = end
    return chunks


def _caption_lane(candidates: list[tuple[int, dict]], source_offset_ms: int) -> list[dict]:
    """Give creator edits their anchored intervals on a single caption lane."""
    starts = {}
    boundaries = set()
    for number, (priority, caption) in enumerate(candidates):
        left, right = caption["start_ms"], caption["end_ms"]
        starts.setdefault(left, []).append((-priority, -left, -number, number))
        boundaries.update((left, right))
    active, segments = [], []
    for left, right in pairwise(sorted(boundaries)):
        for item in starts.get(left, []):
            heappush(active, item)
        while active and candidates[active[0][3]][1]["end_ms"] <= left:
            heappop(active)
        if not active:
            continue
        winner = active[0][3]
        if segments and segments[-1][0] == winner and segments[-1][2] == left:
            segments[-1] = (winner, segments[-1][1], right)
        else:
            segments.append((winner, left, right))
    counts = {}
    for winner, _, _ in segments:
        counts[winner] = counts.get(winner, 0) + 1
    captions = []
    for winner, left, right in segments:
        caption = deepcopy(candidates[winner][1])
        visible = []
        for word in caption["words"]:
            if word["start_ms"] is None:
                visible.append(word)
            elif word["end_ms"] > left and word["start_ms"] < right:
                visible.append(
                    {**word, "start_ms": max(left, word["start_ms"]), "end_ms": min(right, word["end_ms"])}
                )
        if not visible:
            continue
        if counts[winner] > 1:
            caption["id"] = _identity(
                "caption", caption["id"], left - source_offset_ms, right - source_offset_ms
            )
        caption.update(start_ms=left, end_ms=right, words=visible)
        if caption["emphasis_word_id"] not in {word["word_id"] for word in visible}:
            caption["emphasis_word_id"] = None
        captions.append(caption)
    return captions


def canonicalize_plan(
    plan: dict,
    words: list[dict],
    sources: dict[str, dict],
    takes: dict[str, dict] | None = None,
) -> dict:
    """Derive captions and duration; source anchors keep edits attached to occurrences."""
    canonical = Plan.model_validate(plan).model_dump()
    canonical["caption_style"]["preset"] = "spoken_outline"
    sources = {key: _record(value) for key, value in sources.items()}
    index = _words(words, sources)
    takes = None if takes is None else {key: _record(value) for key, value in takes.items()}
    clip_ids, seen_body = set(), False
    for clip in canonical["clips"]:
        if clip["id"] in clip_ids:
            raise EditError(f"Clip {clip['id']} appears more than once.")
        clip_ids.add(clip["id"])
        source = sources.get(clip["source_id"])
        if source is None or clip["source_end_ms"] > source["duration_ms"]:
            raise EditError(f"Clip {clip['id']} exceeds its source range.")
        if clip["role"] == "body":
            seen_body = True
        elif seen_body:
            raise EditError("Hook clips must precede body clips.")
        if takes is not None:
            take = takes.get(clip["take_id"])
            if take is None:
                raise EditError(f"Clip {clip['id']} references an unknown take.")
            take_words = _take_words(take, index)
            if (
                take["line_id"] != clip["line_id"]
                or take["role"] != clip["role"]
                or take_words[0]["source_id"] != clip["source_id"]
            ):
                raise EditError(f"Clip {clip['id']} has inconsistent take references.")
    for take_id in dict.fromkeys(c["take_id"] for c in canonical["clips"] if c["role"] == "hook"):
        retained = [c for c in canonical["clips"] if c["take_id"] == take_id]
        first = retained[0]
        script = next(
            (
                s
                for s in sources[first["source_id"]].get("hook_scripts", [])
                if s["hook_id"] == first["line_id"]
            ),
            None,
        )
        if script and script["action_start_ms"] is not None:
            opening_words = _take_words(takes[take_id], index) if takes else []
            if first["source_start_ms"] != script["action_start_ms"] or (
                opening_words and first["source_end_ms"] <= opening_words[0]["start_ms"]
            ):
                raise EditError(
                    "The hook opening must retain the confirmed physical action through its first spoken word."
                )
    edit_ids = set()
    for edit in canonical["caption_edits"]:
        if edit["id"] in edit_ids:
            raise EditError(f"Caption edit {edit['id']} appears more than once.")
        edit_ids.add(edit["id"])
        refs = set(edit["replaces_word_ids"]) | {
            word["word_id"] for word in edit["words"] if word["word_id"] is not None
        }
        if not refs.issubset(index):
            raise EditError(f"Caption edit {edit['id']} references an unknown word.")
        word_ids = {word["word_id"] for word in edit["words"]}
        if edit["emphasis_word_id"] is not None and edit["emphasis_word_id"] not in word_ids:
            raise EditError(f"Caption edit {edit['id']} emphasis must reference its text.")
    captions, offset = [], 0
    for clip in canonical["clips"]:
        start, end = clip["source_start_ms"], clip["source_end_ms"]
        candidates = []
        clip_edits = [edit for edit in canonical["caption_edits"] if edit["clip_id"] == clip["id"]]
        for edit in clip_edits:
            refs = set(edit["replaces_word_ids"]) | {
                word["word_id"] for word in edit["words"] if word["word_id"] is not None
            }
            if any(index[word_id]["source_id"] != clip["source_id"] for word_id in refs):
                raise EditError(f"Caption edit {edit['id']} references a different source.")
        overlapping = sorted(
            (
                word
                for word in index.values()
                if word["source_id"] == clip["source_id"]
                and word["end_ms"] > start
                and word["start_ms"] < end
            ),
            key=lambda word: (word["start_ms"], word["end_ms"], word["id"]),
        )
        visible = []
        for word in overlapping:
            suppressed = any(
                word["id"] in edit["replaces_word_ids"]
                or (
                    edit["deleted"]
                    and not edit["replaces_word_ids"]
                    and word["end_ms"] > edit["source_start_ms"]
                    and word["start_ms"] < edit["source_end_ms"]
                )
                for edit in clip_edits
            )
            if not suppressed:
                visible.append(
                    {**word, "start_ms": max(start, word["start_ms"]), "end_ms": min(end, word["end_ms"])}
                )
        emphasis = set((takes or {}).get(clip["take_id"], {}).get("emphasis_word_ids", []))
        for chunk in _caption_chunks(visible):
            focused = next((word["id"] for word in chunk if word["id"] in emphasis), None)
            focused = focused or max(chunk, key=lambda word: len(word["text"].strip(".,!?;:")))["id"]
            candidates.append(
                (
                    0,
                    {
                        "id": _identity("caption", clip["id"], *(word["id"] for word in chunk)),
                        "clip_id": clip["id"],
                        "start_ms": offset + chunk[0]["start_ms"] - start,
                        "end_ms": offset + max(word["end_ms"] for word in chunk) - start,
                        "words": [
                            {
                                "word_id": word["id"],
                                "text": word["text"].strip(),
                                "start_ms": offset + word["start_ms"] - start,
                                "end_ms": offset + word["end_ms"] - start,
                            }
                            for word in chunk
                        ],
                        "emphasis_word_id": focused,
                    },
                )
            )
        for priority, edit in enumerate(clip_edits, 1):
            left, right = max(start, edit["source_start_ms"]), min(end, edit["source_end_ms"])
            if left >= right:
                continue
            timed_words = []
            for word in [] if edit["deleted"] else edit["words"]:
                aligned = index.get(word["word_id"])
                word_start = max(left, aligned["start_ms"]) if aligned else right
                word_end = min(right, aligned["end_ms"]) if aligned else left
                if aligned and word_start >= word_end:
                    continue
                timed_words.append(
                    {
                        **word,
                        "start_ms": offset + word_start - start if word_start < word_end else None,
                        "end_ms": offset + word_end - start if word_start < word_end else None,
                    }
                )
            if not timed_words and not edit["deleted"]:
                continue
            candidates.append(
                (
                    priority,
                    {
                        "id": edit["id"],
                        "clip_id": clip["id"],
                        "start_ms": offset + left - start,
                        "end_ms": offset + right - start,
                        "words": timed_words,
                        "emphasis_word_id": edit["emphasis_word_id"],
                    },
                )
            )
        captions.extend(_caption_lane(candidates, offset - start))
        offset += end - start
    canonical["duration_ms"] = offset
    canonical["target_met"] = offset <= canonical["target_duration_ms"]
    canonical["captions"] = sorted(
        captions, key=lambda caption: (caption["start_ms"], caption["end_ms"], caption["id"])
    )
    return Plan.model_validate(canonical).model_dump()


def compile_draft(
    words: list[dict],
    editorial: dict,
    sources: dict[str, dict],
    target_duration_ms: int = 120000,
    dead_space_enabled: bool = True,
    silence_maps: dict[str, list[dict]] | None = None,
    reserved_duration_ms: int = 0,
) -> dict:
    editorial = _record(editorial)
    if reserved_duration_ms < 0:
        raise EditError("Reserved hook duration must be nonnegative.")
    body_target_ms = max(0, target_duration_ms - reserved_duration_ms)
    index = _words(words, sources)
    take_index, lines = {}, {}
    for item in editorial["takes"]:
        take = _record(item)
        if take["id"] in take_index:
            raise EditError(f"Take {take['id']} appears more than once.")
        take_index[take["id"]] = take
        _take_words(take, index)
        if take["role"] == "body":
            lines.setdefault(take["line_id"], []).append(take)
    chosen, dropped = [], []
    for line_id, candidates in lines.items():
        selected = [take for take in candidates if take.get("selected", False)]
        best = max(selected or candidates, key=lambda take: (take.get("score", 0), take["id"]))
        if not selected:
            dropped.append(
                {
                    "line_id": line_id,
                    "text": " ".join(index[w]["text"] for w in best["word_ids"]),
                    "reason": best.get("reason", "Editorial removal"),
                }
            )
            continue
        clips = clips_for_take(best, words, sources, silence_maps, dead_space_enabled)
        chosen.append(
            {
                "take": best,
                "clips": clips,
                "duration": sum(c["source_end_ms"] - c["source_start_ms"] for c in clips),
                "line_start_ms": min(
                    index[w]["start_ms"] for candidate in candidates for w in candidate["word_ids"]
                ),
            }
        )
    chosen.sort(
        key=lambda item: (
            item["clips"][0]["source_id"],
            item["line_start_ms"],
            item["take"]["id"],
        )
    )
    duration = sum(item["duration"] for item in chosen)
    for item in sorted(
        chosen, key=lambda item: (item["take"].get("score", 0), -item["duration"], item["take"]["id"])
    ):
        if duration <= body_target_ms or len(chosen) <= 1:
            break
        remainder = duration - item["duration"]
        if abs(remainder - body_target_ms) > abs(duration - body_target_ms) and remainder < body_target_ms:
            continue
        chosen.remove(item)
        duration = remainder
        take = item["take"]
        dropped.append(
            {
                "line_id": take["line_id"],
                "text": " ".join(index[w]["text"] for w in take["word_ids"]),
                "reason": "Removed as a whole line to approach the target duration.",
            }
        )
    plan = Plan(target_duration_ms=target_duration_ms).model_dump()
    plan["clips"] = [clip for item in chosen for clip in item["clips"]]
    plan["dropped_lines"] = dropped
    plan["dead_space"]["enabled"] = dead_space_enabled
    return canonicalize_plan(plan, words, sources, take_index)


def combination_overlay(plan: dict, visual_title: dict | None, combination: dict) -> dict | None:
    """Resolve the title used by both opening validation and rendering."""
    if not combination.get("use_title", True):
        return None
    if combination.get("overlay") is not None:
        return deepcopy(combination["overlay"])
    if plan.get("selected_hook_id") == combination.get("hook_id") and plan.get(
        "selected_visual_title_id"
    ) == combination.get("visual_title_id"):
        return deepcopy(plan.get("hook_overlay"))
    if visual_title is not None:
        if visual_title.get("missing_slots"):
            raise EditError("Fill the visual title's missing slots or provide a manual title.")
        return {
            "text": visual_title["text"],
            "position": {"x": 0.44, "y": 0.24},
            "hold_ms": 4000,
            "fade_ms": 300,
        }
    return None


def assemble_combination(
    plan: dict,
    hook: dict | None,
    visual_title: dict | None,
    combination: dict,
    words: list[dict],
    sources: dict[str, dict],
    takes: dict[str, dict] | None = None,
) -> dict:
    assembled = deepcopy(_record(plan))
    combination = _record(combination)
    hook = None if hook is None else _record(hook)
    visual_title = None if visual_title is None else _record(visual_title)
    body = [clip for clip in assembled["clips"] if clip["role"] == "body"]
    hook_id = combination.get("hook_id")
    title_id = combination.get("visual_title_id")
    if hook_id is None:
        if title_id is not None:
            raise EditError("A visual title requires a selected hook.")
        hook_clips = []
    else:
        if hook is None or hook.get("id") != hook_id or not hook.get("take_id"):
            raise EditError("The selected hook needs a recorded take.")
        existing = [clip for clip in assembled["clips"] if clip["role"] == "hook"]
        if (
            assembled.get("selected_hook_id") == hook_id
            and existing
            and all(c["take_id"] == hook["take_id"] for c in existing)
        ):
            hook_clips = existing
        elif hook.get("clips"):
            hook_clips = deepcopy(hook["clips"])
        elif takes and hook["take_id"] in takes:
            hook_clips = clips_for_take(
                takes[hook["take_id"]], words, sources, dead_space_enabled=assembled["dead_space"]["enabled"]
            )
        else:
            raise EditError("The selected hook needs available clip ranges.")
    if title_id is not None and (visual_title is None or visual_title.get("id") != title_id):
        raise EditError("The visual title must match the project selection.")
    overlay = combination_overlay(assembled, visual_title, combination)
    assembled.update(
        clips=hook_clips + body,
        selected_hook_id=hook_id,
        selected_visual_title_id=title_id,
        hook_overlay=overlay,
    )
    return canonicalize_plan(assembled, words, sources, takes)
