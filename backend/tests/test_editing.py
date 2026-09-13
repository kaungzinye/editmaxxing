from copy import deepcopy

import pytest
from editmaxxing.editing import (
    EditError,
    assemble_combination,
    canonicalize_plan,
    clips_for_take,
    compile_draft,
)
from editmaxxing.models import Plan


def word(number, start, end, source="body", text=None):
    return {
        "id": f"w{number}",
        "source_id": source,
        "text": text or f"word{number}",
        "start_ms": start,
        "end_ms": end,
    }


def take(id="take1", ids=None, line="line1", role="body", score=80, selected=True):
    return {
        "id": id,
        "word_ids": ids or ["w1", "w2"],
        "line_id": line,
        "role": role,
        "score": score,
        "selected": selected,
        "reason": "Complete sentence",
        "emphasis_word_ids": [],
    }


def clip(id="c1", source="body", start=900, end=3100, role="body", take_id="take1", line="line1"):
    return {
        "id": id,
        "source_id": source,
        "line_id": line,
        "take_id": take_id,
        "role": role,
        "source_start_ms": start,
        "source_end_ms": end,
        "selection_reason": "Creator selection",
    }


def test_silence_split_retains_250ms_and_pads_clear_boundaries():
    words = [word(0, 100, 800), word(1, 1000, 1300), word(2, 2600, 3000), word(3, 3200, 3400)]
    sources = {"body": {"duration_ms": 4000}}
    silence = {
        "body": [
            {"start_ms": 800, "end_ms": 1000},
            {"start_ms": 1300, "end_ms": 2600},
            {"start_ms": 3000, "end_ms": 3200},
        ]
    }
    clips = clips_for_take(take(), words, sources, silence)
    assert [(c["source_start_ms"], c["source_end_ms"]) for c in clips] == [(850, 1425), (2475, 3150)]
    full = clips_for_take(take(), words, sources, silence, False)
    assert [(c["source_start_ms"], c["source_end_ms"]) for c in full] == [(850, 3150)]


def test_padding_clamps_to_neighbor_speech_and_long_word_never_splits():
    words = [word(0, 100, 960), word(1, 1000, 2700), word(2, 2750, 3000), word(3, 3040, 3400)]
    result = clips_for_take(take(), words, {"body": {"duration_ms": 4000}})
    assert len(result) == 1
    assert (result[0]["source_start_ms"], result[0]["source_end_ms"]) == (960, 3040)


def test_dead_space_does_not_remove_unselected_interior_speech():
    words = [word(1, 1000, 1300), word(3, 1700, 2400), word(2, 2600, 3000)]
    result = clips_for_take(take(), words, {"body": {"duration_ms": 4000}})
    assert len(result) == 1


def test_whole_line_ranking_keeps_source_order_and_restorable_text():
    words = [word(1, 100, 55000), word(2, 60000, 105000), word(3, 110000, 165000)]
    takes = [
        take("t1", ["w1"], "l1", score=100),
        take("t2", ["w2"], "l2", score=5),
        take("t3", ["w3"], "l3", score=90),
    ]
    plan = compile_draft(words, {"takes": takes}, {"body": {"duration_ms": 170000}}, 120000, False)
    assert [c["line_id"] for c in plan["clips"]] == ["l1", "l3"]
    assert [line["line_id"] for line in plan["dropped_lines"]] == ["l2"]
    assert plan["target_met"]
    assert plan["dropped_lines"][0]["text"] == "word2"


def test_selected_late_retake_keeps_its_intended_line_order():
    words = [word(1, 1000, 1500), word(2, 5000, 5500), word(3, 9000, 9500)]
    takes = [
        take("early", ["w1"], "opening", selected=False),
        take("middle", ["w2"], "body"),
        take("retake", ["w3"], "opening"),
    ]
    plan = compile_draft(words, {"takes": takes}, {"body": {"duration_ms": 10000}})
    assert [c["take_id"] for c in plan["clips"]] == ["retake", "middle"]


def test_captions_map_half_open_ranges_and_occurrence_offsets():
    words = [
        word(1, 500, 1200, text="First"),
        word(2, 1300, 1500, text="sentence."),
        word(3, 1800, 2300, text="Second"),
        word(4, 2500, 2800, text="idea."),
    ]
    source = {"body": {"duration_ms": 4000}}
    plan = Plan().model_dump()
    plan["clips"] = [
        clip("b", start=1800, end=2600),
        clip("a", start=1000, end=1800),
        clip("repeat", start=1000, end=1800),
    ]
    result = canonicalize_plan(plan, words, source)
    assert result["duration_ms"] == 2400
    assert [(c["clip_id"], c["start_ms"], c["end_ms"]) for c in result["captions"]] == [
        ("b", 0, 800),
        ("a", 800, 1300),
        ("repeat", 1600, 2100),
    ]
    assert [w["text"] for w in result["captions"][1]["words"]] == ["First", "sentence."]
    assert len({c["id"] for c in result["captions"]}) == 3


def test_manual_override_addition_and_deletion_survive_reorder_trim_and_removal():
    words = [word(1, 1000, 1200), word(2, 1300, 1500)]
    plan = Plan().model_dump()
    plan["clips"] = [clip("repeat", start=900, end=1800), clip("edited", start=1100, end=1700)]
    plan["caption_edits"] = [
        {
            "id": "manual",
            "clip_id": "edited",
            "source_start_ms": 1000,
            "source_end_ms": 1450,
            "words": [{"word_id": None, "text": "Creator text"}],
            "replaces_word_ids": ["w1", "w2"],
        },
        {
            "id": "addition",
            "clip_id": "edited",
            "source_start_ms": 1500,
            "source_end_ms": 2000,
            "words": [{"word_id": None, "text": "Extra"}],
        },
        {
            "id": "deletion",
            "clip_id": "repeat",
            "source_start_ms": 1250,
            "source_end_ms": 1500,
            "deleted": True,
        },
    ]
    source = {"body": {"duration_ms": 4000}}
    result = canonicalize_plan(plan, words, source)
    assert [
        (c["id"], c["start_ms"], c["end_ms"]) for c in result["captions"] if c["id"] in {"manual", "addition"}
    ] == [("manual", 900, 1250), ("addition", 1300, 1500)]
    assert result["captions"][0]["words"] == [{"word_id": "w1", "text": "word1"}]
    result["clips"].reverse()
    second = canonicalize_plan(result, words, source)
    assert next(c for c in second["captions"] if c["id"] == "manual")["start_ms"] == 0
    second["clips"] = [second["clips"][1]]
    third = canonicalize_plan(second, words, source)
    assert third["caption_edits"] == result["caption_edits"]
    assert all(c["id"] not in {"manual", "addition"} for c in third["captions"])


def test_caption_chunks_follow_punctuation_pauses_and_emphasis():
    words = [
        word(i, 1000 + i * 200, 1160 + i * 200, text="end." if i == 2 else f"word{i}") for i in range(1, 8)
    ]
    selection = take(ids=[w["id"] for w in words])
    selection["emphasis_word_ids"] = ["w4"]
    result = canonicalize_plan(
        {**Plan().model_dump(), "clips": [clip(start=1000, end=3000)]},
        words,
        {"body": {"duration_ms": 4000}},
        {"take1": selection},
    )
    assert [len(c["words"]) for c in result["captions"]] == [2, 4, 1]
    assert result["captions"][1]["emphasis_word_id"] == "w4"
    assert all(c["emphasis_word_id"] in {w["word_id"] for w in c["words"]} for c in result["captions"])


def test_hook_prepend_preserves_saved_body_and_recalculates_caption_offsets():
    words = [word(1, 1000, 1200), word(2, 1300, 1500), word(3, 6000, 6500, source="hooks", text="Hook.")]
    sources = {"body": {"duration_ms": 4000}, "hooks": {"duration_ms": 8000}}
    takes = {"take1": take(), "hooktake": take("hooktake", ["w3"], "hookline", "hook")}
    plan = canonicalize_plan(
        {**Plan().model_dump(), "revision": 7, "clips": [clip(start=1050, end=1700)]}, words, sources, takes
    )
    title = {"id": "title1", "text": "Watch this", "missing_slots": []}
    hook = {"id": "hook1", "take_id": "hooktake", "visual_titles": [title]}
    result = assemble_combination(
        plan,
        hook,
        title,
        {"id": "combo1", "hook_id": "hook1", "visual_title_id": "title1"},
        words,
        sources,
        takes,
    )
    assert result["clips"][1:] == plan["clips"]
    assert result["clips"][0]["role"] == "hook"
    assert result["revision"] == 7
    body_caption = next(c for c in result["captions"] if c["clip_id"] == "c1")
    assert body_caption["start_ms"] == 800
    assert result["hook_overlay"]["text"] == "Watch this"
    result["clips"][0]["source_start_ms"] += 100
    result["hook_overlay"] = None
    again = assemble_combination(
        result,
        hook,
        title,
        {"id": "combo1", "hook_id": "hook1", "visual_title_id": "title1"},
        words,
        sources,
        takes,
    )
    assert again["clips"] == result["clips"]
    assert again["hook_overlay"] is None


def test_incomplete_title_requires_creator_text_and_title_belongs_to_hook():
    words = [word(1, 1000, 1500)]
    sources = {"body": {"duration_ms": 4000}}
    takes = {"t": take("t", ["w1"], role="hook")}
    title = {"id": "title", "text": "Try {tool}", "missing_slots": ["tool"]}
    hook = {"id": "h", "take_id": "t", "visual_titles": [title]}
    combination = {"id": "c", "hook_id": "h", "visual_title_id": "title"}
    with pytest.raises(EditError, match="missing slots"):
        assemble_combination(Plan().model_dump(), hook, title, combination, words, sources, takes)
    combination["overlay"] = {
        "text": "My title",
        "position": {"x": 0.5, "y": 0.2},
        "hold_ms": 1500,
        "fade_ms": 300,
    }
    assert (
        assemble_combination(Plan().model_dump(), hook, title, combination, words, sources, takes)[
            "hook_overlay"
        ]["text"]
        == "My title"
    )
    combination["visual_title_id"] = "foreign"
    with pytest.raises(EditError, match="belong"):
        assemble_combination(Plan().model_dump(), hook, title, combination, words, sources, takes)


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda p: p["clips"].append(deepcopy(p["clips"][0])), "more than once"),
        (lambda p: p["clips"][0].update(source_end_ms=5000), "source range"),
        (lambda p: p["clips"][0].update(line_id="foreign"), "inconsistent"),
        (lambda p: p["clips"][0].update(role="hook"), "inconsistent"),
    ],
)
def test_invalid_references_reject(mutation, match):
    words = [word(1, 1000, 1200), word(2, 1300, 1500)]
    plan = {**Plan().model_dump(), "clips": [clip()]}
    mutation(plan)
    with pytest.raises(EditError, match=match):
        canonicalize_plan(plan, words, {"body": {"duration_ms": 4000}}, {"take1": take()})
