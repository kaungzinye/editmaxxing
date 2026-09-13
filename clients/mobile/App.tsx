import { useEffect, useRef, useState } from 'react';
import {
  Alert, BackHandler, KeyboardAvoidingView, Linking, Platform, Pressable, ScrollView, StatusBar,
  StyleSheet, Text, TextInput, useWindowDimensions, View,
} from 'react-native';
import Svg, { Path } from 'react-native-svg';
import { SafeAreaProvider, useSafeAreaInsets } from 'react-native-safe-area-context';
import { CURIOSITY_RESEARCH, Hook, MOVEMENTS, TEXT_HOOKS, VERBAL_HOOKS, VerbalHook } from './hooks';
import { BodyCaptureScreen, HookCaptureScreen } from './CaptureScreen';
import FinalVideoScreen from './FinalVideoScreen';
import { buildVersions, Clip, demoProgress, EMPTY_PROGRESS, HookTake, Stage, takeFingerprint } from './workflow';

type Tab = 'verbal' | 'text';
type Edit = { kind: Tab | 'movement'; id: string; draft: string };
type Project = { verbal: VerbalHook[]; text: Hook[]; verbalIds: string[]; textIds: string[]; includePhysical: boolean };
type Details = { hook: Hook; kind: Tab };
const STORAGE_KEY = 'editmaxxing-hook-editor-v2';
const INITIAL: Project = {
  verbal: VERBAL_HOOKS, text: TEXT_HOOKS,
  verbalIds: ['verbal-1', 'verbal-2'], textIds: ['text-1', 'text-3', 'text-4'],
  includePhysical: true,
};

function loadProject(): Project {
  if (Platform.OS !== 'web') return INITIAL;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return INITIAL;
    const saved = JSON.parse(raw) as Project;
    const validHooks = (value: unknown, originals: Hook[], physical = false): boolean =>
      Array.isArray(value) && value.length === 4 && originals.every((original) =>
        value.some((item) => item.id === original.id && typeof item.line === 'string' &&
          item.line.trim().length > 0 && (!physical || typeof item.movement === 'string')));
    if (!validHooks(saved.verbal, VERBAL_HOOKS, true) || !validHooks(saved.text, TEXT_HOOKS) ||
      !Array.isArray(saved.verbalIds) || !Array.isArray(saved.textIds)) return INITIAL;
    return {
      includePhysical: typeof saved.includePhysical === 'boolean' ? saved.includePhysical : true,
      verbal: VERBAL_HOOKS.map((hook) => ({ ...hook,
        line: saved.verbal.find((item) => item.id === hook.id)!.line,
        movement: saved.verbal.find((item) => item.id === hook.id)!.movement })),
      text: TEXT_HOOKS.map((hook) => ({ ...hook, line: saved.text.find((item) => item.id === hook.id)!.line })),
      verbalIds: [...new Set(saved.verbalIds)].filter((id) => VERBAL_HOOKS.some((hook) => hook.id === id)),
      textIds: [...new Set(saved.textIds)].filter((id) => TEXT_HOOKS.some((hook) => hook.id === id)),
    };
  } catch { return INITIAL; }
}

export default function App() {
  return <SafeAreaProvider><HookEditor /></SafeAreaProvider>;
}

function HookEditor() {
  const insets = useSafeAreaInsets();
  const [project, setProject] = useState<Project>(loadProject);
  const [stage, setStage] = useState<Stage>('film');
  const [body, setBody] = useState<Clip | null>(null);
  const [takes, setTakes] = useState<HookTake[]>([]);
  const [keptVersionIds, setKeptVersionIds] = useState<string[] | null>(null);
  const [activeVersionId, setActiveVersionId] = useState<string | null>(null);
  const [editStartedAt, setEditStartedAt] = useState<number | null>(null);
  const [progress, setProgress] = useState(EMPTY_PROGRESS);
  const [tab, setTab] = useState<Tab>('verbal');
  const [edit, setEdit] = useState<Edit | null>(null);
  const [details, setDetails] = useState<Details | null>(null);
  const [review, setReview] = useState(false);
  const [saveStatus, setSaveStatus] = useState('Saved');
  const [notice, setNotice] = useState('');
  const scroll = useRef<ScrollView>(null);
  const { width, height } = useWindowDimensions();
  const desktop = width > 600;
  const verbal = project.verbal.filter((hook) => project.verbalIds.includes(hook.id));
  const text = project.text.filter((hook) => project.textIds.includes(hook.id));
  const pairs = buildVersions(verbal, text, project.includePhysical, takes);
  const hooks = tab === 'verbal' ? project.verbal : project.text;
  const selectedIds = tab === 'verbal' ? project.verbalIds : project.textIds;
  const overlay = Boolean(edit || details || review);

  useEffect(() => {
    if (editStartedAt === null) { setProgress(EMPTY_PROGRESS); return; }
    setProgress(demoProgress(Date.now() - editStartedAt));
    const timer = setInterval(() => {
      const next = demoProgress(Date.now() - editStartedAt);
      setProgress(next);
      if (next.status === 'complete') clearInterval(timer);
    }, 500);
    return () => clearInterval(timer);
  }, [editStartedAt]);

  useEffect(() => {
    if (Platform.OS === 'web' || overlay || stage === 'film') return;
    const subscription = BackHandler.addEventListener('hardwareBackPress', () => {
      setStage(stage === 'final' ? 'record-hooks' : stage === 'record-hooks' ? 'hooks' : 'film');
      return true;
    });
    return () => subscription.remove();
  }, [stage, overlay]);

  function confirmBody(clip: Clip) {
    setBody(clip);
    setTakes([]);
    setKeptVersionIds(null);
    setActiveVersionId(null);
    setEditStartedAt(Date.now());
    setProgress(demoProgress(0));
    setEdit(null);
    setDetails(null);
    setReview(false);
    setTab('verbal');
    setStage('hooks');
  }

  function saveTake(take: HookTake) {
    setTakes((current) => [...current.filter((item) => item.hookId !== take.hookId), take]);
  }

  function finishRecording(lastTake: HookTake) {
    const latest = [...takes.filter((take) => take.hookId !== lastTake.hookId), lastTake];
    if (pairs.length && verbal.every((hook) => latest.some((take) =>
      take.hookId === hook.id && take.fingerprint === takeFingerprint(hook, project.includePhysical)))) {
      setStage('final');
    }
  }

  function newVideo() {
    const reset = () => {
      if (Platform.OS === 'web') {
        [body, ...takes.map((take) => take.clip)].forEach((clip) => {
          if (clip?.uri?.startsWith('blob:')) URL.revokeObjectURL(clip.uri);
        });
      }
      setBody(null);
      setTakes([]);
      setKeptVersionIds(null);
      setActiveVersionId(null);
      setEditStartedAt(null);
      setStage('film');
    };
    if (Platform.OS === 'web') {
      if (window.confirm('Start a new video? The current clips will be cleared. Your saved hook choices will stay.')) reset();
    } else {
      Alert.alert('Start a new video?', 'The current clips will be cleared. Your saved hook choices will stay.', [
        { text: 'Cancel', style: 'cancel' }, { text: 'Start new video', style: 'destructive', onPress: reset },
      ]);
    }
  }

  useEffect(() => {
    if (Platform.OS !== 'web') { setSaveStatus('In this session'); return; }
    try { window.localStorage.setItem(STORAGE_KEY, JSON.stringify(project)); setSaveStatus('Saved'); }
    catch { setSaveStatus('Session only'); }
  }, [project]);

  useEffect(() => {
    if (!notice) return;
    const timeout = setTimeout(() => setNotice(''), 2800);
    return () => clearTimeout(timeout);
  }, [notice]);

  useEffect(() => {
    if (!overlay) return;
    const close = () => { setEdit(null); setDetails(null); setReview(false); };
    if (Platform.OS !== 'web') {
      const subscription = BackHandler.addEventListener('hardwareBackPress', () => { close(); return true; });
      return () => subscription.remove();
    }
    const previousFocus = document.activeElement as HTMLElement | null;
    const dialog = document.querySelector('[data-testid="hook-dialog"]');
    const controls = () => Array.from(dialog?.querySelectorAll<HTMLElement>('textarea, button, [role="button"], [role="link"], [tabindex="0"]') ?? [])
      .filter((element) => element.getAttribute('aria-disabled') !== 'true' && !element.hasAttribute('disabled') && element.offsetParent !== null);
    const items = controls();
    (dialog?.querySelector<HTMLElement>('textarea') ?? items[0])?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); close(); }
      if (event.key !== 'Tab') return;
      const targets = controls();
      if (!targets.length) return;
      const first = targets[0], last = targets[targets.length - 1];
      if (event.shiftKey && (document.activeElement === first || !dialog?.contains(document.activeElement))) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && (document.activeElement === last || !dialog?.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
    };
    // TextInput stops key bubbling on web, so dismissal and focus trapping use capture.
    window.addEventListener('keydown', keydown, true);
    return () => { window.removeEventListener('keydown', keydown, true); previousFocus?.focus(); };
  }, [overlay]);

  function switchTab(next: Tab) {
    setTab(next);
    scroll.current?.scrollTo({ y: 0, animated: false });
  }

  function toggle(id: string) {
    const key = tab === 'verbal' ? 'verbalIds' : 'textIds';
    setProject((current) => ({ ...current, [key]: current[key].includes(id)
      ? current[key].filter((item) => item !== id) : [...current[key], id] }));
  }

  function saveEdit() {
    if (!edit?.draft.trim()) return;
    const value = edit.draft.trim();
    if (edit.kind === 'text') {
      setProject((current) => ({ ...current, text: current.text.map((hook) => hook.id === edit.id ? { ...hook, line: value } : hook) }));
    } else {
      setProject((current) => ({ ...current, verbal: current.verbal.map((hook) => hook.id === edit.id
        ? { ...hook, [edit.kind === 'movement' ? 'movement' : 'line']: value } : hook) }));
    }
    setEdit(null);
    setNotice('Changes saved');
  }

  const editOriginal = edit?.kind === 'text'
    ? TEXT_HOOKS.find((hook) => hook.id === edit.id)?.line
    : edit?.kind === 'movement'
      ? VERBAL_HOOKS.find((hook) => hook.id === edit.id)?.movement
      : VERBAL_HOOKS.find((hook) => hook.id === edit?.id)?.line;
  const words = edit?.draft.trim().split(/\s+/).filter(Boolean).length ?? 0;
  const editTitle = edit?.kind === 'text' ? 'Edit on-screen text' : edit?.kind === 'movement' ? 'Edit physical hook' : 'Edit verbal hook';

  return (
    <View style={[s.canvas, { paddingTop: insets.top, paddingBottom: insets.bottom }]}>
      <StatusBar barStyle={stage === 'film' || stage === 'record-hooks' ? 'light-content' : 'dark-content'} />
      <View testID="editor-phone" style={[s.phone, desktop && s.desktopPhone, { height: desktop ? Math.min(900, height - 48) : height - insets.top - insets.bottom }]}>
        {stage === 'film' && <BodyCaptureScreen onConfirm={confirmBody} />}
        {stage === 'record-hooks' && <HookCaptureScreen hooks={verbal} includePhysical={project.includePhysical}
          takes={takes} onSaveTake={saveTake} onBack={() => setStage('hooks')} onComplete={finishRecording} />}
        {stage === 'final' && body && <FinalVideoScreen versions={pairs} body={body} progress={progress}
          keptIds={keptVersionIds} activeId={activeVersionId} onKeptChange={setKeptVersionIds} onActiveChange={setActiveVersionId}
          onBack={() => setStage('record-hooks')} onEditHooks={() => setStage('hooks')} onNewVideo={newVideo} />}
        {stage === 'hooks' && <>
        <View style={s.app} aria-hidden={overlay} accessibilityElementsHidden={overlay} importantForAccessibility={overlay ? 'no-hide-descendants' : 'auto'}>
          <View testID="editor-header">
          <View style={s.header}>
            <View style={s.brand}>
              <Pressable accessibilityRole="button" accessibilityLabel="Back to filming" onPress={() => setStage('film')} style={s.backButton}><View style={{ transform: [{ rotate: '180deg' }] }}><Icon name="arrow" size={20}/></View></Pressable>
              <Text style={s.title}>Choose hooks</Text>
            </View>
            <Text style={s.stepLabel}>2 of 4</Text>
          </View>
          <View style={s.editProgress} testID="editing-progress">
            <View style={s.progressLabels}>
              <View style={s.progressName}><Text style={s.progressText}>{progress.label}</Text><Text style={s.demoBadge}>Demo</Text></View>
              <Text style={s.progressPercent}>{progress.percent}%</Text>
            </View>
            <View accessibilityRole="progressbar" accessibilityLabel="Body editing progress, demo"
              accessibilityValue={{ min: 0, max: 100, now: progress.percent }} aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress.percent} style={s.progressTrack}>
              <View style={[s.progressFill, { width: `${progress.percent}%` }]} />
            </View>
          </View>

          <View style={s.tabs} accessibilityRole="tablist">
            {(['verbal', 'text'] as const).map((item) => <Pressable key={item}
              accessibilityRole="tab" aria-selected={tab === item} accessibilityState={{ selected: tab === item }}
              accessibilityLabel={item === 'verbal' ? 'Verbal hooks' : 'On-screen hooks'} onPress={() => switchTab(item)}
              style={[s.tab, tab === item && s.tabActive]}>
              <Icon name={item === 'verbal' ? 'mic' : 'text'} size={18} color={tab === item ? C.white : C.muted}/>
              <Text style={[s.tabText, tab === item && s.tabTextActive]}>{item === 'verbal' ? 'Verbal' : 'On-screen'}</Text>
              <View style={[s.tabCount, tab === item && s.tabCountActive]}><Text style={[s.tabCountText, tab === item && s.tabTextActive]}>{item === 'verbal' ? verbal.length : text.length}</Text></View>
            </Pressable>)}
          </View>

          <View style={s.listHeading}>
            <Pressable accessibilityRole="checkbox" aria-checked={project.includePhysical}
              accessibilityState={{ checked: project.includePhysical }} accessibilityLabel="Include physical hooks"
              hitSlop={{ top: 4, bottom: 4 }} style={s.physicalToggle}
              onPress={() => setProject((current) => ({ ...current, includePhysical: !current.includePhysical }))}>
              <View style={[s.optionCheckbox, project.includePhysical && s.optionCheckboxSelected]}>{project.includePhysical && <Icon name="check" size={13} color={C.white}/>}</View>
              <Text style={s.optionLabel}>Include physical hooks</Text>
            </Pressable>
            <Text style={s.listCount}>{selectedIds.length} of 4 selected</Text>
          </View>
          </View>
          <ScrollView ref={scroll} style={s.list} contentContainerStyle={s.listContent} showsVerticalScrollIndicator={false} keyboardShouldPersistTaps="handled">
            {hooks.map((hook, index) => {
              const selected = selectedIds.includes(hook.id);
              const original = (tab === 'verbal' ? VERBAL_HOOKS : TEXT_HOOKS).find((item) => item.id === hook.id)!;
              const edited = original.line !== hook.line;
              const physical = tab === 'verbal' && project.includePhysical ? hook as VerbalHook : undefined;
              return <View key={hook.id} testID={hook.id} style={[s.hook, selected && s.hookSelected]}>
                <View style={s.hookHeader}>
                  <Pressable accessibilityRole="checkbox" aria-checked={selected} accessibilityState={{ checked: selected }}
                    accessibilityLabel={`${tab === 'verbal' ? 'Verbal' : 'On-screen'} hook ${index + 1}`}
                    onPress={() => toggle(hook.id)} style={s.selectionTarget}>
                    <View style={[s.checkbox, selected && s.checkboxSelected]}>{selected && <Icon name="check" size={15} color={C.white}/>}</View>
                    <Text style={s.hookLabel}>{tab === 'verbal' ? 'Verbal' : 'On-screen'} {index + 1}</Text>
                    {edited && <Text style={s.edited}>Edited</Text>}
                  </Pressable>
                  <Pressable accessibilityRole="button" accessibilityLabel={`Edit ${tab === 'verbal' ? 'verbal hook' : 'on-screen hook'} ${index + 1}`}
                    onPress={() => setEdit({ kind: tab, id: hook.id, draft: hook.line })} style={s.editButton}>
                    <Icon name="edit" size={15} color={C.ink}/><Text style={s.editText}>Edit</Text>
                  </Pressable>
                </View>
                <Text style={[s.hookLine, tab === 'text' && s.onScreenLine]}>{hook.line}</Text>
                <Pressable accessibilityRole="button" accessibilityLabel={`Why ${tab === 'verbal' ? 'verbal' : 'on-screen'} hook ${index + 1} works`}
                  style={s.reason} onPress={() => setDetails({ hook, kind: tab })}>
                  <View style={s.reasonHeading}><Text style={s.reasonLabel}>{edited ? 'Original reasoning' : 'Why it works'}</Text><Icon name="chevron" size={13} color={C.muted}/></View>
                  <Text style={s.reasonText}>{hook.reason}</Text>
                </Pressable>
                {physical && <View style={s.movement}>
                  <View style={s.movementHead}><View style={s.movementLabel}><Icon name="movement" size={15} color={C.muted}/><Text style={s.movementTitle}>Physical hook</Text></View>
                    <Pressable accessibilityRole="button" accessibilityLabel={`Edit physical hook ${index + 1}`} style={s.movementEdit}
                      onPress={() => setEdit({ kind: 'movement', id: hook.id, draft: physical.movement })}><Text style={s.movementEditText}>Edit</Text><Icon name="edit" size={12} color={C.muted}/></Pressable></View>
                  <Text style={s.movementText}>{physical.movement}</Text>
                </View>}
              </View>;
            })}
          </ScrollView>

          <View style={s.footer}>
            <View style={s.summary}><Text style={s.sampleLabel}>Sample hooks · {saveStatus.toLowerCase()}</Text><Pressable accessibilityRole="button" accessibilityLabel={`Review ${pairs.length} combinations`} onPress={() => setReview(true)} style={s.versionsButton}><Text style={s.versionCount}>{verbal.length} × {text.length} = {pairs.length} versions</Text><Icon name="chevron" size={13}/></Pressable></View>
            <Pressable accessibilityRole="button" accessibilityLabel={tab === 'verbal' ? 'Choose on-screen text' : `Film ${verbal.length} ${verbal.length === 1 ? 'hook' : 'hooks'}`}
              aria-disabled={tab === 'verbal' ? !verbal.length : !pairs.length}
              disabled={tab === 'verbal' ? !verbal.length : !pairs.length}
              onPress={() => tab === 'verbal' ? switchTab('text') : setStage('record-hooks')}
              style={({ pressed }) => [s.primaryButton, pressed && s.pressed, (tab === 'verbal' ? !verbal.length : !pairs.length) && s.disabled]}>
              <Text style={s.primaryText}>{tab === 'verbal' ? 'Choose on-screen text' : pairs.length ? `Film ${verbal.length} ${verbal.length === 1 ? 'hook' : 'hooks'}` : 'Select at least one of each'}</Text><Icon name="arrow" size={18} color={C.white}/>
            </Pressable>
            {Platform.OS === 'web' ? <View style={s.homeIndicator}/> : <View style={{ height: 14 }}/ >}
          </View>
        </View>

        {!!notice && !overlay && <View style={s.toast} accessibilityLiveRegion="polite"><Icon name="check" color={C.white} size={15}/><Text style={s.toastText}>{notice}</Text></View>}

        {overlay && <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={s.overlay}>
          <Pressable accessibilityRole="button" accessibilityLabel="Close dialog" style={s.scrim}
            onPress={() => { setEdit(null); setDetails(null); setReview(false); }}/>
          <View testID="hook-dialog" role="dialog" aria-modal accessibilityLabel={edit ? editTitle : review ? 'Your combinations' : 'Behind this hook'} style={[s.sheet, review && s.reviewSheet]} accessibilityViewIsModal>
            <View style={s.sheetHandle}/>
            <View style={s.sheetHeader}><Text style={s.sheetTitle}>{edit ? editTitle : review ? 'Your combinations' : 'Behind this hook'}</Text>
              <Pressable accessibilityRole="button" accessibilityLabel="Close editor" style={s.closeButton}
                onPress={() => { setEdit(null); setDetails(null); setReview(false); }}><Icon name="close" size={20} color={C.ink}/></Pressable></View>

            {edit && <>
              <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={s.sheetContent}>
                {edit.kind !== 'movement' && <Text style={s.sheetDescription}>{edit.kind === 'text' ? 'Leave them with a question the body can answer.' : 'Keep it short. Write it the way you’d actually say it.'}</Text>}
                <TextInput accessibilityLabel={editTitle} multiline value={edit.draft} onChangeText={(draft) => setEdit({ ...edit, draft })}
                  style={[s.editorInput, edit.kind === 'movement' && s.movementInput]} maxLength={edit.kind === 'text' ? 260 : 180}
                  placeholder={edit.kind === 'movement' ? 'Describe your movement…' : 'Write your hook…'} placeholderTextColor={C.faint}/>
                <View style={s.editorMeta}><Text style={s.editorHint}>{edit.kind === 'movement' ? 'Body only · Zero props' : edit.kind === 'text' ? 'Aim for 10–22 words' : 'Aim for fewer than 12 words'}</Text><Text style={s.editorHint}>{words} {words === 1 ? 'word' : 'words'}</Text></View>
                {edit.kind === 'movement' ? <>
                  <Text style={s.suggestionsLabel}>Or try a simple action</Text>
                  {MOVEMENTS.map((movement) => <Pressable key={movement} accessibilityRole="button" onPress={() => setEdit({ ...edit, draft: movement })} style={[s.suggestion, edit.draft === movement && s.suggestionActive]}><Text style={s.suggestionText}>{movement}</Text><Icon name={edit.draft === movement ? 'check' : 'plus'} size={16} color={C.ink}/></Pressable>)}
                </> : <View style={s.editorReason}><Text style={s.detailLabel}>Keep the promise grounded</Text><Text style={s.detailBody}>Draw from your video. Let the verbal and on-screen hooks open different questions.</Text></View>}
                <Pressable accessibilityRole="button" onPress={() => setEdit({ ...edit, draft: editOriginal ?? '' })} style={s.restore}><Icon name="reset" size={14} color={C.muted}/><Text style={s.restoreText}>Restore suggestion</Text></Pressable>
              </ScrollView>
              <View style={s.sheetFooter}><Pressable accessibilityRole="button" onPress={() => setEdit(null)} style={s.secondaryButton}><Text style={s.secondaryText}>Cancel</Text></Pressable><Pressable accessibilityRole="button" aria-disabled={!edit.draft.trim()} accessibilityState={{ disabled: !edit.draft.trim() }} disabled={!edit.draft.trim()} onPress={saveEdit} style={[s.saveButton, !edit.draft.trim() && s.disabled]}><Text style={s.primaryText}>Save changes</Text></Pressable></View>
            </>}

            {details && <ScrollView contentContainerStyle={s.detailsContent}>
              <Text style={s.detailHook}>{details.hook.line}</Text>
              <Text style={s.detailLabel}>{(details.kind === 'verbal' ? VERBAL_HOOKS : TEXT_HOOKS).find((hook) => hook.id === details.hook.id)?.line !== details.hook.line ? 'Reasoning for the original suggestion' : details.hook.mechanism}</Text>
              <Text style={s.detailBody}>{details.hook.reason}</Text>
              <View style={s.evidence}><Text style={s.evidenceLabel}>{details.hook.source}</Text><Text style={s.evidenceText}>“{details.hook.evidence}”</Text></View>
              <Text style={s.detailLabel}>The psychology</Text><Text style={s.detailBody}>Information-gap theory links curiosity to a gap between what we know and what we want to know. Here, the hook creates a specific missing piece.</Text>
              <Pressable accessibilityRole="link" onPress={() => Linking.openURL(CURIOSITY_RESEARCH)} style={s.researchLink}><Text style={s.researchLinkText}>Loewenstein · The Psychology of Curiosity</Text><Icon name="external" size={14} color={C.link}/></Pressable>
            </ScrollView>}

            {review && <>
              <View style={s.reviewIntro}><Text style={s.reviewNumber}>{pairs.length}<Text style={s.reviewNumberLabel}> different openings</Text></Text><Text style={s.detailBody}>{verbal.length} verbal hooks × {text.length} on-screen texts. Each version shares the same body video.</Text></View>
              <ScrollView contentContainerStyle={s.reviewContent} showsVerticalScrollIndicator={false}>
                {pairs.map(({ spoken, onScreen }, index) => <View style={s.pair} key={`${spoken.id}-${onScreen.id}`}><View style={s.pairHeading}><Text style={s.pairTitle}>Version {index + 1}</Text><Text style={s.pairMeta}>V{project.verbal.indexOf(spoken) + 1} + T{project.text.indexOf(onScreen) + 1}</Text></View><View style={s.pairLine}><Icon name="mic" size={15} color={C.muted}/><Text style={s.pairVerbal}>{spoken.line}</Text></View><View style={s.pairLine}><Icon name="text" size={15} color={C.muted}/><Text style={s.pairText}>{onScreen.line}</Text></View>{project.includePhysical && <Text style={s.pairMovement}>{spoken.movement}</Text>}</View>)}
                <Text style={s.endNote}>You’ll record the verbal hooks next. Video export follows recording and editing.</Text>
              </ScrollView>
              <View style={s.sheetFooter}><Pressable accessibilityRole="button" style={s.secondaryButton} onPress={() => setReview(false)}><Text style={s.secondaryText}>Back to hooks</Text></Pressable><Pressable accessibilityRole="button" disabled={!pairs.length} aria-disabled={!pairs.length} style={[s.saveButton, !pairs.length && s.disabled]} onPress={() => { setReview(false); setStage('record-hooks'); }}><Text style={s.primaryText}>Film hooks</Text></Pressable></View>
            </>}
          </View>
        </KeyboardAvoidingView>}
        </>}
      </View>
    </View>
  );
}

type IconName = 'check' | 'play' | 'mic' | 'text' | 'edit' | 'bulb' | 'chevron' | 'movement' | 'layers' | 'arrow' | 'close' | 'plus' | 'reset' | 'external';
function Icon({ name, size = 20, color = '#141414' }: { name: IconName; size?: number; color?: string }) {
  const paths: Record<IconName, string> = {
    check: 'M5 12l4 4L19 6', play: 'M9 5l10 7-10 7Z',
    mic: 'M8 5a4 4 0 0 1 8 0v7a4 4 0 0 1-8 0V5ZM5 10v2a7 7 0 0 0 14 0v-2M12 19v3M8 22h8',
    text: 'M4 6V3h16v3M12 3v18M8 21h8',
    edit: 'm16 3 5 5M4 20l5-1L21 7a2 2 0 0 0 0-3l-1-1a2 2 0 0 0-3 0L5 15l-1 5Z',
    bulb: 'M9 18h6M10 21h4M8 14c-4-4-1-11 4-11s8 7 4 11l-1 2H9l-1-2Z',
    chevron: 'm9 5 7 7-7 7', movement: 'M4 14c2-4 4-6 7-5l4 3 5-3M4 19l6-3 4 3 6-4M12 5h.01',
    layers: 'm3 8 9-5 9 5-9 5-9-5Zm0 5 9 5 9-5M3 18l9 5 9-5',
    arrow: 'M4 12h16m-6-6 6 6-6 6', close: 'm6 6 12 12M6 18 18 6',
    plus: 'M12 5v14M5 12h14', reset: 'M3 10a9 9 0 1 1 1 8M3 4v6h6',
    external: 'M14 3h7v7M21 3 10 14M10 3H4a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h16a1 1 0 0 0 1-1v-6',
  };
  return <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" accessibilityElementsHidden>
    <Path d={paths[name]} stroke={name === 'play' ? 'none' : color} fill={name === 'play' ? color : 'none'} strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round"/>
  </Svg>;
}

const C = { white: '#FFFFFF', ink: '#141414', muted: '#6B6B6B', faint: '#999999', line: '#E9E9E9', surface: '#F5F5F5', red: '#F02D3A', softRed: '#FFF9F9', link: '#065FD4' };
const s = StyleSheet.create({
  canvas: { flex: 1, backgroundColor: '#EBECEF', alignItems: 'center', justifyContent: 'center' },
  phone: { width: '100%', maxWidth: 430, backgroundColor: C.white, overflow: 'hidden' },
  desktopPhone: { borderRadius: 30, borderWidth: 1, borderColor: '#D2D3D6', boxShadow: '0px 12px 44px rgba(0, 0, 0, 0.09)' },
  app: { flex: 1 },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingLeft: 4, paddingRight: 16, height: 44 },
  backButton: { width: 40, height: 44, alignItems: 'center', justifyContent: 'center' },
  stepLabel: { fontSize: 11, color: C.muted, fontWeight: '500' },
  editProgress: { paddingHorizontal: 16, paddingBottom: 2 },
  progressLabels: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 5 },
  progressName: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  progressText: { color: '#555555', fontSize: 11 },
  demoBadge: { color: C.muted, fontSize: 9, fontWeight: '600', backgroundColor: C.surface, paddingHorizontal: 5, paddingVertical: 2, borderRadius: 4 },
  progressPercent: { fontSize: 11, fontWeight: '700', fontVariant: ['tabular-nums'], color: C.ink },
  progressTrack: { height: 3, backgroundColor: '#EEEEEE', borderRadius: 2, overflow: 'hidden' },
  progressFill: { height: '100%', backgroundColor: C.red, borderRadius: 2 },
  brand: { flexDirection: 'row', gap: 6, alignItems: 'center' }, brandIcon: { width: 25, height: 19, borderRadius: 6, backgroundColor: C.red, alignItems: 'center', justifyContent: 'center' },
  brandName: { fontSize: 18, letterSpacing: -0.8, fontWeight: '800', color: C.ink },
  saved: { flexDirection: 'row', alignItems: 'center', gap: 4 }, savedText: { color: C.muted, fontSize: 11 },
  intro: { paddingHorizontal: 16, paddingTop: 4 },
  title: { fontSize: 21, lineHeight: 27, letterSpacing: -0.75, fontWeight: '700', color: C.ink },
  tabs: { marginHorizontal: 16, marginTop: 8, flexDirection: 'row', gap: 8 }, tab: { flex: 1, height: 44, borderRadius: 9, backgroundColor: C.surface, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 8 },
  tabActive: { backgroundColor: C.ink }, tabText: { color: C.muted, fontSize: 13, fontWeight: '600' }, tabTextActive: { color: C.white }, tabCount: { minWidth: 21, height: 21, paddingHorizontal: 5, borderRadius: 6, backgroundColor: '#E8E8E8', alignItems: 'center', justifyContent: 'center' }, tabCountActive: { backgroundColor: '#393939' }, tabCountText: { fontSize: 11, fontWeight: '600', color: C.muted },
  listHeading: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 16, height: 36, gap: 6 }, listCount: { fontSize: 11, color: C.muted },
  physicalToggle: { minHeight: 36, flexDirection: 'row', alignItems: 'center', gap: 7 },
  optionCheckbox: { width: 18, height: 18, borderWidth: 1.5, borderColor: '#BFBFBF', borderRadius: 5, alignItems: 'center', justifyContent: 'center' }, optionCheckboxSelected: { backgroundColor: C.ink, borderColor: C.ink }, optionLabel: { fontSize: 12, color: C.ink, fontWeight: '500' },
  list: { flex: 1 }, listContent: { paddingHorizontal: 12, paddingBottom: 12 },
  hook: { paddingHorizontal: 12, paddingTop: 0, paddingBottom: 12, borderWidth: 1, borderColor: C.line, borderRadius: 12, marginBottom: 8, backgroundColor: C.white },
  hookSelected: { borderColor: '#EDD5D7', backgroundColor: C.softRed }, hookHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 4 },
  selectionTarget: { flex: 1, minHeight: 44, flexDirection: 'row', alignItems: 'center', gap: 8 }, checkbox: { width: 21, height: 21, borderRadius: 6, borderWidth: 1.5, borderColor: '#CFCFCF', alignItems: 'center', justifyContent: 'center' }, checkboxSelected: { borderColor: C.red, backgroundColor: C.red }, hookLabel: { fontSize: 11, color: C.muted, fontWeight: '600' }, edited: { fontSize: 9, color: C.muted, backgroundColor: '#EFEFEF', paddingHorizontal: 5, paddingVertical: 2, borderRadius: 3 },
  editButton: { minHeight: 44, minWidth: 51, flexDirection: 'row', justifyContent: 'flex-end', alignItems: 'center', gap: 5 }, editText: { fontSize: 12, fontWeight: '600', color: C.ink },
  hookLine: { fontSize: 22, lineHeight: 28, letterSpacing: -0.55, fontWeight: '600', color: C.ink, marginTop: 2, marginBottom: 10 }, onScreenLine: { fontSize: 21, lineHeight: 27, letterSpacing: -0.4 },
  reason: { gap: 4 }, reasonHeading: { flexDirection: 'row', alignItems: 'center', gap: 5 }, reasonLabel: { color: C.muted, fontSize: 11, fontWeight: '600', flex: 1 }, reasonText: { fontSize: 13, lineHeight: 19, color: C.muted }, mechanism: { color: '#494949', fontWeight: '600' },
  movement: { marginTop: 10, paddingTop: 0, borderTopWidth: 1, borderTopColor: '#EBE5E5' }, movementHead: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }, movementLabel: { flexDirection: 'row', alignItems: 'center', gap: 5 }, movementTitle: { color: C.muted, fontSize: 11, fontWeight: '600' }, movementEdit: { height: 36, minWidth: 44, flexDirection: 'row', alignItems: 'center', justifyContent: 'flex-end', gap: 5 }, movementEditText: { fontSize: 12, color: C.muted }, movementText: { fontSize: 14, lineHeight: 20, fontWeight: '500', color: '#474747' },
  endNote: { fontSize: 11, lineHeight: 17, color: C.muted, marginHorizontal: 10, marginTop: 7, marginBottom: 10, textAlign: 'center' },
  footer: { borderTopWidth: 1, borderTopColor: C.line, backgroundColor: C.white, paddingHorizontal: 16, paddingTop: 10 }, summary: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10, gap: 4 }, summaryLeft: { flexDirection: 'row', alignItems: 'center', gap: 8 }, summaryText: { fontSize: 12, color: C.muted }, bold: { fontWeight: '700', color: C.ink }, multiply: { color: C.faint }, versionCount: { fontSize: 13, fontWeight: '700', color: C.ink },
  sampleLabel: { fontSize: 10, color: C.muted }, versionsButton: { flexDirection: 'row', alignItems: 'center', gap: 3, minHeight: 28, marginVertical: -5, paddingVertical: 5 },
  primaryButton: { minHeight: 46, backgroundColor: C.red, borderRadius: 10, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10, paddingHorizontal: 12 }, primaryText: { fontSize: 14, fontWeight: '600', color: C.white }, pressed: { opacity: 0.85 }, disabled: { backgroundColor: '#BDBDBD' }, homeIndicator: { width: 100, height: 4, borderRadius: 4, backgroundColor: C.ink, alignSelf: 'center', marginTop: 10, marginBottom: 7 },
  toast: { position: 'absolute', bottom: 143, alignSelf: 'center', backgroundColor: C.ink, borderRadius: 20, paddingHorizontal: 16, paddingVertical: 10, flexDirection: 'row', alignItems: 'center', gap: 7 }, toastText: { color: C.white, fontSize: 12 },
  overlay: { position: "absolute", top: 0, right: 0, bottom: 0, left: 0, justifyContent: 'flex-end' }, scrim: { position: "absolute", top: 0, right: 0, bottom: 0, left: 0, backgroundColor: 'rgba(0, 0, 0, 0.38)' }, sheet: { maxHeight: '92%', backgroundColor: C.white, borderTopLeftRadius: 23, borderTopRightRadius: 23, overflow: 'hidden' }, reviewSheet: { height: '90%' }, sheetHandle: { width: 34, height: 4, borderRadius: 3, backgroundColor: '#D9D9D9', alignSelf: 'center', marginTop: 9, marginBottom: 7 }, sheetHeader: { paddingLeft: 22, paddingRight: 12, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }, sheetTitle: { fontSize: 21, fontWeight: '700', letterSpacing: -0.65, color: C.ink }, closeButton: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  sheetContent: { paddingHorizontal: 22, paddingBottom: 15 }, sheetDescription: { fontSize: 13, lineHeight: 19, color: C.muted, marginBottom: 18 }, editorInput: { minHeight: 154, borderWidth: 1, borderColor: '#C9C9C9', borderRadius: 12, padding: 16, fontSize: 21, lineHeight: 28, fontWeight: '500', color: C.ink, textAlignVertical: 'top', backgroundColor: '#FCFCFC' }, movementInput: { minHeight: 106, fontSize: 17, lineHeight: 24 }, editorMeta: { flexDirection: 'row', justifyContent: 'space-between', marginTop: 9, gap: 8 }, editorHint: { fontSize: 10, color: C.muted }, suggestionsLabel: { fontSize: 12, fontWeight: '600', color: C.ink, marginTop: 23, marginBottom: 10 }, suggestion: { minHeight: 46, paddingHorizontal: 12, paddingVertical: 9, borderRadius: 9, backgroundColor: C.surface, marginBottom: 7, flexDirection: 'row', alignItems: 'center', gap: 10 }, suggestionActive: { backgroundColor: '#FCECEE' }, suggestionText: { fontSize: 12, lineHeight: 17, color: C.ink, flex: 1 }, editorReason: { marginTop: 23 }, restore: { flexDirection: 'row', alignItems: 'center', alignSelf: 'flex-start', gap: 6, minHeight: 44, marginTop: 12 }, restoreText: { fontSize: 11, color: C.muted },
  sheetFooter: { flexDirection: 'row', gap: 10, padding: 20, borderTopWidth: 1, borderTopColor: C.line }, secondaryButton: { minHeight: 48, flex: 1, borderWidth: 1, borderColor: C.line, borderRadius: 10, alignItems: 'center', justifyContent: 'center' }, secondaryText: { fontSize: 12, fontWeight: '600', color: C.ink }, saveButton: { minHeight: 48, flex: 1.4, backgroundColor: C.ink, borderRadius: 10, alignItems: 'center', justifyContent: 'center' },
  detailsContent: { paddingHorizontal: 22, paddingBottom: 30 }, detailHook: { fontSize: 21, lineHeight: 29, fontWeight: '600', color: C.ink, marginBottom: 24, letterSpacing: -0.4 }, detailLabel: { fontSize: 12, fontWeight: '700', color: C.ink, marginBottom: 7 }, detailBody: { fontSize: 13, lineHeight: 20, color: C.muted }, evidence: { padding: 15, borderRadius: 11, backgroundColor: C.surface, marginVertical: 23 }, evidenceLabel: { fontSize: 9, fontWeight: '600', color: C.muted, letterSpacing: 0.7, marginBottom: 9 }, evidenceText: { fontSize: 13, lineHeight: 20, color: '#494949' }, researchLink: { flexDirection: 'row', alignItems: 'center', gap: 8, minHeight: 44, marginTop: 5 }, researchLinkText: { fontSize: 11, lineHeight: 17, color: C.link, flex: 1 }, researchNote: { fontSize: 10, color: C.faint, lineHeight: 16 }, physicalDetail: { marginTop: 24, paddingTop: 19, borderTopWidth: 1, borderTopColor: C.line },
  reviewIntro: { paddingHorizontal: 22, paddingBottom: 20 }, reviewNumber: { fontSize: 34, fontWeight: '700', color: C.red, marginBottom: 8, letterSpacing: -1 }, reviewNumberLabel: { fontSize: 17, fontWeight: '600', color: C.ink, letterSpacing: -0.2 }, reviewContent: { paddingHorizontal: 22, paddingBottom: 10 }, pair: { paddingVertical: 17, borderTopWidth: 1, borderTopColor: C.line }, pairHeading: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 12 }, pairTitle: { fontSize: 11, fontWeight: '700', color: C.ink }, pairMeta: { fontSize: 10, color: C.muted }, pairLine: { flexDirection: 'row', gap: 10, alignItems: 'flex-start', marginBottom: 10 }, pairVerbal: { fontSize: 14, fontWeight: '600', color: C.ink, lineHeight: 20, flex: 1, marginTop: -2 }, pairText: { fontSize: 12, lineHeight: 18, color: C.muted, flex: 1, marginTop: -2 }, pairMovement: { fontSize: 10, lineHeight: 16, color: C.faint, marginLeft: 25 },
});
