import type { Hook, VerbalHook } from './hooks';

export type Stage = 'film' | 'hooks' | 'record-hooks' | 'final';

export type Clip = {
  id: string;
  uri?: string;
  duration: number;
  demo: boolean;
  name: string;
  actionStartMs?: number;
};

export type EditProgress = {
  percent: number;
  label: string;
  mode: 'demo' | 'live';
  status: 'idle' | 'running' | 'complete' | 'error';
};

export type HookTake = { hookId: string; fingerprint: string; clip: Clip };

export type VideoVersion = {
  id: string;
  spoken: VerbalHook;
  onScreen: Hook;
  movement?: string;
  take?: Clip;
  /** Supplied only after the editing service returns a real completed render. */
  renderUri?: string;
  exportUri?: string;
};

export function takeFingerprint(hook: VerbalHook, includePhysical: boolean): string {
  return JSON.stringify([hook.line, includePhysical ? hook.movement : null]);
}

export function buildVersions(verbal: VerbalHook[], text: Hook[], includePhysical: boolean, takes: HookTake[]): VideoVersion[] {
  return verbal.flatMap((spoken) => text.map((onScreen) => ({
    id: `${spoken.id}--${onScreen.id}`,
    spoken,
    onScreen,
    ...(includePhysical ? { movement: spoken.movement } : {}),
    take: takes.find((take) => take.hookId === spoken.id && take.fingerprint === takeFingerprint(spoken, includePhysical))?.clip,
  })));
}

export const EMPTY_PROGRESS: EditProgress = { percent: 0, label: 'Waiting for video', mode: 'live', status: 'idle' };
