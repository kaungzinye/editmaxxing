import React, { useEffect, useRef, useState } from 'react';
import { AppState, Linking, Platform, Pressable, ScrollView, StyleSheet, Switch, Text as NativeText, TextInput, View, type TextProps } from 'react-native';
import { useFonts } from 'expo-font';
import { fetch as expoFetch } from 'expo/fetch';
import { VideoView, useVideoPlayer } from 'expo-video';
import { StatusBar } from 'expo-status-bar';
import { randomUUID } from 'expo-crypto';
import type { Caption, Combination, Job, JobCreated, Plan, ProjectCreated, ProjectState, SourceCreate, TimingManifest } from '../../contracts/plan';
import { API } from '@editmaxxing/client/api';
import { remapDraftCaptions } from './src/editor';
import { rememberSourceChanges } from '@editmaxxing/client/transfers';
import { extractedFile, pickFile, readFile, recoverOriginal, unlinkedOriginals } from '@editmaxxing/client/files';
import { readJournal, readToken, saveJournal, saveToken, type Journal, type ProjectJournal, type SourceJournal } from '@editmaxxing/client/journal';
import { extractAudio, extractionAvailable, inspectSource } from '@editmaxxing/client/source-audio';

const timing = (): TimingManifest => ({ media_origin_ms: 0, encoder_delay_ms: 0, duration_ms: 10000, sample_rate: 48000, extractor: 'original' });
const source = (role: 'body' | 'hooks' = 'body'): SourceJournal => ({ sourceId: `src_${randomUUID().replace(/-/g, '')}`, role, duration: 10000, timing: timing(), audioTiming: { ...timing(), extractor: 'ffmpeg' }, hookScripts: [] });
const pretty = (v: unknown) => JSON.stringify(v, null, 2);
function Text({ style, ...props }: TextProps) { return <NativeText {...props} style={[{ fontFamily: 'TikTokSans' }, style]} />; }
function Button({ title, disabled, onPress }: { title: string; disabled?: boolean; onPress: () => void }) { return <Pressable accessibilityRole="button" disabled={disabled} onPress={onPress} style={{ backgroundColor: disabled ? '#ccd3dc' : '#245ba6', padding: 10, borderRadius: 4 }}><Text style={{ color: 'white' }}>{title}</Text></Pressable>; }
function Field({ label, value, set, multiline = false, secure = false }: { label: string; value: string; set: (s: string) => void; multiline?: boolean; secure?: boolean }) {
  return <View style={styles.field}><Text>{label}</Text><TextInput accessibilityLabel={label} style={[styles.input, multiline && styles.json]} value={value} onChangeText={set} multiline={multiline} secureTextEntry={secure} autoCapitalize="none" autoCorrect={false} /></View>;
}
function Video({ uri }: { uri: string }) {
  const player = useVideoPlayer(uri);
  return <VideoView player={player} style={styles.video} nativeControls contentFit="contain" />;
}
function urls(value: unknown): string[] {
  if (typeof value === 'string') return /^https?:\/\//.test(value) ? [value] : [];
  if (Array.isArray(value)) return value.flatMap(urls);
  if (value && typeof value === 'object') return Object.values(value).flatMap(urls);
  return [];
}
export default function App() {
  const [fontsLoaded, fontError] = useFonts({ TikTokSans: require('./assets/fonts/TikTokSans16pt-Regular.ttf'), TikTokSansBold: require('./assets/fonts/TikTokSans36pt-Bold.ttf') });
  const [baseUrl, setBaseUrl] = useState('http://localhost:8000');
  const [name, setName] = useState('Endpoint test');
  const [target, setTarget] = useState('120000');
  const [projectId, setProjectId] = useState('');
  const [token, setToken] = useState('');
  const [journal, setJournal] = useState<Journal>({ projects: [] });
  const journalRef = useRef(journal);
  const [local, setLocal] = useState<SourceJournal>(source);
  const localRef = useRef(local);
  localRef.current = local;
  const [audioTimingText, setAudioTimingText] = useState(pretty(local.audioTiming));
  const [sourceTimingText, setSourceTimingText] = useState(pretty(local.timing));
  const [hookScriptsText, setHookScriptsText] = useState('[]');
  const [project, setProject] = useState<ProjectState | null>(null);
  const [planText, setPlanText] = useState('');
  const [baseRevision, setBaseRevision] = useState(0);
  const [combinationText, setCombinationText] = useState(pretty([{ id: 'body', hook_id: null, visual_title_id: null, use_title: false }]));
  const [jobs, setJobs] = useState<Record<string, Job>>({});
  const [jobId, setJobId] = useState('');
  const [polling, setPolling] = useState(true);
  const [active, setActive] = useState(AppState.currentState === 'active');
  const [busy, setBusy] = useState<string[]>([]);
  const [logs, setLogs] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [transfer, setTransfer] = useState('Idle');
  const pause = useRef(false);
  const [videoUrl, setVideoUrl] = useState('');
  const [templateText, setTemplateText] = useState('[]');
  const log = (label: string, result: unknown) => setLogs(previous => [`${label}\n${pretty(result)}`, ...previous].slice(0, 10));
  const api = () => new API(baseUrl, token, log, expoFetch as typeof fetch);
  const path = () => {
    if (!projectId || !token) throw new Error('Create a project or enter its project ID and token.');
    return `/projects/${projectId}`;
  };
  function persist(next: Journal) { saveJournal(next); journalRef.current = next; setJournal(next); }
  function updateProject(update: (entry: ProjectJournal) => ProjectJournal, id = projectId, url = baseUrl) {
    if (!id) return;
    const entries = journalRef.current.projects;
    const entry = entries.find(p => p.projectId === id && p.baseUrl === url) ?? { baseUrl: url, projectId: id, name, sources: [], jobs: [] };
    persist({ projects: [update(entry), ...entries.filter(p => !(p.projectId === id && p.baseUrl === url))] });
  }
  function rememberSource(next: SourceJournal, id = projectId, url = baseUrl) {
    updateProject(p => ({ ...p, sources: [next, ...p.sources.filter(s => s.sourceId !== next.sourceId)] }), id, url);
  }
  function setSource(next: SourceJournal) {
    localRef.current = next;
    setLocal(next); setAudioTimingText(pretty(next.audioTiming)); setSourceTimingText(pretty(next.timing)); setHookScriptsText(pretty(next.hookScripts));
  }
  function saveSourceChanges(captured: SourceJournal, changes: Partial<SourceJournal>, id = projectId, url = baseUrl) {
    updateProject(p => rememberSourceChanges(p, captured, changes), id, url);
    if (localRef.current.sourceId === captured.sourceId) {
      const next = { ...localRef.current, ...changes };
      localRef.current = next;
      setLocal(next);
      if (changes.audioTiming) setAudioTimingText(pretty(changes.audioTiming));
      if (changes.timing) setSourceTimingText(pretty(changes.timing));
      if (changes.hookScripts) setHookScriptsText(pretty(changes.hookScripts));
    }
  }
  function editPlan(plan: Plan, canonical = false) {
    if (!canonical && planText) { try { plan = remapDraftCaptions(JSON.parse(planText), plan); } catch {} }
    setPlanText(pretty(plan));
    updateProject(p => ({ ...p, planDraft: plan }));
  }
  const draft = (): Plan => { if (!planText) throw new Error('Load a plan first.'); return JSON.parse(planText); };
  async function run(label: string, action: () => Promise<unknown>) {
    setBusy(b => [...b, label]); setError('');
    try { await action(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(b => b.filter(v => v !== label)); }
  }
  const action = (label: string, fn: () => Promise<unknown>, disabled = false) => <View style={styles.button}><Button title={busy.includes(label) ? `${label}…` : label} disabled={disabled || busy.includes(label)} onPress={() => void run(label, fn)} /></View>;
  function rememberJob(result: JobCreated) {
    setJobId(result.job_id);
    setJobs(j => ({ ...j, [result.job_id]: { id: result.job_id, project_id: projectId, state: 'queued', stage: 'queued', progress: 0, result: null, error: null } }));
    updateProject(p => ({ ...p, jobs: Array.from(new Set([...p.jobs, result.job_id])) }));
  }
  async function fetchProject(loadPlan = false) {
    const result = await api().request<ProjectState>(path()); setProject(result);
    if (loadPlan) { setBaseRevision(result.plan.revision); editPlan(result.plan, true); }
    return result;
  }
  async function poll(id: string) {
    if (!id) throw new Error('Enter a job ID.');
    const result = await api().request<Job>(`/jobs/${id}`);
    setJobs(j => ({ ...j, [id]: result }));
    if (result.state === 'succeeded') {
      const media = urls(result.result).find(url => url.includes('/media/'));
      if (media) setVideoUrl(media);
    }
    return result;
  }
  useEffect(() => {
    try { const saved = readJournal(); journalRef.current = saved; setJournal(saved); } catch (e) { setError(`Read local journal: ${String(e)}`); }
    const subscription = AppState.addEventListener('change', state => { setActive(state === 'active'); if (state !== 'active') pause.current = true; });
    return () => subscription.remove();
  }, []);
  useEffect(() => {
    if (!polling || !active || !token) return;
    let checking = false;
    const interval = setInterval(async () => {
      if (checking) return;
      checking = true;
      try { for (const job of Object.values(jobs)) if (job.state === 'queued' || job.state === 'running') await poll(job.id); }
      catch (e) { setError(String(e)); }
      finally { checking = false; }
    }, 2000);
    return () => clearInterval(interval);
  }, [polling, active, token, baseUrl, jobs]);
  async function reopen(entry: ProjectJournal) {
    pause.current = true; setProjectId(entry.projectId); setBaseUrl(entry.baseUrl); setName(entry.name);
    const restoredToken = await readToken(entry.projectId);
    setToken(restoredToken); setProject(null); setJobs({});
    setSource(entry.sources[0] ?? source());
    setPlanText(entry.planDraft ? pretty(entry.planDraft) : ''); setBaseRevision(entry.planDraft?.revision ?? 0);
    setJobId(entry.jobs.at(-1) ?? '');
    if (restoredToken) {
      const restoredAPI = new API(entry.baseUrl, restoredToken, log, expoFetch as typeof fetch);
      const responses = await Promise.allSettled(entry.jobs.map(id => restoredAPI.request<Job>(`/jobs/${id}`)));
      const restoredJobs: Record<string, Job> = {};
      for (const response of responses) {
        if (response.status === 'fulfilled') restoredJobs[response.value.id] = response.value;
        else setError(String(response.reason));
      }
      setJobs(restoredJobs);
    }
  }
  function captionChange(caption: Caption, text: string, deleted = false) {
    const plan = draft();
    const clipIndex = plan.clips.findIndex(c => c.id === caption.clip_id);
    const clip = plan.clips[clipIndex];
    if (!clip) throw new Error('Caption clip is missing.');
    const offset = plan.clips.slice(0, clipIndex).reduce((sum, c) => sum + c.source_end_ms - c.source_start_ms, 0);
    const words = text.trim().split(/\s+/).filter(Boolean).map(text => ({ word_id: null, text }));
    const edit = {
      id: `edit_${caption.id}`, clip_id: clip.id,
      source_start_ms: clip.source_start_ms + caption.start_ms - offset,
      source_end_ms: clip.source_start_ms + caption.end_ms - offset,
      deleted, replaces_word_ids: caption.words.flatMap(w => w.word_id ? [w.word_id] : []), words,
      emphasis_word_id: null,
    };
    plan.caption_edits = [...plan.caption_edits.filter(e => e.id !== edit.id), edit];
    editPlan(plan);
  }
  let parsedPlan: Plan | null = null;
  try { parsedPlan = planText ? JSON.parse(planText) : null; } catch {}
  const recovered = unlinkedOriginals(journal.projects.flatMap(p => p.sources.flatMap(s => s.original ? [s.original.uri] : [])));
  const currentEntry = journal.projects.find(p => p.projectId === projectId && p.baseUrl === baseUrl);
  if (fontError) throw fontError;
  if (!fontsLoaded) return null;
  return <ScrollView contentContainerStyle={styles.page} keyboardShouldPersistTaps="handled">
    <StatusBar style="dark" />
    <Text style={styles.title}>editmaxxing endpoint lab</Text>
    <Text>Raw API controls. Provider credentials stay on the backend. Each request and failure appears below.</Text>
    {error ? <Text selectable style={styles.error}>{error}</Text> : null}
    <Text style={styles.section}>Connection and saved projects</Text>
    <Field label="API base URL" value={baseUrl} set={setBaseUrl} />
    <Text>Phone: use the computer's LAN address. Web: include this app's origin in backend CORS_ORIGINS.</Text>
    <Field label="Project name" value={name} set={setName} />
    <Field label="Target duration ms" value={target} set={setTarget} />
    {action('Health', () => api().request('/healthz'))}
    {action('Create project', async () => {
      const created = await api().request<ProjectCreated>('/projects', 'POST', { name, target_duration_ms: Number(target) });
      await saveToken(created.project_id, created.project_token);
      setProjectId(created.project_id); setToken(created.project_token); setProject(null); setPlanText(''); setJobs({}); setSource(source());
      updateProject(p => p, created.project_id);
    })}
    <Field label="Project ID" value={projectId} set={setProjectId} />
    <Field label="Project token" value={token} set={setToken} secure />
    {action('Remember connection', async () => { path(); await saveToken(projectId, token); updateProject(p => p); })}
    {journal.projects.map(entry => <View key={`${entry.baseUrl}/${entry.projectId}`}>{action(`Open ${entry.name} · ${entry.projectId.slice(-6)}`, () => reopen(entry))}</View>)}
    <Text style={styles.section}>Source and original</Text>
    {recovered.map(file => <View key={file.uri}>{action(`Recover saved ${file.name.slice(-30)}`, async () => { const next = { ...source(), original: await recoverOriginal(file) }; setSource(next); rememberSource(next); })}</View>)}
    <Text>Native file selection copies the original into Documents/originals before hashing. App removal or device loss can remove that local copy. Browser files require selection after reload. Server copies are temporary processing storage.</Text>
    <View style={styles.row}>{action('New body source', async () => setSource(source('body')))}{action('New hooks source', async () => { const next = source('hooks'); next.hookScripts = project?.hooks.map(h => ({ hook_id: h.id, text: h.proposed_text, capture_revision: h.capture_revision, action_start_ms: null })) ?? []; setSource(next); })}</View>
    {currentEntry?.sources.map(item => <View key={item.sourceId}>{action(`Select ${item.role} · ${item.sourceId.slice(-6)}`, async () => setSource(item))}</View>)}
    <Field label="Source ID" value={local.sourceId} set={sourceId => setLocal({ ...local, sourceId })} />
    <Text>Role: {local.role} · Registration: {local.registered ? 'registered' : 'pending'}</Text>
    <Field label="Source duration ms" value={String(local.duration)} set={value => setLocal({ ...local, duration: Number(value) })} />
    {action('Pick original video', async () => {
      const file = await pickFile('original', p => setTransfer(`Hashing original ${Math.round(p * 100)}%`));
      if (!file) return;
      if (local.registered && local.original?.sha256 !== file.sha256) throw new Error('Register a new source ID for a different original.');
      const metadata = extractionAvailable ? await inspectSource(file.uri) : null;
      const next = { ...local, original: file, ...(metadata ? { duration: metadata.duration_ms, timing: { ...local.timing, duration_ms: metadata.duration_ms } } : {}) }; setSource(next); rememberSource(next); setTransfer('Original selected');
    })}
    <Text selectable>{local.original ? `${local.original.name} · ${local.original.size} bytes\nSHA256 ${local.original.sha256}\n${Platform.OS === 'web' ? 'Selected in browser' : 'Saved on this phone'}` : 'Choose the original to compute the source fingerprint.'}</Text>
    {local.original && Platform.OS !== 'web' ? <Text selectable>{local.original.uri}</Text> : null}
    <Field label="Original timing manifest JSON" value={sourceTimingText} set={setSourceTimingText} multiline />
    <Field label="Ordered hook scripts JSON" value={hookScriptsText} set={setHookScriptsText} multiline />
    {action('Register source', async () => {
      if (!local.original) throw new Error('Choose an original first.');
      const request: SourceCreate = { source_id: local.sourceId, role: local.role, duration_ms: local.duration, fingerprint: local.original.sha256, timing: JSON.parse(sourceTimingText), hook_scripts: JSON.parse(hookScriptsText) };
      await api().request(`${path()}/sources`, 'POST', request);
      const next = { ...local, timing: request.timing, hookScripts: request.hook_scripts, registered: true }; setLocal(next); rememberSource(next);
    })}
    <Text style={styles.section}>Audio first</Text>
    <Text>Native extraction: {extractionAvailable ? 'iOS AVFoundation module available' : 'choose prepared audio, or install the iOS development build'}. Extraction creates mono AAC at 16 kHz with a separate decoded-audio timing map.</Text>
    {action('Extract original audio on iOS', async () => {
      if (!local.original) throw new Error('Select an original.');
      if (!local.registered) throw new Error('Register the source before extracting audio.');
      const result = await extractAudio(local.original.uri);
      if (Math.abs(result.source_duration_ms - local.duration) > 100) throw new Error(`Original duration is ${result.source_duration_ms} ms. Register that duration with a fresh source ID.`);
      saveSourceChanges(local, { audio: await extractedFile(result.uri), audioTiming: result.timing });
    }, !extractionAvailable)}
    {action('Pick prepared audio', async () => {
      const file = await pickFile('audio', p => setTransfer(`Hashing audio ${Math.round(p * 100)}%`));
      if (file) { saveSourceChanges(local, { audio: file }); setTransfer('Audio selected'); }
    })}
    <Text selectable>{local.audio ? `${local.audio.name} · ${local.audio.size} bytes\nSHA256 ${local.audio.sha256}` : 'Choose extracted audio from this original.'}</Text>
    <Field label="Audio extraction timing JSON" value={audioTimingText} set={setAudioTimingText} multiline />
    {action('Mark source as synthetic fixture', async () => { await api().request(`${path()}/sources/${local.sourceId}/fixture`, 'POST'); })}
    <Text>Fixture mode requires ENABLE_FIXTURES=true. It uses synthetic words and editorial choices with real media processing. Select it before uploading source audio.</Text>
    {action('Upload audio and analyze', async () => {
      if (!local.audio) throw new Error('Choose audio.');
      const next = { ...local, audioTiming: JSON.parse(audioTimingText) }; rememberSource(next); setLocal(next);
      const file = readFile(local.audio);
      const result = await api().request<JobCreated>(`${path()}/sources/${local.sourceId}/audio`, 'PUT', await file.read(0, file.size), { 'X-Content-SHA256': local.audio.sha256, 'X-Timing-Manifest': JSON.stringify(next.audioTiming) }); rememberJob(result);
    })}
    <Text>Upload the original alongside audio. Analysis completes after the video is ready and each cut boundary receives visual review.</Text>
    {action('Retry project analysis', async () => rememberJob(await api().request<JobCreated>(`${path()}/analysis`, 'POST')))}
    <Text style={styles.section}>Resumable original upload</Text>
    <Text>{transfer}</Text>
    <Text selectable>Upload ID: {local.uploadId ?? 'created on upload'}</Text>
    {action('Upload or resume original', async () => {
      path(); if (!local.original) throw new Error('Choose the original.');
      pause.current = false;
      const captured = { ...local }, capturedProject = projectId, capturedURL = baseUrl;
      const result = await api().uploadOriginal({
        projectId, sourceId: local.sourceId, file: readFile(local.original), sha256: local.original.sha256, uploadId: local.uploadId,
        remember: async uploadId => { saveSourceChanges(captured, { uploadId }, capturedProject, capturedURL); },
        progress: (done, total) => setTransfer(`Uploading for processing ${Math.round(done / total * 100)}% · ${done}/${total} bytes`), paused: () => pause.current,
      });
      if (result) { rememberJob(result); setTransfer('Original transferred. Server verification and normalization are queued.'); }
      else setTransfer('Paused. Resume sends unacknowledged parts.');
    })}
    {action('Pause transfer', async () => { pause.current = true; setTransfer('Pausing after the current part'); })}
    {action('Inspect upload', async () => { if (!local.uploadId) throw new Error('Start an upload first.'); await api().request(`${path()}/sources/${local.sourceId}/video/uploads/${local.uploadId}`); })}
    <Text style={styles.section}>Jobs and project state</Text>
    <View style={styles.row}><Text>Poll active jobs every two seconds</Text><Switch value={polling} onValueChange={setPolling} /></View>
    <Field label="Job ID" value={jobId} set={setJobId} />
    {action('Poll job', () => poll(jobId))}
    {action('Cancel job', async () => { await api().request(`/jobs/${jobId}/cancel`, 'POST'); await poll(jobId); })}
    {Object.values(jobs).map(job => <Text key={job.id} selectable>{job.id}: {job.state} · {job.stage} · {Math.round(job.progress * 100)}%{job.error ? `\n${pretty(job.error)}` : ''}</Text>)}
    {action('Inspect project', () => fetchProject())}
    {project ? <Text selectable style={styles.output}>{pretty({ sources: project.sources, hooks: project.hooks, proposals: project.proposals, feedback: project.feedback, expires_at: project.expires_at })}</Text> : null}
    <Text style={styles.section}>Plan and manual edits</Text>
    <Text>Load the server plan to replace this local draft. Saves send an explicit base revision. A 409 keeps the local draft available for review.</Text>
    {action('Load server plan into editor', () => fetchProject(true))}
    <Text>Base revision {baseRevision} · Draft duration {parsedPlan?.duration_ms ?? 0} ms</Text>
    <Field label="Plan JSON" value={planText} set={text => { setPlanText(text); try { updateProject(p => ({ ...p, planDraft: JSON.parse(text) })); } catch {} }} multiline />
    {parsedPlan?.clips.map((clip, index) => <View key={clip.id} style={styles.card}>
      <Text selectable>{index + 1}. {clip.role} {clip.id} · {clip.source_id}</Text>
      <Field label={`${clip.id} start ms`} value={String(clip.source_start_ms)} set={value => { const plan = draft(); plan.clips[index].source_start_ms = Number(value); editPlan(plan); }} />
      <Field label={`${clip.id} end ms`} value={String(clip.source_end_ms)} set={value => { const plan = draft(); plan.clips[index].source_end_ms = Number(value); editPlan(plan); }} />
      <View style={styles.row}>{action(`Move ${index + 1} up`, async () => { const plan = draft(); [plan.clips[index - 1], plan.clips[index]] = [plan.clips[index], plan.clips[index - 1]]; editPlan(plan); }, index === 0)}{action(`Remove clip ${index + 1}`, async () => { const plan = draft(); plan.clips.splice(index, 1); plan.caption_edits = plan.caption_edits.filter(e => e.clip_id !== clip.id); editPlan(plan); })}</View>
    </View>)}
    {parsedPlan?.captions.slice(0, 12).map(caption => <View key={caption.id} style={styles.card}>
      <Text>{caption.id} · {caption.start_ms}..{caption.end_ms} ms</Text>
      <Field label={`${caption.id} text`} value={(parsedPlan?.caption_edits.find(e => e.id === `edit_${caption.id}`)?.words ?? caption.words).map(w => w.text).join(' ')} set={value => { try { captionChange(caption, value); } catch (e) { setError(String(e)); } }} />
      {action(`Delete caption ${caption.id}`, async () => captionChange(caption, '', true))}
    </View>)}
    <Text>The first 12 captions have text controls. The JSON editor covers every caption, override, overlay, and audio setting.</Text>
    {action('Save plan revision', async () => { const saved = await api().request<Plan>(`${path()}/plan`, 'PUT', { base_revision: baseRevision, plan: draft() }); setBaseRevision(saved.revision); editPlan(saved, true); await fetchProject(); })}
    {action('Request rank proposal', async () => rememberJob(await api().request<JobCreated>(`${path()}/rank`, 'POST', { base_revision: baseRevision, target_duration_ms: Number(target), selected_hook_id: draft().selected_hook_id, dead_space_enabled: draft().dead_space.enabled })))}
    {project?.proposals.map(proposal => <View key={proposal.id}>{action(`Review proposal ${proposal.id.slice(-6)}`, async () => { setPlanText(pretty(proposal.plan)); setBaseRevision(proposal.base_revision); })}{action(`Apply proposal ${proposal.id.slice(-6)}`, async () => { const saved = await api().request<Plan>(`${path()}/plan`, 'PUT', { base_revision: proposal.base_revision, plan: proposal.plan, proposal_id: proposal.id }); setBaseRevision(saved.revision); editPlan(saved, true); await fetchProject(); })}</View>)}
    <Text style={styles.section}>Hook templates and combinations</Text>
    <Field label="Four visual title templates JSON" value={templateText} set={setTemplateText} multiline />
    {action('Save title templates', async () => { await api().request(`${path()}/templates`, 'PUT', { templates: JSON.parse(templateText) }); await fetchProject(); })}
    {project?.hooks.map(hook => <View key={hook.id} style={styles.card}>
      <Text selectable>{hook.id} · take {hook.take_id ?? 'recording required'}</Text>
      <Field label={`${hook.id} spoken text`} value={hook.proposed_text} set={value => setProject(p => p ? { ...p, hooks: p.hooks.map(h => h.id === hook.id ? { ...h, proposed_text: value } : h) } : p)} />
      {action(`Save suggestion ${hook.id.slice(-6)}`, async () => { await api().request(`${path()}/hooks/${hook.id}`, 'PUT', { proposed_text: hook.proposed_text }); await fetchProject(); })}
      {hook.candidates.map(candidate => <View key={candidate.take_id}>{action(`Select take ${candidate.take_id.slice(-6)} · ${Math.round(candidate.confidence * 100)}%`, async () => { await api().request(`${path()}/hooks/${hook.id}`, 'PUT', { take_id: candidate.take_id }); await fetchProject(); })}</View>)}
      {project.titles.map(title => <View key={title.id}><Text>{title.text} {title.missing_slots.length ? `· Missing: ${title.missing_slots.join(', ')}` : ''}</Text>{action(`Toggle ${hook.id.slice(-4)}/${title.id.slice(-4)}`, async () => {
        const selected: Combination[] = JSON.parse(combinationText);
        const matches = (c: Combination) => c.hook_id === hook.id && c.visual_title_id === title.id;
        setCombinationText(pretty(selected.some(matches) ? selected.filter(c => !matches(c)) : [...selected.filter(c => c.id !== 'body'), { id: `combo_${randomUUID().replace(/-/g, '')}`, hook_id: hook.id, visual_title_id: title.id, use_title: true }]));
      })}</View>)}
    </View>)}
    <Field label="Selected combinations JSON" value={combinationText} set={setCombinationText} multiline />
    <Text>Each combination produces a separate video with its selected hook first and the saved body edit. Supply a manual overlay in a combination to fill a title yourself.</Text>
    <View style={styles.row}>{(['draft', 'export'] as const).map(kind => <View key={kind}>{action(`Render ${kind}`, async () => rememberJob(await api().request<JobCreated>(`${path()}/renders`, 'POST', { plan_revision: baseRevision, kind, combinations: JSON.parse(combinationText) })))}</View>)}</View>
    <Text style={styles.section}>Playback</Text>
    <Field label="Video URL" value={videoUrl} set={setVideoUrl} />
    {videoUrl ? <><Video key={videoUrl} uri={videoUrl} />{action('Open video URL', () => Linking.openURL(videoUrl))}</> : null}
    {Object.values(jobs).flatMap(job => urls(job.result).map(url => <View key={`${job.id}/${url}`}>{action(`Play ${url.split('/').pop()?.split('?')[0]}`, async () => setVideoUrl(url))}</View>))}
    <Text style={styles.section}>Request log</Text>
    {action('Clear request log', async () => setLogs([]))}
    {logs.map((entry, index) => <Text key={index} selectable style={styles.output}>{entry}</Text>)}
  </ScrollView>;
}
const styles = StyleSheet.create({
  page: { padding: 20, paddingTop: 56, paddingBottom: 80, gap: 8, backgroundColor: '#f7f8fa', maxWidth: 1000, width: '100%', alignSelf: 'center' },
  title: { fontSize: 24, fontFamily: 'TikTokSansBold' }, section: { fontSize: 20, fontFamily: 'TikTokSansBold', marginTop: 24 },
  field: { gap: 4 }, input: { borderWidth: 1, borderColor: '#afb8c5', borderRadius: 4, backgroundColor: 'white', padding: 9, fontSize: 14, fontFamily: 'TikTokSans' },
  json: { minHeight: 110, maxHeight: 380, fontFamily: 'TikTokSans', textAlignVertical: 'top' },
  row: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 8 }, button: { marginVertical: 3 },
  output: { backgroundColor: '#e8edf4', padding: 12, fontFamily: 'TikTokSans', fontSize: 12 },
  error: { color: '#a11919', backgroundColor: '#ffeded', padding: 12 }, card: { borderWidth: 1, borderColor: '#c7ced9', padding: 12, gap: 6 },
  video: { width: '100%', height: 480, backgroundColor: '#111' },
});
