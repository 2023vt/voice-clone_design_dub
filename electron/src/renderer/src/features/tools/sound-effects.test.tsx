import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import '@/i18n';
import { apiJson } from '@/lib/api/client';
import { SoundEffects } from './sound-effects';

vi.mock('@/lib/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api/client')>()),
  apiJson: vi.fn(),
}));
vi.mock('@/components/audio-preview-button', () => ({
  AudioPreviewButton: ({ src }: { src: string }) => <span data-testid="preview">{src}</span>,
}));
vi.mock('@/components/save-audio-button', () => ({ SaveAudioButton: () => null }));

const base = {
  error: null,
  license: 'CC-BY-NC-SA-4.0',
  download_bytes: 4_480_000_000,
  max_seconds: 20,
  max_variations: 4,
};

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <SoundEffects />
    </QueryClientProvider>,
  );
}

describe('SoundEffects', () => {
  beforeEach(() => vi.mocked(apiJson).mockReset());

  it('asks before downloading and starts the install only on click', async () => {
    vi.mocked(apiJson).mockImplementation(async (path) =>
      path === '/sfx/install'
        ? { ...base, ready: false, stage: 'installing' }
        : { ...base, ready: false, stage: 'idle' },
    );
    renderPage();
    const install = await screen.findByRole('button', { name: /Install sound effects/ });
    expect(screen.getByText(/4\.5 GB/)).toBeInTheDocument();
    expect(apiJson).not.toHaveBeenCalledWith('/sfx/install', expect.anything());
    fireEvent.click(install);
    await waitFor(() =>
      expect(apiJson).toHaveBeenCalledWith('/sfx/install', { method: 'POST' }),
    );
    expect(await screen.findByRole('button', { name: /Installing/ })).toBeDisabled();
  });

  it('generates the chosen number of takes and lists them', async () => {
    vi.mocked(apiJson).mockImplementation(async (path) =>
      path === '/sfx/generate'
        ? {
            prompt: 'Heavy rain on a tin roof',
            takes: [
              { id: 'a', audio_url: '/audio/a.wav', duration_s: 5 },
              { id: 'b', audio_url: '/audio/b.wav', duration_s: 5 },
            ],
          }
        : { ...base, ready: true, stage: 'ready' },
    );
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: /Heavy rain on a tin roof/ }));
    fireEvent.click(screen.getByRole('button', { name: '2' }));
    fireEvent.click(screen.getByRole('button', { name: /Generate sound effects/ }));
    expect(await screen.findAllByTestId('preview')).toHaveLength(2);
    const call = vi.mocked(apiJson).mock.calls.find(([path]) => path === '/sfx/generate');
    const body = call?.[1]?.body as FormData;
    expect(body.get('prompt')).toBe('Heavy rain on a tin roof');
    expect(body.get('variations')).toBe('2');
    expect(body.get('seconds')).toBe('5');
  });
});
