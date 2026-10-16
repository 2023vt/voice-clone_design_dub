import { cleanup, render, screen, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, expect, it, vi } from 'vitest';

vi.mock('@/lib/api/client', () => ({
  apiJson: (path: string) =>
    Promise.resolve(
      path === '/api/settings/storage'
        ? {
            categories: [
              { id: 'hf_cache', path: 'C:\\models', bytes: 1 },
              { id: 'data', path: 'C:\\data', bytes: 1 },
              { id: 'engine_venvs', path: 'C:\\data\\engines', bytes: 1 },
            ],
            volumes: [],
            warnings: [],
          }
        : { available: false },
    ),
}));
vi.mock('@tanstack/react-router', () => ({
  Link: ({ children }: { children: React.ReactNode }) => <a>{children}</a>,
}));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('./models-directory-settings', () => ({
  ModelsDirectorySettings: () => <button>move-models</button>,
}));
vi.mock('./data-directory-settings', () => ({
  DataDirectorySettings: () => <button>move-data</button>,
}));
vi.mock('./privacy-settings', () => ({ HistoryRetention: () => null }));
vi.mock('./reset-settings', () => ({ ResetSettings: () => null }));
vi.mock('./uninstall-settings', () => ({ UninstallSettings: () => null }));

import { StorageSettings } from './storage-settings';

afterEach(cleanup);

it('places folder move controls in the matching Storage rows', async () => {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <StorageSettings />
    </QueryClientProvider>,
  );
  for (const [category, action] of [
    ['hf_cache', 'move-models'],
    ['data', 'move-data'],
    ['engine_venvs', 'move-data'],
  ]) {
    const heading = await screen.findByRole('heading', {
      name: `settings.storage_cat_${category}`,
    });
    expect(
      within(heading.parentElement!.parentElement!).getByRole('button', { name: action }),
    ).toBeTruthy();
  }
});
