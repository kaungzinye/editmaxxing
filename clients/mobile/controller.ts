import { API, RequestError } from '@editmaxxing/client/api';
import type { SourceJournal } from '@editmaxxing/client/journal';
import type { ByteSource } from '@editmaxxing/client/api';
import type { HookScript, HookUpdate, Job, JobCreated, Plan, ProjectCreated, ProjectState, RenderInput, RenderOutput, RenderQueued } from '../../contracts/plan';
import type { Clip, EditProgress, Stage } from './workflow';
import { API_BASE_URL } from './config';

export interface Recording extends SourceJournal { clip: Clip; audioJob?: string; videoJob?: string; selected?: boolean }
export interface RenderManifest {
  requestId: string; key: string; kind: 'draft' | 'export'; pairIds: string[];
  jobId?: string; inputs?: RenderInput[];
}
export interface Session {
  baseUrl: string; projectId?: string; stage: Stage; sources: Recording[]; jobs: Record<string, Job>;
  verbalIds: string[]; textIds: string[]; includePhysical: boolean; initializedChoices: boolean;
  keptIds: string[] | null; activeId: string | null; renders: RenderManifest[]; project?: ProjectState;
  planDraft?: Plan; error: string; preparation?: Clip;
}
export const initialSession = (): Session => ({
  baseUrl: API_BASE_URL, stage: 'film', sources: [], jobs: {}, verbalIds: [], textIds: [],
  includePhysical: false, initializedChoices: false, keptIds: null, activeId: null, renders: [], error: '',
});
export interface Dependencies {
  save(session: Session): void;
  saveToken(id: string, token: string): Promise<void>;
  readToken(id: string): Promise<string>;
  prepare(clip: Clip, scripts: HookScript[]): Promise<Recording>;
  read(file: NonNullable<Recording['original']>): ByteSource;
  uuid(): string;
  transport?: typeof fetch;
}
export function jobProgress(job?: Job): EditProgress {
  if (!job) return { mode: 'live', status: 'idle', percent: 0, label: 'Waiting for recording' };
  const status = job.state === 'succeeded' ? 'complete' : ['failed', 'cancelled'].includes(job.state) ? 'error' : 'running';
  return { mode: 'live', status, percent: job.state === 'succeeded' ? 100 : Math.min(99, Math.round(Math.max(0, Math.min(1, job.progress)) * 100)),
    label: job.error?.message ?? (job.stage === 'waiting_video' ? 'Waiting for video upload' : job.stage.replaceAll('_', ' ')) };
}
export function renderKey(project: ProjectState, pairIds: string[]) {
  return JSON.stringify([project.plan.revision, pairIds.map(id => {
    const [hid, tid] = id.split('--');
    const hook = project.hooks.find(h => h.id === hid), title = project.titles.find(t => t.id === tid);
    return [id, hook?.take_id, hook?.capture_revision, title?.text_revision, title?.text];
  })]);
}
export function matchingOutput(session: Session, pairId: string, kind: 'draft' | 'export'): RenderOutput | undefined {
  const project = session.project;
  if (!project) return;
  for (const manifest of [...session.renders].reverse()) {
    if (manifest.kind !== kind || !manifest.pairIds.includes(pairId) || manifest.key !== renderKey(project, manifest.pairIds)) continue;
    if (!manifest.jobId || session.jobs[manifest.jobId]?.state !== 'succeeded') continue;
    const input = manifest.inputs?.find(i => i.combination_id === pairId);
    if (!input) continue;
    const output = project.outputs.find(o => o.render_job_id === manifest.jobId && o.combination_id === pairId && o.kind === kind
      && o.input_hash === input.input_hash && o.hook_take_id === input.hook_take_id
      && o.hook_revision === input.hook_revision && o.title_revision === input.title_revision
      && o.plan_revision === project.plan.revision);
    if (output) return output;
  }
}
export class ProjectController {
  private listeners = new Set<() => void>();
  private transfers = new Set<string>();
  private refreshing = false;
  private rendering = false;
  private preparing = false;
  reset() {
    if (this.preparing || this.rendering || this.transfers.size || this.refreshing) throw new Error('Wait for active transfers to finish before starting another video.');
    this.patch({ ...initialSession(), baseUrl: this.state.baseUrl, projectId: undefined, project: undefined, planDraft: undefined, preparation: undefined });
  }
  constructor(public state: Session, private deps: Dependencies) {}
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  snapshot = () => this.state;
  patch(changes: Partial<Session>) {
    this.state = { ...this.state, ...changes }; this.deps.save(this.state); this.listeners.forEach(fn => fn());
  }
  fail(error: unknown) {
    const response = error instanceof RequestError ? error.response as { error?: { message: string } } : null;
    this.patch({ error: response?.error?.message ?? (error instanceof Error ? error.message : String(error)) });
  }
  async api() {
    if (!this.state.projectId) throw new Error('Confirm a body recording first.');
    const token = await this.deps.readToken(this.state.projectId);
    if (!token) throw new Error('Project access is missing. Start a new video.');
    return new API(this.state.baseUrl, token, undefined, this.deps.transport);
  }
  private path() { return `/projects/${this.state.projectId}`; }
  private remember(source: Recording, changes: Partial<Recording>) {
    this.patch({ sources: this.state.sources.map(s => s.sourceId === source.sourceId ? { ...s, ...changes } : s) });
  }
  private async rememberJob(id: string) {
    const api = await this.api();
    const job = await api.request<Job>(`/jobs/${id}`);
    this.patch({ jobs: { ...this.state.jobs, [id]: job } });
  }
  async capture(clip: Clip, hookId?: string) {
    if (this.preparing) throw new Error('Wait for the recording to finish saving.');
    this.preparing = true;
    try {
      if (clip.demo || !clip.uri) throw new Error('Choose a recorded video.');
      if (this.state.sources.length >= 20) throw new Error('This project has twenty recordings. Start a new video to record more takes.');
      if (!hookId && this.state.sources.some(s => s.role === 'body')) throw new Error('Start a new video to use another body recording.');
      this.patch({ preparation: clip, error: '' });
      const hook = this.state.project?.hooks.find(h => h.id === hookId);
      const scripts: HookScript[] = hook ? [{ hook_id: hook.id, text: hook.proposed_text, capture_revision: hook.capture_revision,
        action_start_ms: hook.action_enabled ? clip.actionStartMs ?? null : null }] : [];
      if (hookId && !hook) throw new Error('Refresh recommendations before capturing this hook.');
      if (hook?.action_enabled && scripts[0].action_start_ms === null) throw new Error('Confirm where the physical action starts.');
      const recording = await this.deps.prepare(clip, scripts);
      if (!this.state.projectId) {
        const created = await new API(this.state.baseUrl, '', undefined, this.deps.transport).request<ProjectCreated>('/projects', 'POST', { name: clip.name, target_duration_ms: 120000 });
        await this.deps.saveToken(created.project_id, created.project_token);
        this.patch({ projectId: created.project_id });
      }
      this.patch({ sources: [...this.state.sources, recording], preparation: undefined, stage: hook ? this.state.stage : 'hooks' });
      void this.transfer(recording).catch(error => this.fail(error));
      return recording.clip;
    } finally { this.preparing = false; }
  }
  async transfer(source: Recording) {
    if (this.transfers.has(source.sourceId)) return;
    this.transfers.add(source.sourceId);
    try {
      const api = await this.api(), prefix = `${this.path()}/sources/${source.sourceId}`;
      if (!source.original || !source.audio) throw new Error('The saved recording needs its original and extracted audio.');
      if (!source.registered) {
        await api.request(`${this.path()}/sources`, 'POST', { source_id: source.sourceId, role: source.role,
          duration_ms: source.duration, timing: source.timing, fingerprint: source.original.sha256, hook_scripts: source.hookScripts });
        this.remember(source, { registered: true });
      }
      const results = await Promise.allSettled([
        (async () => {
          if (source.audioJob) return;
          const file = this.deps.read(source.audio!);
          const result = await api.request<JobCreated>(`${prefix}/audio`, 'PUT', await file.read(0, file.size), {
            'X-Content-SHA256': source.audio!.sha256, 'X-Timing-Manifest': JSON.stringify(source.audioTiming),
          });
          this.remember(source, { audioJob: result.job_id }); await this.rememberJob(result.job_id);
        })(),
        (async () => {
          if (source.videoJob) return;
          let uploadId = source.uploadId;
          if (uploadId) {
            try { await api.request(`${prefix}/video/uploads/${uploadId}`); }
            catch (error) { if (error instanceof RequestError && [404, 410].includes(error.status)) uploadId = undefined; else throw error; }
          }
          const result = await api.uploadOriginal({ projectId: this.state.projectId!, sourceId: source.sourceId,
            file: this.deps.read(source.original!), sha256: source.original!.sha256, uploadId,
            remember: async id => this.remember(source, { uploadId: id }), progress: () => {}, paused: () => false });
          if (result) { this.remember(source, { videoJob: result.job_id }); await this.rememberJob(result.job_id); }
        })(),
      ]);
      for (const result of results) if (result.status === 'rejected') throw result.reason;
    } finally { this.transfers.delete(source.sourceId); }
  }
  async refresh() {
    if (!this.state.projectId || this.refreshing) return;
    this.refreshing = true;
    try {
      const api = await this.api();
      const [project, jobs] = await Promise.all([
        api.request<ProjectState>(this.path()),
        Promise.all([...new Set([...Object.keys(this.state.jobs), ...this.state.sources.flatMap(s => [s.audioJob, s.videoJob]), ...this.state.renders.map(m => m.jobId)].filter((id): id is string => !!id))].map(id => api.request<Job>(`/jobs/${id}`))),
      ]);
      const changes: Partial<Session> = { project, jobs: Object.fromEntries(jobs.map(j => [j.id, j])) };
      if (!this.state.initializedChoices && project.recommendations.status === 'ready') {
        changes.verbalIds = project.hooks.map(h => h.id); changes.textIds = project.titles.map(t => t.id); changes.initializedChoices = true;
      }
      this.patch(changes);
      for (const source of [...this.state.sources].reverse()) {
        if (source.role !== 'hooks' || source.selected) continue;
        const script = source.hookScripts[0], hook = project.hooks.find(h => h.id === script.hook_id);
        const latest = [...this.state.sources].reverse().find(s => s.hookScripts[0]?.hook_id === script.hook_id);
        if (latest?.sourceId !== source.sourceId || hook?.capture_revision !== script.capture_revision) continue;
        const candidate = hook.candidates.find(c => c.source_id === source.sourceId);
        if (!candidate) continue;
        if (candidate.confidence < .65) { this.patch({ error: 'This take needs clearer matching speech. Record the displayed hook again.' }); continue; }
        await api.request(`${this.path()}/hooks/${hook.id}`, 'PUT', { take_id: candidate.take_id });
        this.remember(source, { selected: true });
        this.patch({ project: await api.request<ProjectState>(this.path()) });
      }
    } finally { this.refreshing = false; }
  }
  async resume() {
    this.patch({ error: '' });
    if (!this.state.projectId) return;
    await this.refresh();
    await Promise.all(this.state.sources.map(s => this.transfer(s)));
  }
  async retry() {
    await this.resume();
    const api = await this.api();
    for (const job of Object.values(this.state.jobs)) {
      if (job.state === 'failed' || job.state === 'cancelled') {
        const result = await api.request<JobCreated>(`/jobs/${job.id}/retry`, 'POST');
        await this.rememberJob(result.job_id);
        if (result.job_id !== job.id) {
          const jobs = { ...this.state.jobs }; delete jobs[job.id];
          this.patch({ jobs, renders: this.state.renders.map(m => m.jobId === job.id ? { ...m, jobId: result.job_id } : m),
            sources: this.state.sources.map(s => ({ ...s, audioJob: s.audioJob === job.id ? result.job_id : s.audioJob,
              videoJob: s.videoJob === job.id ? result.job_id : s.videoJob })) });
        }
      }
    }
  }
  async editHook(id: string, changes: HookUpdate) {
    const api = await this.api();
    await api.request(`${this.path()}/hooks/${id}`, 'PUT', changes); await this.refresh();
  }
  async editTitle(id: string, text: string) {
    const title = this.state.project?.titles.find(t => t.id === id);
    if (!title) return;
    const api = await this.api();
    await api.request(`${this.path()}/titles/${id}`, 'PUT', { text, base_revision: title.text_revision }); await this.refresh();
  }
  async physical(enabled: boolean) {
    for (const hook of this.state.project?.hooks ?? []) await this.editHook(hook.id, { action_enabled: enabled });
    this.patch({ includePhysical: enabled });
  }
  async savePlan(plan: Plan) {
    this.patch({ planDraft: plan });
    const api = await this.api();
    try {
      const saved = await api.request<Plan>(`${this.path()}/plan`, 'PUT', { base_revision: plan.revision, plan });
      this.patch({ planDraft: undefined, project: { ...this.state.project!, plan: saved } });
    } catch (error) { await this.refresh(); throw error; }
  }
  async render(kind: 'draft' | 'export', pairIds: string[]) {
    if (this.rendering || !pairIds.length) return;
    this.rendering = true;
    try {
      await this.refresh();
      const project = this.state.project;
      if (this.state.sources.some(s => s.role === 'hooks' && !s.selected && pairIds.some(id => id.startsWith(`${s.hookScripts[0].hook_id}--`)) && [...this.state.sources].reverse().find(latest => latest.hookScripts[0]?.hook_id === s.hookScripts[0].hook_id)?.sourceId === s.sourceId)) throw new Error('Wait for the selected hook recordings to finish matching.');
      if (!project?.plan.clips.length) throw new Error('Wait for the body edit to finish.');
      if (this.state.planDraft) throw new Error('Save or reconcile the pending body edit before rendering.');
      const key = renderKey(project, pairIds);
      let manifest = this.state.renders.find(m => m.kind === kind && m.key === key);
      if (manifest?.jobId) return;
      if (!manifest) {
        manifest = { requestId: this.deps.uuid(), key, kind, pairIds };
        this.patch({ renders: [...this.state.renders, manifest] });
      }
      const api = await this.api();
      const result = await api.request<RenderQueued>(`${this.path()}/renders`, 'POST', {
        request_id: manifest.requestId, plan_revision: project.plan.revision, kind,
        combinations: pairIds.map(id => { const [hook_id, visual_title_id] = id.split('--'); return { id, hook_id, visual_title_id, use_title: true }; }),
      });
      this.patch({ renders: this.state.renders.map(m => m.requestId === manifest!.requestId ? { ...m, jobId: result.job_id, inputs: result.inputs } : m), error: '' });
      await this.rememberJob(result.job_id);
    } finally { this.rendering = false; }
  }
  async media(pairId: string, kind: 'draft' | 'export') {
    await this.refresh();
    const output = matchingOutput(this.state, pairId, kind);
    if (!output) throw new Error('Wait for the matching render to finish.');
    return output.url;
  }
}
