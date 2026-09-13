import { requireOptionalNativeModule } from 'expo';
import type { TimingManifest } from '../../../contracts/plan';
export interface AudioExtraction {
  uri: string;
  source_duration_ms: number;
  timing: TimingManifest;
}
const module = requireOptionalNativeModule<{ extract(uri: string): Promise<AudioExtraction>; inspect(uri: string): Promise<{ duration_ms: number }> }>('SourceAudio');
export const extractionAvailable = Boolean(module);
export async function extractAudio(uri: string) {
  if (!module) throw new Error('Audio extraction requires the iOS development build. Choose prepared audio for web, Android, or Expo Go.');
  return module.extract(uri);
}

export async function inspectSource(uri: string) {
  if (!module) throw new Error('Source inspection requires the iOS development build.');
  return module.inspect(uri);
}
