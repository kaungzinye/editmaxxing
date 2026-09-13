import React, { useEffect, useRef, useState } from 'react';
import { BackHandler, Linking, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useVideoPlayer, VideoView } from 'expo-video';
import { TEXT_HOOKS, VERBAL_HOOKS } from './hooks';
import type { Clip, EditProgress, VideoVersion } from './workflow';

const C = { ink: '#141414', red: '#F02D3A', muted: '#737373', line: '#EAEAEA', paper: '#FFFFFF', soft: '#F5F5F5' };
type Props = { versions: VideoVersion[]; body: Clip; progress: EditProgress; keptIds: string[] | null; activeId: string | null; onKeptChange: (ids: string[]) => void; onActiveChange: (id: string) => void; onBack: () => void; onEditHooks: () => void; onNewVideo: () => void };
const duration = (seconds: number) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;

function Playable({ uri, text, autoplay, onEnd }: { uri: string; text?: string; autoplay: boolean; onEnd: () => void }) {
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState(false);
  const player = useVideoPlayer(uri, p => { p.timeUpdateEventInterval = 0.2; if (autoplay) p.play(); });
  useEffect(() => {
    const time = player.addListener('timeUpdate', event => setSeconds(event.currentTime));
    const end = player.addListener('playToEnd', onEnd);
    const status = player.addListener('statusChange', event => setError(event.status === 'error'));
    return () => { time.remove(); end.remove(); status.remove(); };
  }, [player, onEnd]);
  return <>
    <VideoView player={player} style={StyleSheet.absoluteFill} contentFit="contain" nativeControls />
    {!!text && seconds < 4 && <View pointerEvents="none" style={s.videoText}><Text style={s.overlayText}>{text}</Text></View>}
    {error && <View style={[StyleSheet.absoluteFill, s.playError]}><Text style={s.lightText}>This clip could not play. Try recording it again.</Text></View>}
  </>;
}

function Preview({ version, body, height }: { version: VideoVersion; body: Clip; height: number }) {
  const [part, setPart] = useState<'opening' | 'body'>('opening');
  const [autoplay, setAutoplay] = useState(false);
  const uri = version.renderUri || (part === 'opening' ? version.take?.uri : body.uri);
  return <View style={s.previewArea}>
    <View style={[s.preview, { height, width: height * 9 / 16 }]}>
      {uri ? <Playable key={`${part}-${uri}`} uri={uri} text={!version.renderUri && part === 'opening' ? version.onScreen.line : undefined} autoplay={autoplay} onEnd={() => {
        if (!version.renderUri && part === 'opening' && body.uri) { setAutoplay(true); setPart('body'); }
      }} /> : <View style={s.demoCanvas}>
        <View style={s.canvasLine} /><View style={s.canvasCircle} />
        <Text style={s.demoEyebrow}>{part === 'opening' ? 'HOOK PREVIEW' : 'BODY PREVIEW'}</Text>
        <Text style={s.demoHook}>{part === 'opening' ? version.onScreen.line : body.name}</Text>
        <View style={s.demoFoot}><View style={s.tinyRed} /><Text style={s.demoFootText}>{body.demo ? 'Sample body' : 'Opening clip needed'}</Text></View>
      </View>}
      <View pointerEvents="none" style={s.previewTag}><Text style={s.previewTagText}>{version.renderUri ? 'FINAL VIDEO' : uri ? 'DEMO · UNRENDERED' : 'DEMO'}</Text></View>
    </View>
    <View style={s.timeline}>
      <Pressable disabled={!!version.renderUri} aria-disabled={!!version.renderUri} accessibilityRole="button" accessibilityLabel="Preview opening clip" onPress={() => { setPart('opening'); setAutoplay(false); }} style={s.openingSegment}><Text style={s.timelineLight}>Opening · {duration(version.take?.duration || 4)}</Text></Pressable>
      <Pressable disabled={!!version.renderUri} aria-disabled={!!version.renderUri} accessibilityRole="button" accessibilityLabel="Preview body clip" onPress={() => { setPart('body'); setAutoplay(false); }} style={s.bodySegment}><Text style={s.timelineText}>Body · {duration(body.duration)}</Text></Pressable>
    </View>
  </View>;
}

export default function FinalVideoScreen({ versions, body, progress, keptIds, activeId, onKeptChange, onActiveChange, onBack, onEditHooks, onNewVideo }: Props) {
  const kept = new Set(keptIds ?? versions.map(v => v.id));
  const [sheet, setSheet] = useState(false);
  const sheetRef = useRef<View>(null);
  const backgroundRef = useRef<View>(null);
  const [downloadError, setDownloadError] = useState('');
  const [availableHeight, setAvailableHeight] = useState(780);
  const version = versions.find(v => v.id === activeId) || versions[0];
  const selected = versions.filter(v => kept.has(v.id));
  const verbalIds = [...new Set(versions.map(v => v.spoken.id))];
  const textIds = [...new Set(versions.map(v => v.onScreen.id))];
  const index = version ? versions.indexOf(version) : 0;
  const pairing = (v: VideoVersion) => `V${VERBAL_HOOKS.findIndex(h => h.id === v.spoken.id) + 1} + T${TEXT_HOOKS.findIndex(h => h.id === v.onScreen.id) + 1}`;
  useEffect(() => {
    if (!sheet) return;
    const back = BackHandler.addEventListener('hardwareBackPress', () => { setSheet(false); return true; });
    if (Platform.OS !== 'web' || typeof document === 'undefined') return () => back.remove();
    const previous = document.activeElement as HTMLElement | null;
    const dialog = sheetRef.current as unknown as HTMLElement | null;
    const background = backgroundRef.current as unknown as HTMLElement | null;
    if (background) background.inert = true;
    const focusables = () => Array.from(dialog?.querySelectorAll<HTMLElement>('button, a[href], [tabindex="0"]') || []).filter(element => element.getAttribute('aria-disabled') !== 'true');
    focusables()[0]?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); setSheet(false); }
      if (event.key !== 'Tab') return;
      const items = focusables();
      const first = items[0], last = items[items.length - 1];
      if (!first) { event.preventDefault(); return; }
      if (event.shiftKey && (document.activeElement === first || !dialog?.contains(document.activeElement))) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && (document.activeElement === last || !dialog?.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
    };
    document.addEventListener('keydown', keydown);
    return () => { back.remove(); document.removeEventListener('keydown', keydown); if (background) background.inert = false; previous?.focus(); };
  }, [sheet]);
  async function save(v: VideoVersion) {
    if (!v.renderUri) return;
    try {
      if (Platform.OS === 'web' && typeof document !== 'undefined') {
        const link = document.createElement('a'); link.href = v.renderUri; link.download = `editmaxxing-${v.id}.mp4`; link.rel = 'noopener'; link.target = '_blank'; link.click();
      } else await Linking.openURL(v.renderUri);
    } catch { setDownloadError('Could not open this video. Please try again.'); }
  }
  if (!version) return <View style={s.empty}><Text style={s.title}>Choose your hooks first</Text><Text style={s.subtitle}>Your video versions will appear here.</Text><Pressable accessibilityRole="button" onPress={onEditHooks} style={s.cta}><Text style={s.ctaText}>Choose hooks</Text></Pressable></View>;
  return <View style={s.root} onLayout={event => setAvailableHeight(event.nativeEvent.layout.height)}>
    <View ref={backgroundRef} style={s.root} aria-hidden={sheet} importantForAccessibility={sheet ? 'no-hide-descendants' : 'auto'}>
    <View style={s.topbar}><Pressable accessibilityRole="button" accessibilityLabel="Back to hook recordings" onPress={onBack} style={s.back}><Text style={s.backArrow}>‹</Text><Text style={s.backText}>Retakes</Text></Pressable><Text style={s.step}>4 OF 4 · FINAL VIDEO</Text><Pressable accessibilityRole="button" onPress={onNewVideo} style={s.new}><Text style={s.backText}>New video</Text></Pressable></View>
    <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={s.content}>
      <View style={s.heading}><Text style={s.title}>Your final videos</Text><Text style={s.subtitle}>{verbalIds.length} verbal × {textIds.length} text = {versions.length} versions</Text></View>
      {progress.percent < 100 && <View style={s.progressBox}><View style={s.row}><Text style={s.progressText}>{progress.mode === 'demo' ? 'Demo · ' : ''}{progress.label}</Text><Text style={s.progressText}>{Math.max(0, Math.round(progress.percent))}%</Text></View><View style={s.progressTrack}><View style={[s.progressFill, { width: `${Math.min(100, Math.max(0, progress.percent))}%` }]} /></View></View>}
      <Preview key={version.id} version={version} body={body} height={Math.min(340, Math.max(200, availableHeight - (progress.percent < 100 ? 475 : 433)))} />
      <View style={s.versionHeading}><Text style={s.sectionTitle}>Version {index + 1}<Text style={s.ofCount}> / {versions.length}</Text></Text><Text style={s.pair}>{pairing(version)}</Text><Pressable accessibilityRole="button" onPress={onEditHooks} style={s.edit}><Text style={s.editText}>Edit hooks</Text></Pressable></View>
      <View style={s.hookSummary}><Text style={s.hookKind}>VERBAL</Text><Text numberOfLines={1} style={s.hookLine}>{version.spoken.line}</Text></View>
      <View style={s.hookSummary}><Text style={s.hookKind}>TEXT</Text><Text numberOfLines={2} style={s.hookLine}>{version.onScreen.line}</Text></View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={s.versions}>
        {versions.map((v, i) => <View key={v.id} style={[s.versionCard, v.id === version.id && s.versionActive]}>
          <Pressable accessibilityRole="button" accessibilityLabel={`Preview version ${i + 1}, ${pairing(v)}`} aria-selected={v.id === version.id} accessibilityState={{ selected: v.id === version.id }} onPress={() => onActiveChange(v.id)} style={s.versionTarget}><Text style={[s.versionNumber, v.id === version.id && s.redText]}>Version {i + 1}</Text><Text style={s.versionPair}>{pairing(v)}</Text></Pressable>
          <Pressable accessibilityRole="checkbox" accessibilityLabel={`Keep version ${i + 1} for download`} aria-checked={kept.has(v.id)} accessibilityState={{ checked: kept.has(v.id) }} style={s.checkTarget} onPress={() => { const next = new Set(kept); next.has(v.id) ? next.delete(v.id) : next.add(v.id); onKeptChange([...next]); }}><View style={[s.checkbox, kept.has(v.id) && s.checked]}>{kept.has(v.id) && <Text style={s.checkmark}>✓</Text>}</View></Pressable>
        </View>)}
      </ScrollView>
    </ScrollView>
    <View style={s.footer}><View style={s.row}><Text style={s.selectedText}>{selected.length} of {versions.length} selected</Text><Text style={s.previewNote}>{selected.every(v => !!v.renderUri) && selected.length ? 'Ready to save' : body.demo ? 'Demo preview' : 'Preview only'}</Text></View><Pressable accessibilityRole="button" aria-disabled={!selected.length} accessibilityState={{ disabled: !selected.length }} disabled={!selected.length} style={[s.cta, !selected.length && s.disabled]} onPress={() => { setDownloadError(''); setSheet(true); }}><Text style={s.downloadIcon}>↓</Text><Text style={s.ctaText}>Download selected{selected.length ? ` (${selected.length})` : ''}</Text></Pressable></View>
    </View>
    {sheet && <View style={[StyleSheet.absoluteFill, s.overlay]}>
      <View style={s.scrim}><Pressable style={StyleSheet.absoluteFill} accessibilityRole="button" accessibilityLabel="Close downloads" onPress={() => setSheet(false)} /><View ref={sheetRef} style={s.sheet} accessibilityViewIsModal role="dialog" aria-modal={true} accessibilityLabel="Your selected videos">
        <View style={s.sheetHandle} /><View style={s.row}><Text style={s.sheetTitle}>Your selected videos</Text><Pressable accessibilityRole="button" accessibilityLabel="Close downloads" onPress={() => setSheet(false)} style={s.close}><Text style={s.closeText}>×</Text></Pressable></View>
        <Text style={s.sheetDescription}>{selected.some(v => !v.renderUri) ? 'These are previews. Final video rendering is not connected yet. Downloads will be available when your videos are rendered.' : 'Save each finished video below.'}</Text>
        <ScrollView style={s.downloadList}>{selected.map(v => <View key={v.id} style={s.downloadRow}><View style={s.downloadCopy}><Text style={s.sectionTitle}>Version {versions.indexOf(v) + 1} · {pairing(v)}</Text><Text numberOfLines={2} style={s.downloadLine}>{v.onScreen.line}</Text></View>{v.renderUri ? <Pressable accessibilityRole="button" accessibilityLabel={`Save version ${versions.indexOf(v) + 1}`} onPress={() => void save(v)} style={s.save}><Text style={s.saveText}>Save ↓</Text></Pressable> : <Text style={s.pending}>Preview</Text>}</View>)}</ScrollView>
        {!!downloadError && <Text accessibilityRole="alert" style={s.error}>{downloadError}</Text>}
        <Pressable accessibilityRole="button" onPress={() => setSheet(false)} style={s.done}><Text style={s.ctaText}>Back to videos</Text></Pressable>
      </View></View>
    </View>}
  </View>;
}

const s = StyleSheet.create({
  overlay: { zIndex: 30 }, root: { flex: 1, backgroundColor: C.paper }, topbar: { height: 49, paddingHorizontal: 18, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', borderBottomWidth: 1, borderBottomColor: C.line }, back: { flexDirection: 'row', gap: 4, alignItems: 'center', minHeight: 44 }, backArrow: { fontSize: 31, color: C.ink, marginTop: -3 }, backText: { fontSize: 11, fontWeight: '600', color: C.ink }, step: { fontSize: 9, letterSpacing: 1.1, color: C.muted, fontWeight: '600' }, new: { minHeight: 44, justifyContent: 'center' }, content: { paddingHorizontal: 20, paddingBottom: 10 }, heading: { marginTop: 16, marginBottom: 14 }, title: { fontSize: 26, fontWeight: '700', letterSpacing: -0.9, color: C.ink }, subtitle: { marginTop: 5, fontSize: 12, color: C.muted }, progressBox: { marginBottom: 12, gap: 6 }, row: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }, progressText: { color: C.muted, fontSize: 10 }, progressTrack: { height: 3, backgroundColor: C.line, borderRadius: 2, overflow: 'hidden' }, progressFill: { height: 3, backgroundColor: C.red }, previewArea: { alignItems: 'center' }, preview: { borderRadius: 13, overflow: 'hidden', backgroundColor: '#1C1D20' }, demoCanvas: { flex: 1, justifyContent: 'center', padding: 17, overflow: 'hidden', backgroundColor: '#1C1D20' }, canvasLine: { position: 'absolute', width: 1, backgroundColor: '#343539', height: '100%', left: '72%' }, canvasCircle: { position: 'absolute', width: 240, height: 240, borderRadius: 120, borderColor: '#2E3035', borderWidth: 42, right: -125, bottom: -125 }, demoEyebrow: { fontSize: 7, letterSpacing: 1.6, fontWeight: '600', color: '#A1A1A6', marginBottom: 12 }, demoHook: { color: C.paper, fontSize: 17, lineHeight: 23, fontWeight: '700', letterSpacing: -0.3 }, demoFoot: { position: 'absolute', bottom: 15, left: 17, flexDirection: 'row', gap: 5, alignItems: 'center' }, tinyRed: { width: 4, height: 4, backgroundColor: C.red, borderRadius: 2 }, demoFootText: { color: '#A1A1A6', fontSize: 8 }, previewTag: { position: 'absolute', top: 10, left: 10, paddingHorizontal: 6, paddingVertical: 4, borderRadius: 4, backgroundColor: '#00000090' }, previewTagText: { color: '#FFFFFF', fontSize: 7, letterSpacing: 0.8, fontWeight: '600' }, videoText: { position: 'absolute', top: '18%', left: 12, right: 12, backgroundColor: '#0000008A', borderRadius: 5, padding: 8 }, overlayText: { color: '#FFF', fontSize: 14, lineHeight: 19, fontWeight: '700', textAlign: 'center' }, playError: { justifyContent: 'center', padding: 18, backgroundColor: '#141414DE' }, lightText: { color: '#FFF', fontSize: 12, lineHeight: 18 }, timeline: { flexDirection: 'row', alignSelf: 'stretch', gap: 3, marginTop: 10 }, openingSegment: { flex: 1, minHeight: 44, backgroundColor: C.red, borderRadius: 5, justifyContent: 'center', paddingHorizontal: 8 }, bodySegment: { flex: 2, minHeight: 44, backgroundColor: '#EEEEEE', borderRadius: 5, justifyContent: 'center', paddingHorizontal: 8 }, timelineLight: { fontSize: 9, fontWeight: '600', color: C.paper }, timelineText: { fontSize: 9, fontWeight: '600', color: '#616161' }, versionHeading: { flexDirection: 'row', alignItems: 'center', marginTop: 5 }, sectionTitle: { color: C.ink, fontSize: 12, fontWeight: '600' }, ofCount: { color: C.muted, fontWeight: '400' }, pair: { marginLeft: 9, fontSize: 9, color: C.muted, backgroundColor: C.soft, paddingHorizontal: 6, paddingVertical: 4, borderRadius: 4 }, edit: { marginLeft: 'auto', minHeight: 44, justifyContent: 'center' }, editText: { fontSize: 11, fontWeight: '600', color: C.ink }, hookSummary: { flexDirection: 'row', alignItems: 'baseline', gap: 9, marginBottom: 6 }, hookKind: { fontSize: 8, letterSpacing: 0.5, color: C.muted, width: 40 }, hookLine: { flex: 1, fontSize: 11, lineHeight: 16, color: '#505050' }, versions: { gap: 7, paddingTop: 8, paddingBottom: 2 }, versionCard: { flexDirection: 'row', width: 122, height: 62, borderRadius: 9, borderWidth: 1, borderColor: C.line, backgroundColor: C.paper }, versionActive: { borderColor: C.red, backgroundColor: '#FFF7F8' }, versionTarget: { paddingLeft: 10, flex: 1, justifyContent: 'center', gap: 5 }, versionNumber: { color: C.ink, fontSize: 11, fontWeight: '600' }, redText: { color: C.red }, versionPair: { fontSize: 9, color: C.muted }, checkTarget: { width: 44, minHeight: 44, alignItems: 'center', justifyContent: 'center' }, checkbox: { width: 17, height: 17, borderRadius: 5, borderWidth: 1, borderColor: '#BBBBBB', alignItems: 'center', justifyContent: 'center' }, checked: { backgroundColor: C.ink, borderColor: C.ink }, checkmark: { color: C.paper, fontSize: 11, fontWeight: '700' }, footer: { paddingHorizontal: 20, paddingTop: 10, paddingBottom: 13, borderTopWidth: 1, borderTopColor: C.line, gap: 9 }, selectedText: { fontSize: 11, color: C.ink, fontWeight: '600' }, previewNote: { fontSize: 10, color: C.muted }, cta: { minHeight: 47, backgroundColor: C.red, borderRadius: 10, alignItems: 'center', justifyContent: 'center', flexDirection: 'row', gap: 9 }, ctaText: { fontSize: 13, fontWeight: '600', color: C.paper }, downloadIcon: { color: C.paper, fontSize: 21 }, disabled: { opacity: 0.4 }, empty: { flex: 1, justifyContent: 'center', padding: 24, gap: 16 }, scrim: { flex: 1, justifyContent: 'flex-end', backgroundColor: '#00000065', alignItems: 'center' }, sheet: { width: '100%', maxWidth: 430, maxHeight: '78%', backgroundColor: C.paper, borderTopLeftRadius: 22, borderTopRightRadius: 22, paddingHorizontal: 20, paddingBottom: 28 }, sheetHandle: { width: 30, height: 4, borderRadius: 3, backgroundColor: '#D6D6D6', alignSelf: 'center', marginTop: 10, marginBottom: 7 }, sheetTitle: { fontSize: 20, fontWeight: '700', letterSpacing: -0.5, color: C.ink }, close: { width: 44, height: 44, alignItems: 'flex-end', justifyContent: 'center' }, closeText: { fontSize: 26, color: C.muted }, sheetDescription: { color: C.muted, fontSize: 12, lineHeight: 18, marginBottom: 15 }, downloadList: { maxHeight: 290 }, downloadRow: { paddingVertical: 12, borderTopWidth: 1, borderTopColor: C.line, flexDirection: 'row', alignItems: 'center', gap: 14 }, downloadCopy: { flex: 1, gap: 5 }, downloadLine: { color: C.muted, fontSize: 11, lineHeight: 16 }, pending: { fontSize: 10, color: C.muted }, save: { minHeight: 44, justifyContent: 'center' }, saveText: { color: C.red, fontWeight: '600', fontSize: 12 }, error: { color: C.red, fontSize: 12, marginTop: 10 }, done: { minHeight: 47, backgroundColor: C.ink, alignItems: 'center', justifyContent: 'center', borderRadius: 10, marginTop: 16 },
});
