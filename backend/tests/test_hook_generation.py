import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from editmaxxing.config import Settings
from editmaxxing.hook_policy import example_catalogue, examples_for_ids, load_examples, policy_version
from editmaxxing.models import BodyEditorial, HookRecommendations
from editmaxxing.provider import (
    FixtureProvider,
    OpenAIProvider,
    ProviderError,
    complete_editorial,
    fixture_words,
    validate_editorial,
)

CASES = json.loads((Path(__file__).parent / "fixtures" / "hook_eval_cases.json").read_text())


def test_example_library_and_evaluation_corpus_are_separate():
    library = load_examples()
    assert len(library) == 20
    for case in CASES:
        assert case["transcript"] not in [e["body_excerpt"] for e in library]
        assert case["review_rules"]
    assert all(set(e) == {"id", "technique", "subjects"} for e in example_catalogue())


@pytest.mark.parametrize("ids", [[], ["notes_return"], ["notes_return"] * 2, ["notes_return", "invented"]])
def test_example_selection_requires_two_distinct_library_ids(ids):
    with pytest.raises(ValueError, match="two distinct"):
        examples_for_ids(ids)


def test_generation_receives_two_examples_and_only_selected_body_words():
    words = fixture_words("body")
    body = FixtureProvider().analyze_body(words)
    body.takes[-1].selected = False
    excluded = set(body.takes[-1].word_ids)
    selected = [w for w in words if w.id not in excluded]
    generated = FixtureProvider().generate_hooks(selected, [], body.example_ids)
    client = Mock()
    client.responses.parse.side_effect = [
        SimpleNamespace(status="completed", output_parsed=body),
        SimpleNamespace(status="completed", output_parsed=generated),
    ]
    result = OpenAIProvider(Settings(), client=client).analyze(words, [])
    first, second = [call.kwargs for call in client.responses.parse.call_args_list]
    assert first["text_format"] is BodyEditorial
    assert second["text_format"] is HookRecommendations
    first_payload = json.loads(first["input"][0]["content"][0]["text"])
    payload = json.loads(second["input"][0]["content"][0]["text"])
    assert "examples" not in first_payload
    assert len(first_payload["example_catalogue"]) == 20
    assert "example_catalogue" not in payload
    assert len(payload["examples"]) == 2
    assert {w["id"] for w in payload["words"]} == {w.id for w in selected}
    assert result.example_ids == [e["id"] for e in payload["examples"]]
    assert result.hook_policy_version == payload["policy_version"] == policy_version()


def test_generation_uses_only_words_retained_by_duration_selection():
    words = fixture_words("body")
    provider = FixtureProvider()
    body = provider.analyze_body(words)
    retained = set(body.takes[0].word_ids)
    original = provider.generate_hooks
    received = []

    def generate(selected, templates, example_ids):
        received.extend(w.id for w in selected)
        return original(selected, templates, example_ids)

    provider.generate_hooks = generate
    complete_editorial(provider, body, words, [], retained)
    assert set(received) == retained


def test_invalid_body_stops_before_hook_generation():
    words = fixture_words("body")
    body = FixtureProvider().analyze_body(words)
    body.takes[0].word_ids = ["invented"]
    client = Mock()
    client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed=body)
    with pytest.raises(ProviderError, match="unavailable"):
        OpenAIProvider(Settings(), client=client).analyze(words, [])
    assert client.responses.parse.call_count == 1


def test_evidence_accepts_separate_spans_and_requires_selected_payoff():
    words = fixture_words("body")
    editorial = FixtureProvider().analyze(words, [])
    hook = editorial.hooks[0]
    hook.evidence_spans = [editorial.takes[0].word_ids, editorial.takes[-1].word_ids]
    hook.question_opened = "What does the last passage explain?"
    hook.payoff_word_ids = editorial.takes[-1].word_ids
    validate_editorial(editorial, words, [])
    editorial.takes[-1].selected = False
    with pytest.raises(ProviderError, match="unavailable"):
        validate_editorial(editorial, words, [])


@pytest.mark.parametrize("count,duration,valid", [(11, 2999, True), (12, 2999, False), (11, 3000, False)])
def test_spoken_word_and_duration_boundaries(count, duration, valid):
    words = fixture_words("body")
    editorial = FixtureProvider().analyze(words, [])
    editorial.hooks[0].proposed_text = " ".join(["word"] * count)
    editorial.hooks[0].estimated_duration_ms = duration
    if valid:
        validate_editorial(editorial, words, [])
    else:
        with pytest.raises(ProviderError, match="three seconds"):
            validate_editorial(editorial, words, [])


@pytest.mark.parametrize("group", ["hooks", "titles"])
def test_generated_exclamations_are_rejected(group):
    words = fixture_words("body")
    editorial = FixtureProvider().analyze(words, [])
    getattr(editorial, group)[0].proposed_text += "!"
    with pytest.raises(ProviderError, match="punctuation"):
        validate_editorial(editorial, words, [])


def test_an_open_question_requires_a_payoff():
    words = fixture_words("body")
    editorial = FixtureProvider().analyze(words, [])
    editorial.hooks[0].question_opened = "Which setting caused the failure?"
    with pytest.raises(ProviderError, match="answer passage"):
        validate_editorial(editorial, words, [])


def test_example_edits_change_policy_identity(monkeypatch):
    before = policy_version()
    changed = copy.deepcopy(load_examples())
    changed[0]["rationale"] = "A revised explanation of the example."
    monkeypatch.setattr("editmaxxing.hook_policy.load_examples", lambda: changed)
    assert policy_version() != before
