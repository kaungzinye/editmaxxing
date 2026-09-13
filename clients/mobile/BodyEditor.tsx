import { useState } from 'react';
import { Modal, Pressable, ScrollView, Text, View } from 'react-native';
import type { Plan, ProjectState } from '../../contracts/plan';

export default function BodyEditor({ project, draft, onSave, onClose, onDiscard }: {
  project: ProjectState; draft?: Plan; onSave(plan: Plan): Promise<void>; onClose(): void; onDiscard(): void;
}) {
  const [plan, setPlan] = useState(() => JSON.parse(JSON.stringify(draft ?? project.plan)) as Plan);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const clips = project.plan.clips.filter(c => c.role === 'body');
  const conflict = plan.revision !== project.plan.revision;
  async function save() {
    setBusy(true);
    try { await onSave(plan); onClose(); } catch (error) { setError(error instanceof Error ? error.message : String(error)); }
    finally { setBusy(false); }
  }
  return <Modal visible animationType="slide" onRequestClose={onClose}>
    <View style={{ flex: 1, padding: 24, paddingTop: 60, gap: 18 }}>
      <Text style={{ fontSize: 24, fontWeight: '700' }}>Edit shared body</Text>
      <Text>Select the passages to keep in every version.</Text>
      <ScrollView>{clips.map(clip => {
        const selected = plan.clips.some(c => c.id === clip.id);
        const text = project.words.filter(w => w.source_id === clip.source_id && w.start_ms < clip.source_end_ms && w.end_ms > clip.source_start_ms).map(w => w.text).join(' ');
        return <Pressable key={clip.id} accessibilityRole="checkbox" accessibilityState={{ checked: selected }} style={{ paddingVertical: 16 }}
          onPress={() => setPlan({ ...plan, clips: selected ? plan.clips.filter(c => c.id !== clip.id) : project.plan.clips.filter(c => c.id === clip.id || plan.clips.some(kept => kept.id === c.id)) })}>
          <Text>{selected ? '☑' : '☐'} {text}</Text><Text>{(clip.source_start_ms / 1000).toFixed(1)}–{(clip.source_end_ms / 1000).toFixed(1)}s</Text>
        </Pressable>;
      })}</ScrollView>
      {!!error && <Text accessibilityRole="alert">{error}</Text>}
      {conflict && <><Text>The saved body has another revision. Review it before saving your selection.</Text>
        <Pressable onPress={() => { onDiscard(); setPlan(JSON.parse(JSON.stringify(project.plan)) as Plan); setError(''); }}><Text>Load saved body</Text></Pressable>
        <Pressable onPress={() => setPlan({ ...project.plan, clips: project.plan.clips.filter(c => plan.clips.some(selected => selected.id === c.id)) })}><Text>Apply selection to saved body and review</Text></Pressable></>}
      <Pressable disabled={busy || conflict || !plan.clips.length} onPress={() => void save()}><Text>{busy ? 'Saving…' : 'Save body edit'}</Text></Pressable>
      <Pressable disabled={busy} onPress={onClose}><Text>Close</Text></Pressable>
    </View>
  </Modal>;
}
