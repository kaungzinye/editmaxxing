/** Source ranges are half-open. All time values are integer milliseconds. */
export type Millis = number;
/** API validates an integer in 90000..180000. */
export type TargetDuration = number;
export type SourceRole = "body" | "hooks";
export type Position = { x: number; y: number };

export interface TimingManifest {
  /** canonical_ms = decoded_media_ms + media_origin_ms - encoder_delay_ms */
  media_origin_ms: Millis;
  encoder_delay_ms: Millis;
  duration_ms: Millis;
  sample_rate: number;
  extractor: string;
}
export interface HookScript { hook_id: string; text: string; capture_revision: number; action_start_ms: Millis | null }
export interface SourceCreate {
  source_id: string;
  role: SourceRole;
  duration_ms: Millis;
  fingerprint: string;
  timing: TimingManifest;
  hook_scripts: HookScript[];
}
export interface Word {
  id: string;
  source_id: string;
  text: string;
  start_ms: Millis;
  end_ms: Millis;
}
export interface Recommendation {
  generated_text: string; text_revision: number; rationale_revision: number;
  mechanism: string; rationale: string; evidence_word_ids: string[]; validation: "pending" | "supported";
}
export interface VisualHookTitle extends Recommendation {
  id: string;
  template_id: string | null;
  slots: Record<string, string>;
  missing_slots: string[];
  text: string;
}
export interface SpokenHook extends Recommendation {
  id: string;
  proposed_text: string;
  take_id: string | null;
  movement: string; action_enabled: boolean; capture_revision: number;
  candidates: HookCandidate[];
  clips: Clip[];
}
export interface HookCandidate { capture_revision: number; take_id: string; source_id: string; confidence: number; reason: string; clips: Clip[] }
export interface Take {
  id: string; source_id: string; line_id: string; word_ids: string[];
  role: "body" | "hook"; score: number; selected: boolean; reason: string; emphasis_word_ids: string[];
}
export interface Clip {
  id: string;
  source_id: string;
  line_id: string;
  take_id: string;
  role: "hook" | "body";
  source_start_ms: Millis;
  source_end_ms: Millis;
  selection_reason: string;
}
export interface CaptionWord { word_id: string | null; text: string }
/** Word timing uses assembled timeline milliseconds; unmatched creator text has null timing. */
export interface TimedCaptionWord extends CaptionWord { start_ms: Millis | null; end_ms: Millis | null }
export interface Caption {
  id: string;
  clip_id: string;
  start_ms: Millis;
  end_ms: Millis;
  words: TimedCaptionWord[];
  emphasis_word_id: string | null;
}
/** A manual edit anchors to one clip occurrence and canonical source time. */
export interface CaptionEdit {
  id: string;
  clip_id: string;
  source_start_ms: Millis;
  source_end_ms: Millis;
  deleted: boolean;
  replaces_word_ids: string[];
  words: CaptionWord[];
  emphasis_word_id: string | null;
}
export interface Overlay {
  text: string;
  position: Position;
  hold_ms: Millis;
  fade_ms: 300;
}
export interface Plan {
  schema_version: 1;
  revision: number;
  target_duration_ms: TargetDuration;
  duration_ms: Millis;
  target_met: boolean;
  selected_hook_id: string | null;
  selected_visual_title_id: string | null;
  clips: Clip[];
  dropped_lines: { line_id: string; text: string; reason: string }[];
  dead_space: { enabled: boolean; threshold_ms: 700; retain_ms: 250 };
  hook_overlay: Overlay | null;
  audio: { normalization_enabled: boolean; preset: "speech_consistent" };
  caption_style: { preset: "spoken_outline" | "classic_box"; position: Position };
  captions: Caption[];
  caption_edits: CaptionEdit[];
}
export interface SavePlan { base_revision: number; plan: Plan; proposal_id?: string | null }
export interface RankRequest {
  base_revision: number;
  target_duration_ms: TargetDuration;
  selected_hook_id: string | null;
  dead_space_enabled: boolean;
}
export interface Combination {
  id: string;
  hook_id: string | null;
  visual_title_id: string | null;
  overlay?: Overlay | null;
  use_title: boolean;
}
export interface RenderRequest {
  request_id?: string;
  plan_revision: number;
  kind: "draft" | "export";
  combinations: Combination[];
}
export interface Template { id: string; pattern: string; slots: string[] }
export interface APIError { error: { code: string; message: string; retryable: boolean }; request_id?: string }
export interface ProjectCreated { project_id: string; project_token: string; expires_at: number }
export interface JobCreated { job_id: string; job_ids?: string[] }
export interface Job<T = unknown> {
  id: string;
  project_id: string;
  state: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  stage: string;
  progress: number;
  result: T | null;
  error: { code: string; message: string; retryable: boolean } | null;
}
export interface UploadPart { part: number; sha256: string; size_bytes: number }
export interface UploadSession {
  upload_id: string;
  part_size: number;
  size_bytes: number;
  sha256: string;
  parts: UploadPart[];
  state: string;
  expires_at: number;
}
export interface Proposal {
  id: string;
  base_revision: number;
  plan: Plan;
  analysis_refs: string[];
}
/** Source and analysis metadata remain available for raw inspection. */
export interface SignedMedia { url: string; expires_at: number }
export interface SourceState extends SourceCreate {
  audio_state: string;
  video_state: string;
  fixture: boolean;
  uploads: Record<string, UploadSession>;
  storage: {
    copy_kind: "processing" | "durable_backup";
    expires_at: number;
    restore_capable: boolean;
    original_verified: boolean;
    sha256?: string;
    size_bytes?: number;
    verified_at?: number;
  };
  audio_timing?: TimingManifest;
  audio_sha256?: string;
  audio_size_bytes?: number;
  words?: Word[];
  deleted?: boolean;
  raw_audio_media?: SignedMedia;
  audio_media?: SignedMedia;
  editing_media?: SignedMedia;
  original_media?: SignedMedia;
}
export interface RenderInput {
  combination_id: string; hook_take_id: string | null; hook_revision: number | null; title_revision: number | null; input_hash: string;
}
export interface RenderQueued extends JobCreated { inputs: RenderInput[] }
export interface RenderOutput extends SignedMedia, RenderInput {
  render_job_id: string;
  combination_id: string;
  plan_revision: number;
  hook_take_id: string | null;
  kind: "draft" | "export";
  metadata: Record<string, unknown>;
}
export interface DeliveryFeedback {
  text: string;
  confidence: number;
  suggested_action: "keep_take" | "play_transition" | "record_again";
  hook_take_id: string;
  hook_id: string;
  body_revision: number;
  evidence: Record<string, unknown>;
  stale: boolean;
  advisory: true;
}
export interface ProjectState {
  project_id: string;
  name: string;
  sources: Record<string, SourceState>;
  words: Word[];
  analysis: Record<string, unknown>;
  boundary_reviews: Record<string, BoundaryReviewRecord>;
  takes: Record<string, Take>;
  hooks: SpokenHook[];
  titles: VisualHookTitle[];
  recommendations: { status: "pending" | "ready"; short_set_reason: string };
  proposals: Proposal[];
  feedback: DeliveryFeedback[];
  outputs: RenderOutput[];
  plan: Plan;
  templates: Template[];
  expires_at: number;
}

export interface BoundaryReviewRecord {
  source_id: string;
  version: string;
  fixture: boolean;
  elapsed_seconds: number;
  review: { decisions: BoundaryDecision[] };
  evidence: (BoundaryDecision & { candidate_ms: number; applied_ms: number; accepted: boolean; needs_review: boolean })[];
  frames: { source_id: string; boundary_id: string; timestamp_ms: number; frame_timestamps_ms: number[] }[];
}
export interface BoundaryDecision {
  boundary_id: string;
  timestamp_ms: number;
  confidence: number;
  reason: string;
}

export interface ProjectCreate { name: string; target_duration_ms: TargetDuration }
export interface UploadCreate { size_bytes: number; sha256: string }
export interface CompleteUpload { parts: { part: number; sha256: string }[] }
export interface HookUpdate { proposed_text?: string; take_id?: string; movement?: string; action_enabled?: boolean; base_revision?: number }
export interface TitleUpdate { text: string; base_revision: number }
export interface SourceDependencies { source_id: string; current_clip_ids: string[]; saved_revisions: number[]; hook_ids: string[] }
export interface RenderResult { plan_revision: number; outputs: RenderOutput[] }
