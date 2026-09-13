/** Source ranges are half-open. Time values are integer milliseconds. */
export type TargetDuration = 15000 | 30000 | 45000 | 60000 | 90000;
export type Position = { x: number; y: number };
export interface Clip {
  id: string;
  source_id: string;
  line_id: string;
  take_id: string;
  role: "hook" | "body";
  source_start_ms: number;
  source_end_ms: number;
  selection_reason: string;
}
export interface Caption {
  id: string;
  clip_id: string;
  start_ms: number;
  end_ms: number;
  words: { word_id: string; text: string }[];
  emphasis_word_id: string;
}
export interface Plan {
  schema_version: 1;
  revision: number;
  target_duration_ms: TargetDuration;
  duration_ms: number;
  target_met: boolean;
  selected_hook_id: string;
  clips: Clip[];
  dropped_lines: { line_id: string; text: string; reason: string }[];
  dead_space: { enabled: boolean; threshold_ms: 700; retain_ms: 250 };
  hook_overlay: {
    locked: boolean;
    text: string;
    position: Position;
    hold_ms: 12000;
    fade_ms: 300;
  };
  caption_style: { preset: "classic_box"; position: Position };
  captions: Caption[];
}
