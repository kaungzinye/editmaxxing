from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from editmaxxing.config import Settings
from editmaxxing.models import Editorial, HookScript, Match, Matches, SlotValue, Template, Timing, TitleChoice
from editmaxxing.provider import (
    FixtureProvider,
    OpenAIProvider,
    ProviderError,
    assemble_title,
    fixture_words,
    get_provider,
    validate_editorial,
    validate_matches,
    validate_templates,
)
from openai import AuthenticationError, RateLimitError


@pytest.fixture
def words():
    return fixture_words("body", 12000)


@pytest.fixture
def templates():
    return [Template(id=f"template_{index}", pattern="Try {topic}", slots=["topic"]) for index in range(4)]


@pytest.fixture
def editorial(words, templates):
    return FixtureProvider().analyze(words, templates)


def provider_with_words(raw_words):
    client = Mock()
    client.audio.transcriptions.create.return_value = SimpleNamespace(words=raw_words)
    return OpenAIProvider(Settings(openai_api_key="test"), client=client), client


def test_whisper_uses_word_timestamps_and_maps_to_canonical_time(tmp_path):
    audio = tmp_path / "source.m4a"
    audio.write_bytes(b"test audio")
    provider, client = provider_with_words(
        [
            SimpleNamespace(word="Hello", start=0.1, end=0.4),
            SimpleNamespace(word="there.", start=0.45, end=0.8),
        ]
    )
    words = provider.transcribe(
        audio, "source_id", Timing(duration_ms=2000, media_origin_ms=500, encoder_delay_ms=100), 2000
    )
    assert [(word.start_ms, word.end_ms) for word in words] == [(500, 800), (850, 1200)]
    assert {word.source_id for word in words} == {"source_id"}
    assert client.audio.transcriptions.create.call_args.kwargs["model"] == "whisper-1"
    assert client.audio.transcriptions.create.call_args.kwargs["response_format"] == "verbose_json"
    assert client.audio.transcriptions.create.call_args.kwargs["timestamp_granularities"] == ["word"]


@pytest.mark.parametrize("start,end", [(0, 1000), (2, 1), (float("nan"), 1), (0, float("inf"))])
def test_invalid_provider_times_fail_before_clip_construction(tmp_path, start, end):
    audio = tmp_path / "source.m4a"
    audio.write_bytes(b"test audio")
    provider, _ = provider_with_words([SimpleNamespace(word="Hello", start=start, end=end)])
    with pytest.raises(ProviderError, match="invalid word timestamps"):
        provider.transcribe(audio, "body", Timing(duration_ms=2000), 2000)


def test_whisper_rounding_clamps_small_source_boundary_overshoot(tmp_path):
    audio = tmp_path / "source.m4a"
    audio.write_bytes(b"test audio")
    provider, _ = provider_with_words([SimpleNamespace(word="Hello", start=0, end=2.001)])
    words = provider.transcribe(audio, "body", Timing(duration_ms=2000), 2000)
    assert words[0].end_ms == 2000


def test_editorial_rejects_invented_word_ids(editorial, words, templates):
    editorial.takes[0].word_ids[0] = "invented"
    with pytest.raises(ProviderError, match="unavailable transcript words"):
        validate_editorial(editorial, words, templates)


def test_editorial_rejects_skipped_words_in_a_take(editorial, words, templates):
    editorial.takes[0].word_ids.pop(1)
    with pytest.raises(ProviderError, match="consecutive words"):
        validate_editorial(editorial, words, templates)


def test_editorial_rejects_shared_words_between_takes(editorial, words, templates):
    editorial.takes[1].word_ids = editorial.takes[0].word_ids
    with pytest.raises(ProviderError, match="overlapping takes"):
        validate_editorial(editorial, words, templates)


def test_editorial_rejects_two_selected_takes_for_one_line(editorial, words, templates):
    editorial.takes[1].line_id = editorial.takes[0].line_id
    with pytest.raises(ProviderError, match="at most one take"):
        validate_editorial(editorial, words, templates)


def test_editorial_rejects_invented_template_and_emphasis(editorial, words, templates):
    editorial.hooks[0].visual_titles[0].template_id = "invented"
    with pytest.raises(ProviderError, match="one title choice"):
        validate_editorial(editorial, words, templates)
    editorial.hooks[0].visual_titles[0].template_id = templates[0].id
    editorial.takes[0].emphasis_word_ids = [words[-1].id]
    with pytest.raises(ProviderError, match="Caption emphasis"):
        validate_editorial(editorial, words, templates)


def test_title_uses_fixed_wording_and_verbatim_evidence(words):
    template = Template(id="title", pattern="Start with {topic}, then {topic}.", slots=["topic"])
    choice = TitleChoice(
        template_id="title",
        slots=[
            SlotValue(name="topic", value="audio", evidence_word_ids=[words[1].id]),
        ],
    )
    title = assemble_title(choice, template, words)
    assert title["text"] == "Start with audio, then audio."
    assert title["ready"] is True
    assert title["missing_slots"] == []


@pytest.mark.parametrize(
    "value,indices", [("millions of views", [0, 1]), ("Clear attention", [0, 3]), ("audio", [])]
)
def test_unsupported_slot_stays_out_of_export(words, value, indices):
    template = Template(id="title", pattern="Try {topic}", slots=["topic"])
    choice = TitleChoice(
        template_id="title",
        slots=[
            SlotValue(name="topic", value=value, evidence_word_ids=[words[index].id for index in indices]),
        ],
    )
    title = assemble_title(choice, template, words)
    assert title["text"] == "Try {topic}"
    assert title["missing_slots"] == ["topic"]
    assert title["ready"] is False


@pytest.mark.parametrize(
    "pattern", ["Try {topic.foo}", "Try {topic!r}", "Try {topic:>100}", "Try {missing}", "Try {"]
)
def test_template_parser_accepts_only_declared_plain_slots(pattern):
    templates = [Template(id=f"t{index}", pattern=pattern, slots=["topic"]) for index in range(4)]
    with pytest.raises(ProviderError):
        validate_templates(templates)


def test_empty_templates_preserve_spoken_suggestions(words):
    editorial = FixtureProvider().analyze(words, [])
    assert len(editorial.hooks) == 4
    assert all(hook.visual_titles == [] for hook in editorial.hooks)


def test_hook_match_rejects_unknown_hook_and_reused_take(words):
    scripts = [HookScript(hook_id="hook_a", text="A hook"), HookScript(hook_id="hook_b", text="Another hook")]
    matches = Matches(
        matches=[
            Match(hook_id="hook_a", word_ids=[words[0].id], confidence=0.9, reason="Match"),
            Match(hook_id="hook_b", word_ids=[words[0].id], confidence=0.9, reason="Match"),
        ]
    )
    with pytest.raises(ProviderError, match="distinct takes"):
        validate_matches(matches, words, scripts)
    matches.matches[1].hook_id = "other"
    with pytest.raises(ProviderError, match="each supplied hook"):
        validate_matches(matches, words, scripts)


def test_unmatched_hook_requires_zero_confidence(words):
    scripts = [HookScript(hook_id="hook", text="A hook")]
    result = Matches(matches=[Match(hook_id="hook", word_ids=[], confidence=0.7, reason="No matching take")])
    with pytest.raises(ProviderError, match="zero confidence"):
        validate_matches(result, words, scripts)


def test_fixture_mode_requires_explicit_request_and_setting(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = Settings(openai_api_key="", enable_fixtures=True)
    with pytest.raises(ProviderError) as error:
        get_provider(settings)
    assert error.value.code == "provider_unconfigured"
    assert isinstance(get_provider(settings, fixture=True), FixtureProvider)
    with pytest.raises(ProviderError) as error:
        get_provider(Settings(enable_fixtures=False), fixture=True)
    assert error.value.code == "fixtures_disabled"


def test_requested_editor_model_is_exact():
    with pytest.raises(ProviderError, match="must be gpt-6-astra"):
        OpenAIProvider(Settings(editor_model="other"), client=Mock())


def test_structured_response_preserves_model_schema_and_local_validation(words, templates, editorial):
    client = Mock()
    client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed=editorial)
    result = OpenAIProvider(Settings(), client=client).analyze(words, templates)
    assert result == editorial
    options = client.responses.parse.call_args.kwargs
    assert options["model"] == "gpt-6-astra"
    assert options["text_format"] is Editorial
    assert options["store"] is False
    assert options["reasoning"] == {"effort": "low"}
    client.responses.parse.return_value = SimpleNamespace(status="incomplete", output_parsed=None)
    with pytest.raises(ProviderError, match="incomplete"):
        OpenAIProvider(Settings(), client=client).analyze(words, templates)


@pytest.mark.parametrize(
    "error_type,status,code,retryable",
    [
        (AuthenticationError, 401, "provider_auth", False),
        (RateLimitError, 429, "provider_rate_limit", True),
    ],
)
def test_provider_errors_omit_response_bodies(words, templates, error_type, status, code, retryable, caplog):
    secret_marker = "sensitive-provider-response-marker"
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.openai.com/v1/responses"))
    client = Mock()
    client.responses.parse.side_effect = error_type(
        secret_marker, response=response, body={"secret": secret_marker}
    )
    with pytest.raises(ProviderError) as error:
        OpenAIProvider(Settings(), client=client).analyze(words, templates)
    assert error.value.code == code
    assert error.value.retryable is retryable
    assert secret_marker not in str(error.value)
    assert secret_marker not in caplog.text


def test_visual_review_caps_frames_and_supplies_timestamps(tmp_path):
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"jpeg fixture")
    frames = [{"path": image, "timestamp_ms": index * 1000, "source_id": "body"} for index in range(10)]
    content = OpenAIProvider._content({"metrics": {}}, frames)
    assert len([item for item in content if item["type"] == "input_image"]) == 8
    assert content[1]["text"] == "Frame source_id=body canonical_ms=0"
    image.write_bytes(b"x" * (512 * 1024 + 1))
    with pytest.raises(ProviderError, match="512 KiB"):
        OpenAIProvider._content({}, frames)


def test_fixture_hook_source_matches_four_declared_takes():
    provider = FixtureProvider()
    words = provider.transcribe(
        Path("synthetic.mp4"), "hooks", Timing(duration_ms=12000), 12000, role="hooks"
    )
    scripts = [HookScript(hook_id=f"hook_{index}", text=f"Fixture hook {index}") for index in range(4)]
    matches = provider.match_hooks(words, scripts)
    assert len(matches.matches) == 4
    assert all(len(match.word_ids) == 4 for match in matches.matches)
    assert min(word.start_ms for word in words) >= 0
    assert max(word.end_ms for word in words) <= 12000


def test_boundary_review_sends_all_sheets_and_strict_decisions(tmp_path):
    from editmaxxing.models import BoundaryDecision, BoundaryReview

    picture = tmp_path / "sheet.jpg"
    picture.write_bytes(b"fixture sheet")
    boundaries = [
        {
            "id": f"b{i}",
            "timestamp_ms": 1000,
            "min_ms": 900,
            "max_ms": 1100,
            "words": [],
            "reason": "Complete take",
        }
        for i in range(16)
    ]
    frames = [
        {
            "path": picture,
            "boundary_id": b["id"],
            "source_id": "body",
            "timestamp_ms": 1000,
            "frame_timestamps_ms": [867, 900, 933, 967, 1000, 1033, 1067, 1100],
        }
        for b in boundaries
    ]
    expected = BoundaryReview(
        decisions=[
            BoundaryDecision(boundary_id=b["id"], timestamp_ms=1000, confidence=0.9, reason="Mouth at rest")
            for b in boundaries
        ]
    )
    client = Mock()
    client.responses.parse.return_value = SimpleNamespace(status="completed", output_parsed=expected)
    provider = OpenAIProvider(Settings(), client=client)
    assert provider.review_boundaries(boundaries, frames) == expected
    options = client.responses.parse.call_args.kwargs
    assert options["text_format"] is BoundaryReview
    content = options["input"][0]["content"]
    images = [c for c in content if c["type"] == "input_image"]
    assert len(images) == 16 and all(i["detail"] == "high" for i in images)
    assert options["max_output_tokens"] == 5000
    with pytest.raises(ProviderError, match="each|Each"):
        provider.review_boundaries(boundaries, frames[:-1])
