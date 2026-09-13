from copy import deepcopy
from itertools import pairwise

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


def assert_caption_lane(captions):
    for previous, following in pairwise(captions):
        assert previous["end_ms"] <= following["start_ms"]
    for caption in captions:
        assert caption["start_ms"] < caption["end_ms"]
        for token in caption["words"]:
            if token["start_ms"] is None:
                assert token["end_ms"] is None
            else:
                assert caption["start_ms"] <= token["start_ms"] < token["end_ms"] <= caption["end_ms"]


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
    assert [[(w["start_ms"], w["end_ms"]) for w in c["words"]] for c in result["captions"]] == [
        [(0, 500), (700, 800)],
        [(800, 1000), (1100, 1300)],
        [(1600, 1800), (1900, 2100)],
    ]
    assert len({c["id"] for c in result["captions"]}) == 3
    assert_caption_lane(result["captions"])


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
    assert result["captions"][0]["words"] == [
        {"word_id": "w1", "text": "word1", "start_ms": 100, "end_ms": 300}
    ]
    manual = next(c for c in result["captions"] if c["id"] == "manual")
    assert manual["words"] == [{"word_id": None, "text": "Creator text", "start_ms": None, "end_ms": None}]
    result["clips"].reverse()
    second = canonicalize_plan(result, words, source)
    assert next(c for c in second["captions"] if c["id"] == "manual")["start_ms"] == 0
    second["clips"] = [second["clips"][1]]
    third = canonicalize_plan(second, words, source)
    assert third["caption_edits"] == result["caption_edits"]
    assert all(c["id"] not in {"manual", "addition"} for c in third["captions"])


def test_caption_chunks_keep_three_or_four_words_across_punctuation_and_preserve_emphasis():
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
    assert [len(c["words"]) for c in result["captions"]] == [4, 3]
    assert result["captions"][0]["emphasis_word_id"] == "w4"
    assert all(c["emphasis_word_id"] in {w["word_id"] for w in c["words"]} for c in result["captions"])


@pytest.mark.parametrize(
    "length,expected_sizes",
    [
        (1, [1]),
        (2, [2]),
        (3, [3]),
        (4, [4]),
        (5, [3, 2]),
        (6, [3, 3]),
        (7, [4, 3]),
        (8, [4, 4]),
        (9, [3, 3, 3]),
        (10, [4, 3, 3]),
        (11, [4, 4, 3]),
        (12, [4, 4, 4]),
        (13, [4, 3, 3, 3]),
        (14, [4, 4, 3, 3]),
    ],
)
def test_continuous_speech_balances_caption_lengths_and_preserves_word_timing(length, expected_sizes):
    words = [word(i, 1000 + i * 700, 1600 + i * 700, text=f"word{i}.") for i in range(length)]
    end = words[-1]["end_ms"] + 100
    result = canonicalize_plan(
        {**Plan().model_dump(), "clips": [clip(start=900, end=end)]},
        words,
        {"body": {"duration_ms": end}},
    )
    assert [len(c["words"]) for c in result["captions"]] == expected_sizes
    assert [w for c in result["captions"] for w in c["words"]] == [
        {"word_id": w["id"], "text": w["text"], "start_ms": w["start_ms"] - 900, "end_ms": w["end_ms"] - 900}
        for w in words
    ]
    assert_caption_lane(result["captions"])


@pytest.mark.parametrize("gap,expected_sizes", [(0, [3, 3]), (350, [3, 3]), (700, [3, 3]), (701, [2, 4])])
def test_caption_runs_split_at_source_pauses_over_700ms(gap, expected_sizes):
    words = [word(0, 0, 200), word(1, 200, 400)] + [
        word(i + 2, 400 + gap + i * 200, 600 + gap + i * 200) for i in range(4)
    ]
    end = words[-1]["end_ms"]
    result = canonicalize_plan(
        {**Plan().model_dump(), "clips": [clip(start=0, end=end)]}, words, {"body": {"duration_ms": end}}
    )
    assert [len(c["words"]) for c in result["captions"]] == expected_sizes
    if gap > 700:
        assert result["captions"][0]["end_ms"] == 400
        assert result["captions"][1]["start_ms"] == 400 + gap
    assert [w["word_id"] for c in result["captions"] for w in c["words"]] == [w["id"] for w in words]
    assert_caption_lane(result["captions"])


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
    assert [(w["start_ms"], w["end_ms"]) for w in body_caption["words"]] == [(800, 950), (1050, 1250)]
    hook_caption = result["captions"][0]
    assert [(w["start_ms"], w["end_ms"]) for w in hook_caption["words"]] == [(150, 650)]
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
    assert [(w["start_ms"], w["end_ms"]) for w in again["captions"][0]["words"]] == [(50, 550)]
    shifted_body = next(c for c in again["captions"] if c["clip_id"] == "c1")
    assert [(w["start_ms"], w["end_ms"]) for w in shifted_body["words"]] == [(700, 850), (950, 1150)]
    assert [(w["start_ms"], w["end_ms"]) for w in plan["captions"][0]["words"]] == [(0, 150), (250, 450)]
    assert_caption_lane(again["captions"])


def test_manual_caption_owns_its_range_and_preserves_spoken_tail_after_hook():
    words = [
        word(1, 2160, 2420, text="the"),
        word(2, 2420, 2660, text="long"),
        word(3, 2660, 2920, text="pauses"),
        word(4, 2920, 3280, text="between"),
        word(5, 3280, 3540, text="your"),
        word(6, 3540, 3960, text="ideas"),
        word(7, 0, 2460, source="hooks", text="Hook."),
    ]
    plan = Plan().model_dump()
    plan["clips"] = [clip("body_clip", start=2190, end=4110)]
    plan["caption_edits"] = [
        {
            "id": "manual_smoke",
            "clip_id": "body_clip",
            "source_start_ms": 2190,
            "source_end_ms": 3190,
            "replaces_word_ids": [],
            "words": [{"word_id": None, "text": "Synthetic"}, {"word_id": None, "text": "review"}],
        }
    ]
    sources = {"body": {"duration_ms": 5000}, "hooks": {"duration_ms": 3000}}
    body = canonicalize_plan(plan, words, sources)
    assert body["caption_style"]["preset"] == "spoken_outline"
    assert [(c["start_ms"], c["end_ms"], [w["text"] for w in c["words"]]) for c in body["captions"]] == [
        (0, 1000, ["Synthetic", "review"]),
        (1000, 1770, ["between", "your", "ideas"]),
    ]
    assert body["captions"][1]["words"] == [
        {"word_id": "w4", "text": "between", "start_ms": 1000, "end_ms": 1090},
        {"word_id": "w5", "text": "your", "start_ms": 1090, "end_ms": 1350},
        {"word_id": "w6", "text": "ideas", "start_ms": 1350, "end_ms": 1770},
    ]
    hook = {
        "id": "hook1",
        "take_id": "hooktake",
        "clips": [clip("hook_clip", source="hooks", start=0, end=2610, role="hook", take_id="hooktake")],
    }
    assembled = assemble_combination(
        body, hook, None, {"id": "combo1", "hook_id": "hook1", "use_title": False}, words, sources
    )
    body_captions = [c for c in assembled["captions"] if c["clip_id"] == "body_clip"]
    assert [(c["start_ms"], c["end_ms"]) for c in body_captions] == [(2610, 3610), (3610, 4380)]
    assert body_captions[1]["words"] == [
        {"word_id": "w4", "text": "between", "start_ms": 3610, "end_ms": 3700},
        {"word_id": "w5", "text": "your", "start_ms": 3700, "end_ms": 3960},
        {"word_id": "w6", "text": "ideas", "start_ms": 3960, "end_ms": 4380},
    ]
    assert all(w["start_ms"] is None and w["end_ms"] is None for w in body_captions[0]["words"])
    assert_caption_lane(assembled["captions"])


def test_later_manual_caption_wins_and_splits_earlier_manual_and_automatic_cues():
    words = [
        word(1, 0, 300, text="Before."),
        word(2, 300, 900, text="Middle."),
        word(3, 900, 1200, text="After."),
    ]
    plan = Plan().model_dump()
    plan["clips"] = [clip(start=0, end=1200)]
    plan["caption_edits"] = [
        {
            "id": "wide",
            "clip_id": "c1",
            "source_start_ms": 200,
            "source_end_ms": 1000,
            "words": [{"word_id": None, "text": "Wide edit"}],
        },
        {
            "id": "focused",
            "clip_id": "c1",
            "source_start_ms": 400,
            "source_end_ms": 600,
            "words": [{"word_id": None, "text": "Focused edit"}],
        },
    ]
    result = canonicalize_plan(plan, words, {"body": {"duration_ms": 2000}})
    assert [(c["start_ms"], c["end_ms"], [w["text"] for w in c["words"]]) for c in result["captions"]] == [
        (0, 200, ["Before."]),
        (200, 400, ["Wide edit"]),
        (400, 600, ["Focused edit"]),
        (600, 1000, ["Wide edit"]),
        (1000, 1200, ["After."]),
    ]
    assert len({c["id"] for c in result["captions"]}) == len(result["captions"])
    assert_caption_lane(result["captions"])
    plan["caption_edits"].reverse()
    reversed_result = canonicalize_plan(plan, words, {"body": {"duration_ms": 2000}})
    assert [
        (c["start_ms"], c["end_ms"], [w["text"] for w in c["words"]]) for c in reversed_result["captions"]
    ] == [
        (0, 200, ["Before."]),
        (200, 1000, ["Wide edit"]),
        (1000, 1200, ["After."]),
    ]


def test_source_linked_manual_words_clamp_to_edit_and_clip_timing():
    words = [word(1, 1000, 1400), word(2, 1400, 1800), word(3, 1900, 2000)]
    plan = Plan().model_dump()
    plan["clips"] = [clip("lead", start=0, end=100), clip("manual_clip", start=1150, end=1700)]
    plan["caption_edits"] = [
        {
            "id": "linked",
            "clip_id": "manual_clip",
            "source_start_ms": 1100,
            "source_end_ms": 1600,
            "replaces_word_ids": ["w1", "w2", "w3"],
            "words": [
                {"word_id": "w1", "text": "Corrected"},
                {"word_id": "w2", "text": "speech"},
                {"word_id": "w3", "text": "Outside"},
                {"word_id": None, "text": "annotation"},
            ],
        }
    ]
    result = canonicalize_plan(plan, words, {"body": {"duration_ms": 3000}})
    manual = next(c for c in result["captions"] if c["id"] == "linked")
    assert (manual["start_ms"], manual["end_ms"]) == (100, 550)
    assert manual["words"] == [
        {"word_id": "w1", "text": "Corrected", "start_ms": 100, "end_ms": 350},
        {"word_id": "w2", "text": "speech", "start_ms": 350, "end_ms": 550},
        {"word_id": None, "text": "annotation", "start_ms": None, "end_ms": None},
    ]
    assert_caption_lane(result["captions"])


def test_manual_conflict_clips_linked_words_to_their_winning_intervals():
    words = [word(1, 0, 500), word(2, 500, 1000)]
    plan = Plan().model_dump()
    plan["clips"] = [clip(start=0, end=1000)]
    plan["caption_edits"] = [
        {
            "id": "linked",
            "clip_id": "c1",
            "source_start_ms": 0,
            "source_end_ms": 1000,
            "replaces_word_ids": ["w1", "w2"],
            "words": [{"word_id": "w1", "text": "One"}, {"word_id": "w2", "text": "Two"}],
        },
        {
            "id": "insertion",
            "clip_id": "c1",
            "source_start_ms": 400,
            "source_end_ms": 600,
            "words": [{"word_id": None, "text": "Insert"}],
        },
    ]
    sources = {"body": {"duration_ms": 2000}}
    result = canonicalize_plan(plan, words, sources)
    assert [(c["start_ms"], c["end_ms"]) for c in result["captions"]] == [(0, 400), (400, 600), (600, 1000)]
    assert [c["words"] for c in result["captions"]] == [
        [{"word_id": "w1", "text": "One", "start_ms": 0, "end_ms": 400}],
        [{"word_id": None, "text": "Insert", "start_ms": None, "end_ms": None}],
        [{"word_id": "w2", "text": "Two", "start_ms": 600, "end_ms": 1000}],
    ]
    assert canonicalize_plan(result, words, sources) == result
    assert_caption_lane(result["captions"])


@pytest.mark.parametrize(
    "deletion_start,deletion_end,expected_ranges",
    [(0, 1000, []), (400, 600, [(0, 400), (600, 1000)])],
)
def test_later_deletion_owns_full_or_partial_manual_caption_range(
    deletion_start, deletion_end, expected_ranges
):
    plan = Plan().model_dump()
    plan["clips"] = [clip(start=0, end=1000)]
    plan["caption_edits"] = [
        {
            "id": "manual",
            "clip_id": "c1",
            "source_start_ms": 0,
            "source_end_ms": 1000,
            "words": [{"word_id": None, "text": "Creator text"}],
        },
        {
            "id": "delete_manual",
            "clip_id": "c1",
            "source_start_ms": deletion_start,
            "source_end_ms": deletion_end,
            "deleted": True,
            "words": [],
        },
    ]
    sources = {"body": {"duration_ms": 2000}}
    words = [word(1, 0, 1000)]
    result = canonicalize_plan(plan, words, sources)
    assert [(c["start_ms"], c["end_ms"]) for c in result["captions"]] == expected_ranges
    assert all(c["words"][0]["text"] == "Creator text" for c in result["captions"])
    assert canonicalize_plan(result, words, sources) == result
    assert_caption_lane(result["captions"])


def test_manual_caption_and_deletion_anchors_survive_trim_and_reorder():
    plan = Plan().model_dump()
    plan["clips"] = [clip("lead", start=1100, end=1300), clip(start=300, end=800)]
    plan["caption_edits"] = [
        {
            "id": "manual",
            "clip_id": "c1",
            "source_start_ms": 0,
            "source_end_ms": 1000,
            "words": [{"word_id": None, "text": "Creator text"}],
        },
        {
            "id": "delete_middle",
            "clip_id": "c1",
            "source_start_ms": 400,
            "source_end_ms": 600,
            "deleted": True,
            "words": [],
        },
    ]
    words, sources = [word(1, 0, 1000)], {"body": {"duration_ms": 2000}}
    full_range = deepcopy(plan)
    full_range["clips"][1].update(source_start_ms=0, source_end_ms=1000)
    before_reorder = canonicalize_plan(full_range, words, sources)
    trimmed = canonicalize_plan(plan, words, sources)
    assert [(c["start_ms"], c["end_ms"]) for c in trimmed["captions"]] == [(200, 300), (500, 700)]
    saved_edits = deepcopy(trimmed["caption_edits"])
    trimmed["clips"][1].update(source_start_ms=450, source_end_ms=550)
    within_deletion = canonicalize_plan(trimmed, words, sources)
    assert within_deletion["captions"] == []
    within_deletion["clips"].reverse()
    within_deletion["clips"][0].update(source_start_ms=0, source_end_ms=1000)
    expanded = canonicalize_plan(within_deletion, words, sources)
    assert [(c["start_ms"], c["end_ms"]) for c in expanded["captions"]] == [(0, 400), (600, 1000)]
    assert [c["id"] for c in expanded["captions"]] == [c["id"] for c in before_reorder["captions"]]
    assert expanded["caption_edits"] == saved_edits
    assert_caption_lane(expanded["captions"])


def test_overlapping_asr_chunks_have_disjoint_cues_and_contained_word_timings():
    words = [
        word(1, 0, 800, text="First."),
        word(2, 400, 600, text="Second."),
        word(3, 700, 1200, text="Third."),
        word(4, 1000, 1500, text="Fourth."),
        word(5, 1500, 1600, text="Fifth."),
        word(6, 1600, 1700, text="Sixth."),
    ]
    result = canonicalize_plan(
        {**Plan().model_dump(), "clips": [clip(start=0, end=1800)]}, words, {"body": {"duration_ms": 2000}}
    )
    assert [(c["start_ms"], c["end_ms"]) for c in result["captions"]] == [(0, 1000), (1000, 1700)]
    assert [len(c["words"]) for c in result["captions"]] == [3, 3]
    assert_caption_lane(result["captions"])


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
