import { Store } from '@tanstack/store';
import { useStore } from '@tanstack/react-store';
import type { GenerateResult } from '@/lib/api/types';
import { audioUrl } from '@/lib/api/client';
import { createObjectUrl, revokeObjectUrl } from '@/lib/audio/object-url';

/** One candidate voice rendered from the same description with its own seed. */
export interface DesignVariation {
  seed: number;
  /** Served take, when the backend kept one; otherwise the object URL. */
  src: string;
  objectUrl: string | null;
  durationSeconds: number | null;
}

export const designVariationsStore = new Store<DesignVariation[]>([]);

export function useDesignVariations(): DesignVariation[] {
  return useStore(designVariationsStore);
}

export function clearDesignVariations(): void {
  for (const variation of designVariationsStore.state) revokeObjectUrl(variation.objectUrl);
  designVariationsStore.setState(() => []);
}

export function addDesignVariation(result: GenerateResult, seed: number): void {
  const objectUrl = createObjectUrl(result.blob);
  const src = result.audioPath ? audioUrl(result.audioPath) : objectUrl;
  if (!src) return;
  designVariationsStore.setState((current) => [
    ...current,
    { seed: result.seed ?? seed, src, objectUrl, durationSeconds: result.durationSeconds },
  ]);
}
