import { renderHook } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { useTtsLanguages } from './use-tts-languages';
const state = vi.hoisted(() => ({ remote: false, error: false, loading: false }));
vi.mock('./use-engines', () => ({
  useEngines: () => ({
    activeTts: { display_name: 'KittenTTS', supported_language_names: ['english'] },
  }),
}));
vi.mock('./use-compute-target', () => ({
  useComputeTarget: () => ({
    data: { active: { remote: state.remote, label: 'Worker' } },
    isError: state.error,
    isLoading: state.loading,
  }),
}));
it('distinguishes local support from unknown worker, loading and failed discovery', () => {
  const { result, rerender } = renderHook(() => useTtsLanguages());
  expect(result.current).toMatchObject({ names: ['english'], state: 'known' });
  state.remote = true;
  rerender();
  expect(result.current).toMatchObject({ names: null, state: 'unknown', modelLabel: 'Worker' });
  state.remote = false;
  state.loading = true;
  rerender();
  expect(result.current).toMatchObject({ names: null, state: 'loading' });
  state.loading = false;
  state.error = true;
  rerender();
  expect(result.current).toMatchObject({ names: null, state: 'error' });
});
