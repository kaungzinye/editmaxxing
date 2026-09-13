from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Millis = Annotated[int, Field(strict=True, ge=0)]
Target = Annotated[int, Field(strict=True, ge=90000, le=180000)]
Id = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")]
Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Position(Model):
    x: float = Field(default=0.44, ge=0, le=1)
    y: float = Field(default=0.7, ge=0, le=1)


class Timing(Model):
    # canonical_ms = decoded_media_ms + media_origin_ms - encoder_delay_ms
    media_origin_ms: Millis = 0
    encoder_delay_ms: Millis = 0
    duration_ms: Annotated[int, Field(strict=True, gt=0)]
    sample_rate: int = Field(default=48000, ge=8000, le=192000)
    extractor: str = Field(default="ffmpeg", max_length=100)


class ProjectCreate(Model):
    name: str = Field(default="Untitled", min_length=1, max_length=200)
    target_duration_ms: Target = 120000


class HookScript(Model):
    hook_id: Id
    text: str = Field(min_length=1, max_length=2000)


class SourceCreate(Model):
    source_id: Id
    role: Literal["body", "hooks"]
    duration_ms: Annotated[int, Field(strict=True, gt=0, le=1200000)]
    fingerprint: Digest
    timing: Timing
    hook_scripts: list[HookScript] = Field(default_factory=list, max_length=4)


class UploadCreate(Model):
    size_bytes: int = Field(gt=0)
    sha256: Digest


class Part(Model):
    part: int = Field(ge=0)
    sha256: Digest


class CompleteUpload(Model):
    parts: list[Part] = Field(min_length=1)


class Word(Model):
    id: Id
    source_id: Id
    text: str
    start_ms: Millis
    end_ms: Millis


class Clip(Model):
    id: Id
    source_id: Id
    line_id: Id
    take_id: Id
    role: Literal["hook", "body"]
    source_start_ms: Millis
    source_end_ms: Millis
    selection_reason: str = "Creator selection"

    @model_validator(mode="after")
    def range_valid(self):
        if self.source_start_ms >= self.source_end_ms:
            raise ValueError("Clip range must have positive duration")
        return self


class CaptionWord(Model):
    word_id: str | None
    text: str = Field(min_length=1, max_length=200)


class Caption(Model):
    id: Id
    clip_id: Id
    start_ms: Millis
    end_ms: Millis
    words: list[CaptionWord] = Field(min_length=1, max_length=24)
    emphasis_word_id: str | None = None


class CaptionEdit(Model):
    id: Id
    clip_id: Id
    # Source-time anchors survive reordering, repeat occurrences, and partial trims.
    source_start_ms: Millis
    source_end_ms: Millis
    deleted: bool = False
    replaces_word_ids: list[str] = Field(default_factory=list)
    words: list[CaptionWord] = Field(default_factory=list, max_length=24)
    emphasis_word_id: str | None = None

    @model_validator(mode="after")
    def valid(self):
        if self.source_start_ms >= self.source_end_ms or (not self.deleted and not self.words):
            raise ValueError("Caption edit needs a positive range and text or a deletion")
        return self


class Overlay(Model):
    text: str = Field(max_length=500)
    position: Position = Field(default_factory=lambda: Position(y=0.24))
    hold_ms: Millis = 12000
    fade_ms: Literal[300] = 300


class Audio(Model):
    normalization_enabled: bool = True
    preset: Literal["speech_consistent"] = "speech_consistent"


class CaptionStyle(Model):
    preset: Literal["classic_box"] = "classic_box"
    position: Position = Field(default_factory=Position)


class DeadSpace(Model):
    enabled: bool = True
    threshold_ms: Literal[700] = 700
    retain_ms: Literal[250] = 250


class DroppedLine(Model):
    line_id: Id
    text: str
    reason: str


class Plan(Model):
    schema_version: Literal[1] = 1
    revision: Millis = 0
    target_duration_ms: Target = 120000
    duration_ms: Millis = 0
    target_met: bool = True
    selected_hook_id: Id | None = None
    selected_visual_title_id: Id | None = None
    clips: list[Clip] = Field(default_factory=list, max_length=1000)
    dropped_lines: list[DroppedLine] = Field(default_factory=list)
    dead_space: DeadSpace = Field(default_factory=DeadSpace)
    hook_overlay: Overlay | None = None
    audio: Audio = Field(default_factory=Audio)
    caption_style: CaptionStyle = Field(default_factory=CaptionStyle)
    captions: list[Caption] = Field(default_factory=list)
    caption_edits: list[CaptionEdit] = Field(default_factory=list)


class SavePlan(Model):
    base_revision: Millis
    plan: Plan
    proposal_id: Id | None = None


class Rank(Model):
    base_revision: Millis
    target_duration_ms: Target
    selected_hook_id: Id | None = None
    dead_space_enabled: bool = True


class VisualReview(Model):
    base_revision: Millis
    source_id: Id


class Combination(Model):
    id: Id
    hook_id: Id | None = None
    visual_title_id: Id | None = None
    overlay: Overlay | None = None
    use_title: bool = True


class RenderRequest(Model):
    plan_revision: Millis
    kind: Literal["draft", "export"]
    combinations: list[Combination] = Field(min_length=1, max_length=16)


class Template(Model):
    id: Id
    pattern: str = Field(min_length=1, max_length=500)
    slots: list[Id] = Field(max_length=10)


class Templates(Model):
    templates: list[Template] = Field(min_length=4, max_length=4)


# Required fields keep the provider's strict JSON schema explicit.
class EditorialTake(Model):
    id: Id
    line_id: Id
    word_ids: list[Id]
    role: Literal["body", "hook"]
    score: int = Field(ge=0, le=100)
    selected: bool
    reason: str
    emphasis_word_ids: list[Id]


class SlotValue(Model):
    name: str
    value: str
    evidence_word_ids: list[Id]


class TitleChoice(Model):
    template_id: Id
    slots: list[SlotValue]


class HookChoice(Model):
    proposed_text: str
    visual_titles: list[TitleChoice]


class Editorial(Model):
    takes: list[EditorialTake]
    hooks: list[HookChoice]


class Match(Model):
    hook_id: Id
    word_ids: list[Id]
    confidence: float = Field(ge=0, le=1)
    reason: str


class Matches(Model):
    matches: list[Match]


class Feedback(Model):
    text: str
    confidence: float = Field(ge=0, le=1)
    suggested_action: Literal["keep_take", "play_transition", "record_again"]
