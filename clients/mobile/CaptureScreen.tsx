import React, { useEffect, useRef, useState } from 'react';
import { AppState, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { CameraView, useCameraPermissions, useMicrophonePermissions } from 'expo-camera';
import * as ImagePicker from 'expo-image-picker';
import { useVideoPlayer, VideoView } from 'expo-video';
import Svg, { Path, Rect, Circle } from 'react-native-svg';
import type { VerbalHook } from './hooks';
import { Clip, HookTake, takeFingerprint } from './workflow';

const RED = '#F02D3A';
const time = (seconds: number) => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
type IconName = 'back' | 'flip' | 'grid' | 'upload' | 'camera' | 'check' | 'timer';
function Icon({ name, size = 24 }: { name: IconName; size?: number }) {
  return <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round">
    {name === 'back' && <Path d="M15 5l-7 7 7 7" />}
    {name === 'flip' && <><Path d="M20 8a8 8 0 00-14-3L3 8m0-5v5h5M4 16a8 8 0 0014 3l3-3m0 5v-5h-5" /></>}
    {name === 'grid' && <><Rect x="3" y="3" width="18" height="18" rx="2" /><Path d="M9 3v18M15 3v18M3 9h18M3 15h18" /></>}
    {name === 'upload' && <><Rect x="3" y="3" width="18" height="18" rx="4" /><Path d="M12 17V7m-4 4l4-4 4 4" /></>}
    {name === 'camera' && <><Rect x="2" y="5" width="20" height="15" rx="4" /><Circle cx="12" cy="12.5" r="4" /><Path d="M8 5l1-2h6l1 2" /></>}
    {name === 'check' && <Path d="M5 12l4 4L19 6" />}
    {name === 'timer' && <><Circle cx="12" cy="13" r="8" /><Path d="M9 2h6m-3 6v5l3 2" /></>}
  </Svg>;
}

function Playback({ uri }: { uri: string }) {
  const player = useVideoPlayer(uri, p => { p.loop = true; });
  const [error, setError] = useState(false);
  useEffect(() => {
    const listener = player.addListener('statusChange', event => setError(event.status === 'error'));
    return () => listener.remove();
  }, [player]);
  return <><VideoView player={player} style={StyleSheet.absoluteFill} contentFit="contain" nativeControls />
    {error && <View style={s.idle}><Text style={s.body}>This video cannot play here. Retake or upload another clip.</Text></View>}</>;
}

type CaptureProps = {
  title: string; subtitle: string; line?: string; movement?: string;
  initialClip?: Clip; confirmLabel: string; onUse: (clip: Clip) => void;
  onBack?: () => void; progress?: React.ReactNode;
};

function Capture({ title, subtitle, line, movement, initialClip, confirmLabel, onUse, onBack, progress }: CaptureProps) {
  const camera = useRef<CameraView>(null);
  const mounted = useRef(true);
  const recordingRef = useRef(false);
  const started = useRef(0);
  const [permission, requestCamera] = useCameraPermissions();
  const [microphone, requestMicrophone] = useMicrophonePermissions();
  const [enabled, setEnabled] = useState(false);
  const [ready, setReady] = useState(false);
  const [facing, setFacing] = useState<'front' | 'back'>('front');
  const [grid, setGrid] = useState(false);
  const [delay, setDelay] = useState(false);
  const [countdown, setCountdown] = useState<number | null>(null);
  const [duration, setDuration] = useState(line ? 15 : 60);
  const [recording, setRecording] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [clip, setClip] = useState<Clip | undefined>(initialClip);
  const [error, setError] = useState('');
  const active = enabled && !!permission?.granted && !!microphone?.granted && !clip;
  useEffect(() => {
    mounted.current = true;
    const subscription = AppState.addEventListener('change', state => {
      if (state !== 'active') { camera.current?.stopRecording(); setEnabled(false); setCountdown(null); }
    });
    return () => { mounted.current = false; camera.current?.stopRecording(); subscription.remove(); };
  }, []);
  useEffect(() => {
    if (!recording) return;
    const timer = setInterval(() => setElapsed((Date.now() - started.current) / 1000), 200);
    return () => clearInterval(timer);
  }, [recording]);
  useEffect(() => {
    if (countdown === null) return;
    const timer = setTimeout(() => {
      if (countdown === 1) { setCountdown(null); void record(); }
      else setCountdown(countdown - 1);
    }, 1000);
    return () => clearTimeout(timer);
  }, [countdown]);

  async function enableCamera() {
    if (Platform.OS === 'web') { setError('To record, open the mobile app. You can upload a video or try the demo here.'); return; }
    try {
      const cam = permission?.granted ? permission : await requestCamera();
      if (!cam.granted) { setError('Allow camera access in your device settings, or upload a video.'); return; }
      const mic = microphone?.granted ? microphone : await requestMicrophone();
      if (!mic.granted) { setError('Allow microphone access to record your voice, or upload a video.'); return; }
      if (mounted.current) { setError(''); setEnabled(true); }
    } catch { setError('Camera unavailable. Upload a video or try the demo.'); }
  }
  async function record() {
    if (!camera.current || !ready || recordingRef.current) return;
    recordingRef.current = true; setRecording(true); setError(''); setElapsed(0); started.current = Date.now();
    try {
      const result = await camera.current.recordAsync({ maxDuration: duration });
      if (mounted.current && result?.uri) setClip({ id: `clip-${Date.now()}`, uri: result.uri, duration: (Date.now() - started.current) / 1000, demo: false, name: line ? 'Hook take' : 'Body video' });
      else if (mounted.current) setError('No recording was saved. Please try again.');
    } catch { if (mounted.current) setError('Recording failed. Please try again or upload a video.'); }
    finally { recordingRef.current = false; if (mounted.current) setRecording(false); }
  }
  async function upload() {
    setError('');
    try {
      const result = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['videos'], allowsEditing: false });
      if (!result.canceled && mounted.current) {
        const asset = result.assets[0];
        setClip({ id: `upload-${Date.now()}`, uri: asset.uri, duration: (asset.duration ?? 0) / 1000, demo: false, name: asset.fileName || 'Uploaded video' });
      }
    } catch { if (mounted.current) setError('Could not open this video. Try another file.'); }
  }
  const demo = () => { setError(''); setClip({ id: `demo-${Date.now()}`, duration: line ? 5 : 42, demo: true, name: line ? 'Demo hook take' : 'Demo body video' }); };
  const busy = recording || countdown !== null;

  return <View style={s.screen}>
    <View style={s.header}>
      {onBack ? <Pressable accessibilityRole="button" accessibilityLabel="Back to hook selection" aria-disabled={busy} disabled={busy} onPress={onBack} style={[s.iconButton, busy && s.disabled]}><Icon name="back" /></Pressable> : <View style={s.brandMark}><Text style={s.brandLetter}>e</Text><View style={s.brandDot} /></View>}
      <View style={s.headerCopy}><Text style={s.headerTitle}>{clip ? 'Review your take' : title}</Text><Text style={s.muted}>{subtitle}</Text></View>
      <View style={s.badge}><View style={[s.statusDot, recording && { backgroundColor: RED }]} /><Text style={s.badgeText}>{recording ? 'REC' : clip?.demo ? 'DEMO' : '9:16'}</Text></View>
    </View>
    {progress}
    <View style={s.viewfinder}>
      {active && <CameraView ref={camera} style={StyleSheet.absoluteFill} facing={facing} mode="video" onCameraReady={() => setReady(true)} onMountError={() => { setEnabled(false); setError('Camera unavailable. Upload a video or try the demo.'); }} />}
      {!!line && !clip && <ScrollView style={[s.teleprompter, !active && s.teleprompterIdle]} contentContainerStyle={{ padding: 15 }}><Text style={s.eyebrow}>SAY THIS</Text><Text style={s.spoken}>“{line}”</Text>{movement && <Text style={s.movement}>{movement}</Text>}</ScrollView>}
      {clip?.uri ? <Playback uri={clip.uri} /> : clip?.demo ? <View style={s.idle}><View style={s.demoStamp}><Icon name="check" size={30} /></View><Text style={s.idleTitle}>Demo take ready</Text><Text style={s.body}>A sample to explore the flow.{'\n'}No video was recorded.</Text></View> : !active && <View style={s.idle}>
        {!line && <><View style={s.cameraGlyph}><Icon name="camera" size={32} /></View>
        <Text style={s.idleTitle}>Your story starts here.</Text>
        <Text style={s.body}>{'Film the main part of your video.\nWe’ll find the hooks next.'}</Text></>}
        <Pressable accessibilityRole="button" onPress={Platform.OS === 'web' ? upload : enableCamera} style={s.cameraButton}><Text style={s.cameraButtonText}>{Platform.OS === 'web' ? 'Upload a video' : 'Enable camera'}</Text></Pressable>
        <Pressable accessibilityRole="button" onPress={demo} style={s.demoButton}><Text style={s.demoText}>Try demo <Text style={{ color: RED }}>↗</Text></Text></Pressable>
      </View>}
      {grid && !clip && <View pointerEvents="none" style={StyleSheet.absoluteFill}>{[1, 2].map(n => <React.Fragment key={n}><View style={[s.gridV, { left: `${n * 100 / 3}%` }]} /><View style={[s.gridH, { top: `${n * 100 / 3}%` }]} /></React.Fragment>)}</View>}
      {!clip && <View style={s.rail}>
        <Pressable accessibilityRole="button" accessibilityLabel="Flip camera" aria-disabled={!active || busy} disabled={!active || busy} onPress={() => { setReady(false); setFacing(facing === 'front' ? 'back' : 'front'); }} style={[s.railButton, (!active || busy) && s.disabled]}><Icon name="flip" /><Text style={s.railLabel}>Flip</Text></Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel="Toggle camera grid" aria-selected={grid} accessibilityState={{ selected: grid }} onPress={() => setGrid(!grid)} style={s.railButton}><Icon name="grid" /><Text style={[s.railLabel, grid && { color: RED }]}>Grid</Text></Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel="Toggle three second timer" aria-selected={delay} aria-disabled={!active || busy} accessibilityState={{ selected: delay }} disabled={!active || busy} onPress={() => setDelay(!delay)} style={[s.railButton, (!active || busy) && s.disabled]}><Icon name="timer" /><Text style={s.railLabel}>{delay ? '3s' : 'Timer'}</Text></Pressable>
      </View>}
      {countdown !== null && <View pointerEvents="none" style={s.countdown}><Text style={s.countdownText}>{countdown}</Text></View>}
      {!!error && <View style={s.error}><Text accessibilityRole="alert" style={s.errorText}>{error}</Text></View>}
      {!clip && <View pointerEvents="none" style={s.viewfinderCaption}><Text style={s.caption}>{recording ? `${time(elapsed)} / ${time(duration)}` : active ? 'Keep it natural. Keep it you.' : Platform.OS === 'web' ? 'Camera recording is available in the mobile app' : 'Camera & microphone stay off until you enable them'}</Text></View>}
    </View>
    {clip ? <View style={s.reviewControls}>
      <View style={s.reviewMeta}><Text style={s.reviewTitle}>{clip.demo ? 'Demo' : 'Your take'}{clip.duration > 0 ? ` · ${time(clip.duration)}` : ''}</Text><Text style={s.muted}>{clip.demo ? 'Sample preview' : 'Play above to review'}</Text></View>
      <View style={s.reviewRow}><Pressable accessibilityRole="button" onPress={() => { setClip(undefined); setReady(false); setError(''); }} style={s.retake}><Text style={s.retakeText}>Retake</Text></Pressable><Pressable accessibilityRole="button" onPress={() => onUse(clip)} style={s.confirm}><Text style={s.confirmText}>{confirmLabel} →</Text></Pressable></View>
    </View> : <View style={s.controls}>
      <View style={s.durations}>{(line ? [15, 30, 60] : [15, 60, 180]).map(value => <Pressable key={value} accessibilityRole="button" aria-selected={duration === value} aria-disabled={busy} accessibilityState={{ selected: duration === value }} disabled={busy} onPress={() => setDuration(value)} style={[s.duration, duration === value && s.durationSelected]}><Text style={[s.durationText, duration === value && { color: '#141414' }]}>{value < 60 ? `${value}s` : `${value / 60}m`}</Text></Pressable>)}</View>
      <View style={s.shutterRow}>
        <Pressable accessibilityRole="button" aria-disabled={busy} disabled={busy} onPress={upload} style={[s.sideControl, busy && s.disabled]}><Icon name="upload" /><Text style={s.railLabel}>Upload</Text></Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel={recording ? 'Stop recording' : countdown ? 'Cancel countdown' : 'Record video'} onPress={() => { if (recording) camera.current?.stopRecording(); else if (countdown) setCountdown(null); else if (!active) void enableCamera(); else if (ready) delay ? setCountdown(3) : void record(); }} style={s.shutter}><View style={[s.shutterInner, recording && s.shutterStop]} /></Pressable>
        <Pressable accessibilityRole="button" aria-disabled={busy} disabled={busy} onPress={demo} style={[s.sideControl, busy && s.disabled]}><Text style={s.demoSmall}>DEMO</Text><Text style={s.railLabel}>Try demo</Text></Pressable>
      </View>
      <Text style={s.bottomLabel}>{countdown ? 'Tap to cancel' : recording ? 'Tap to stop' : active ? ready ? 'Tap to record' : 'Starting camera…' : 'FILM'}</Text>
    </View>}
  </View>;
}

export function BodyCaptureScreen({ onConfirm }: { onConfirm: (clip: Clip) => void }) {
  return <Capture title="Film your video" subtitle="First, the body. Then, the hooks." confirmLabel="Choose hooks" onUse={onConfirm} />;
}

export function HookCaptureScreen({ hooks, includePhysical, takes, onSaveTake, onBack, onComplete }: {
  hooks: VerbalHook[]; includePhysical: boolean; takes: HookTake[];
  onSaveTake: (take: HookTake) => void; onBack: () => void; onComplete: (lastTake: HookTake) => void;
}) {
  const [index, setIndex] = useState(0);
  const hook = hooks[Math.min(index, hooks.length - 1)];
  const matchingTake = (item: VerbalHook) => [...takes].reverse().find(t => t.hookId === item.id && t.fingerprint === takeFingerprint(item, includePhysical));
  const completed = hooks.filter(item => matchingTake(item)).length;
  if (!hook) return <View style={s.screen}><View style={s.idle}><Text style={s.idleTitle}>Choose a verbal hook first.</Text><Pressable onPress={onBack} style={s.cameraButton}><Text style={s.cameraButtonText}>Back to hooks</Text></Pressable></View></View>;
  const fingerprint = takeFingerprint(hook, includePhysical);
  return <Capture key={`${hook.id}:${fingerprint}`} title="Film your hooks" subtitle={`Hook ${index + 1} of ${hooks.length} · ${completed} saved`} line={hook.line} movement={includePhysical ? hook.movement : undefined} onBack={onBack} initialClip={matchingTake(hook)?.clip}
    confirmLabel={index === hooks.length - 1 ? 'See final videos' : 'Next hook'}
    onUse={clip => { const lastTake = { hookId: hook.id, fingerprint, clip }; onSaveTake(lastTake); if (index < hooks.length - 1) setIndex(index + 1); else onComplete(lastTake); }}
    progress={<View style={s.progress}>{hooks.map((item, i) => <View key={item.id} style={[s.progressSegment, matchingTake(item) ? { backgroundColor: '#FFFFFF' } : i === index ? { backgroundColor: RED } : undefined]} />)}</View>} />;
}

const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: '#141414' },
  header: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 18, paddingVertical: 12, gap: 10 },
  headerCopy: { flex: 1 }, headerTitle: { color: '#FFF', fontSize: 16, fontWeight: '700', letterSpacing: -.3 },
  muted: { color: '#A5A5A5', fontSize: 11, marginTop: 4 },
  brandMark: { width: 36, height: 44, justifyContent: 'center' }, brandLetter: { color: 'white', fontSize: 35, fontWeight: '900', fontStyle: 'italic' }, brandDot: { position: 'absolute', width: 6, height: 6, borderRadius: 3, backgroundColor: RED, right: 0, bottom: 8 },
  iconButton: { width: 44, height: 44, justifyContent: 'center', alignItems: 'center', marginLeft: -10 },
  badge: { flexDirection: 'row', alignItems: 'center', gap: 5, borderColor: '#454545', borderWidth: 1, paddingHorizontal: 8, paddingVertical: 6, borderRadius: 6 }, badgeText: { color: '#FFF', fontSize: 10, fontWeight: '700', letterSpacing: .5 }, statusDot: { width: 4, height: 4, borderRadius: 2, backgroundColor: '#A5A5A5' },
  viewfinder: { flex: 1, minHeight: 250, backgroundColor: '#202020', overflow: 'hidden', borderRadius: 16, marginHorizontal: 8 },
  idle: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 30, paddingBottom: 30 },
  cameraGlyph: { paddingBottom: 22, opacity: .65 }, idleTitle: { color: '#FFF', fontSize: 23, fontWeight: '700', letterSpacing: -.8, textAlign: 'center' }, body: { color: '#B1B1B1', fontSize: 13, lineHeight: 20, textAlign: 'center', marginTop: 10 },
  cameraButton: { minHeight: 44, paddingHorizontal: 23, borderRadius: 24, backgroundColor: '#FFF', justifyContent: 'center', marginTop: 24 }, cameraButtonText: { color: '#141414', fontWeight: '700', fontSize: 13 }, demoButton: { minHeight: 44, justifyContent: 'center', marginTop: 3 }, demoText: { color: '#FFF', fontSize: 13, fontWeight: '600' },
  rail: { position: 'absolute', right: 7, top: '44%', gap: 12 }, railButton: { width: 48, minHeight: 48, alignItems: 'center', justifyContent: 'center', gap: 5 }, railLabel: { color: '#FFF', fontSize: 10 }, disabled: { opacity: .28 },
  viewfinderCaption: { position: 'absolute', bottom: 14, left: 12, right: 12 }, caption: { textAlign: 'center', color: '#A5A5A5', fontSize: 10, lineHeight: 15 },
  controls: { paddingTop: 9, paddingBottom: 12 }, durations: { flexDirection: 'row', justifyContent: 'center', gap: 12 }, duration: { minWidth: 44, minHeight: 44, alignItems: 'center', justifyContent: 'center', borderRadius: 22 }, durationSelected: { backgroundColor: '#FFF' }, durationText: { color: '#FFF', fontSize: 12, fontWeight: '700' },
  shutterRow: { flexDirection: 'row', justifyContent: 'center', alignItems: 'center', gap: 45, marginTop: 13 }, shutter: { width: 78, height: 78, borderRadius: 40, borderColor: '#F02D3A99', borderWidth: 3, padding: 5, alignItems: 'center', justifyContent: 'center' }, shutterInner: { width: 62, height: 62, backgroundColor: RED, borderRadius: 32 }, shutterStop: { width: 30, height: 30, borderRadius: 6 }, sideControl: { width: 52, minHeight: 52, justifyContent: 'center', alignItems: 'center', gap: 7 }, demoSmall: { color: 'white', fontSize: 8, fontWeight: '800', letterSpacing: .7, borderWidth: 1, borderColor: '#777', borderRadius: 5, padding: 5 }, bottomLabel: { color: '#FFF', fontSize: 10, fontWeight: '700', letterSpacing: 1, textAlign: 'center', marginTop: 12 },
  teleprompter: { position: 'absolute', top: 15, left: 20, right: 20, maxHeight: '52%', backgroundColor: '#141414D9', borderRadius: 12 }, teleprompterIdle: { position: 'relative', top: 0, left: 0, right: 0, margin: 15, flexGrow: 0, flexShrink: 1 }, eyebrow: { color: '#AAA', fontSize: 9, fontWeight: '700', letterSpacing: 1.5, marginBottom: 7 }, spoken: { color: '#FFF', fontSize: 23, lineHeight: 29, letterSpacing: -.5, fontWeight: '700' }, movement: { color: '#C7C7C7', fontSize: 12, lineHeight: 17, marginTop: 9 },
  progress: { flexDirection: 'row', gap: 4, paddingHorizontal: 18, paddingBottom: 12 }, progressSegment: { height: 3, borderRadius: 2, backgroundColor: '#444', flex: 1 },
  demoStamp: { width: 64, height: 64, borderRadius: 32, backgroundColor: RED, alignItems: 'center', justifyContent: 'center', marginBottom: 22 }, reviewControls: { padding: 20, gap: 17 }, reviewMeta: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }, reviewTitle: { color: 'white', fontSize: 13, fontWeight: '600' }, reviewRow: { flexDirection: 'row', gap: 10 }, retake: { borderWidth: 1, borderColor: '#555', minHeight: 50, borderRadius: 13, paddingHorizontal: 22, justifyContent: 'center' }, retakeText: { color: '#FFF', fontSize: 14, fontWeight: '600' }, confirm: { flex: 1, minHeight: 50, backgroundColor: RED, borderRadius: 13, alignItems: 'center', justifyContent: 'center' }, confirmText: { color: '#FFF', fontSize: 14, fontWeight: '700' },
  error: { position: 'absolute', bottom: 38, left: 14, right: 14, padding: 12, borderRadius: 8, backgroundColor: '#491E24' }, errorText: { color: 'white', fontSize: 12, lineHeight: 18 },
  countdown: { position: 'absolute', top: 0, bottom: 0, left: 0, right: 0, justifyContent: 'center', alignItems: 'center', backgroundColor: '#0005' }, countdownText: { color: 'white', fontSize: 100, fontWeight: '700' }, gridV: { position: 'absolute', top: 0, bottom: 0, width: 1, backgroundColor: '#FFFFFF30' }, gridH: { position: 'absolute', left: 0, right: 0, height: 1, backgroundColor: '#FFFFFF30' },
});
