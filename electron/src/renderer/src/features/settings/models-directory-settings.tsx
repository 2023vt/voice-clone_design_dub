import { ArrowRightIcon, FolderOpenIcon, HardDriveIcon, LoaderCircleIcon } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { getBridge } from '@/components/bridge';
import { Button } from '@/components/ui/button';
import { apiJson, describeError } from '@/lib/api/client';
import type { DataDirectorySelection, DataRelocationStage } from '../../../../preload/index.d';
import { fmtBytes } from '@shared/components/settings/models/format';
import { toast } from 'sonner';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { SettingsRow, SettingsSection } from './settings-layout';

interface ModelsDirectoryState {
  configured: string | null;
  effective?: string;
  default: string;
  restart_required: boolean;
}

const queryKey = ['models-directory'] as const;

function moveError(t: (key: string) => string, cause: unknown): string {
  const detail = describeError(cause);
  for (const code of [
    'target_not_empty',
    'nested_path',
    'insufficient_space',
    'local_only',
    'backend_not_managed',
    'authorization_expired',
    'backend_verification_failed',
  ]) {
    if (detail.includes(code)) return t(`settings.data_move_error_${code}`);
  }
  return t('settings.data_move_error');
}

export function ModelsDirectorySettings({ inline = false }: { inline?: boolean }) {
  const { t } = useTranslation();
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [selection, setSelection] = useState<DataDirectorySelection | null>(null);
  const [stage, setStage] = useState<DataRelocationStage | null>(null);
  const query = useQuery({
    queryKey,
    queryFn: ({ signal }) =>
      apiJson<ModelsDirectoryState>('/api/settings/storage/models-dir', { signal }),
  });
  const bridge = getBridge();
  useEffect(() => bridge?.maintenance?.onRelocationProgress?.(setStage), [bridge]);

  const chooseMove = async () => {
    if (!bridge || busy) return;
    try {
      const value = await bridge.maintenance.chooseModelsDirectory();
      if (value) setSelection(value);
    } catch (cause) {
      toast.error(moveError(t, cause));
    }
  };

  const move = async () => {
    if (!bridge || !selection || busy) return;
    setBusy(true);
    setStage('stopping');
    try {
      const result = await bridge.maintenance.relocateModelsDirectory(selection.authorization);
      setSelection(null);
      await Promise.all([
        client.invalidateQueries({ queryKey }),
        client.invalidateQueries({ queryKey: ['storage-report'] }),
        client.invalidateQueries({ queryKey: ['system-info'] }),
      ]);
      toast.success(t('settings.data_move_done', { path: result.path }));
      if (!result.removed_source) toast.warning(t('settings.data_move_old_copy'));
    } catch (cause) {
      toast.error(moveError(t, cause));
    } finally {
      setBusy(false);
      setStage(null);
    }
  };

  const save = async (reset: boolean) => {
    if (busy || !bridge?.files.authorizeModelsDirectory) return;
    setBusy(true);
    setError('');
    try {
      const selected = await bridge.files.authorizeModelsDirectory(reset);
      if (!selected) return;
      const next = await apiJson<ModelsDirectoryState>('/api/settings/storage/models-dir', {
        method: 'PUT',
        body: JSON.stringify({ authorization: selected.authorization }),
      });
      client.setQueryData(queryKey, next);
      await client.invalidateQueries({ queryKey });
    } catch (cause) {
      setError(describeError(cause));
    } finally {
      setBusy(false);
    }
  };

  const state = query.data;
  const path = state?.configured || state?.effective || state?.default;
  return (
    <>
      {!inline && (
        <SettingsSection icon={HardDriveIcon} title={t('settings.storage_cat_hf_cache')}>
          <SettingsRow
            id="models-directory"
            title={t('settings.storage_cat_hf_cache')}
            description={t('settings.storage_desc')}
          >
            <code
              title={path}
              className="min-w-0 max-w-full flex-1 truncate rounded-md border border-border/60 bg-muted/35 px-2.5 py-1.5 text-xs text-muted-foreground @2xl:max-w-[32rem]"
            >
              {query.isPending ? t('common.loading') : path}
            </code>
            {bridge && (
              <>
                {typeof bridge?.maintenance?.chooseModelsDirectory === 'function' && (
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy || query.isPending}
                    onClick={() => void chooseMove()}
                  >
                    <FolderOpenIcon />
                    {t('settings.data_move_choose')}
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy || query.isPending}
                  onClick={() => void save(false)}
                >
                  <FolderOpenIcon />
                  {t('settings.models_dir_choose')}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy || query.isPending || !state?.configured}
                  onClick={() => void save(true)}
                >
                  {t('preferences.reset')}
                </Button>
              </>
            )}
          </SettingsRow>
          {(query.isError || error) && (
            <div
              role="alert"
              className="flex items-center gap-2 px-4 py-3 text-sm text-destructive"
            >
              <span className="min-w-0 flex-1 break-words">{error || t('common.error')}</span>
              {query.isError && (
                <Button size="sm" variant="ghost" onClick={() => void query.refetch()}>
                  {t('common.retry')}
                </Button>
              )}
            </div>
          )}
          {state?.restart_required && (
            <p role="status" className="px-4 py-3 text-xs text-muted-foreground">
              {t('settings.compute_device_restart')}
            </p>
          )}
        </SettingsSection>
      )}
      {inline &&
        (bridge ? (
          <>
            {typeof bridge?.maintenance?.chooseModelsDirectory === 'function' && (
              <Button
                size="sm"
                variant="outline"
                disabled={busy || query.isPending}
                onClick={() => void chooseMove()}
              >
                <FolderOpenIcon />
                {t('settings.data_move_choose')}
              </Button>
            )}
            <Button
              size="sm"
              variant="ghost"
              disabled={busy || query.isPending}
              onClick={() => void save(false)}
            >
              <FolderOpenIcon />
              {t('settings.models_dir_choose')}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={busy || query.isPending || !state?.configured}
              onClick={() => void save(true)}
            >
              {t('preferences.reset')}
            </Button>
            {error && (
              <p role="alert" className="w-full text-xs text-destructive">
                {error}
              </p>
            )}
            {state?.restart_required && (
              <p role="status" className="w-full text-xs text-muted-foreground">
                {t('settings.compute_device_restart')}
              </p>
            )}
          </>
        ) : (
          <p className="text-xs text-muted-foreground">{t('settings.data_move_electron_only')}</p>
        ))}
      <Dialog
        open={Boolean(selection)}
        onOpenChange={(open) => !open && !busy && setSelection(null)}
      >
        <DialogContent showCloseButton={!busy} className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>{t('settings.storage_cat_hf_cache')}</DialogTitle>
            <DialogDescription>{t('settings.data_move_desc')}</DialogDescription>
          </DialogHeader>
          {selection && (
            <div className="space-y-3 rounded-xl border border-border/60 bg-muted/25 p-3.5">
              <div className="grid min-w-0 grid-cols-[1fr_auto_1fr] items-center gap-2">
                <code className="truncate text-xs text-muted-foreground" title={selection.source}>
                  {selection.source}
                </code>
                <ArrowRightIcon className="size-4 text-muted-foreground" />
                <code className="truncate text-xs" title={selection.target}>
                  {selection.target}
                </code>
              </div>
              <p className="text-xs text-muted-foreground">
                {t('settings.data_move_summary', {
                  size: fmtBytes(selection.size_bytes),
                  count: selection.file_count,
                })}
              </p>
            </div>
          )}
          {busy && stage && (
            <div role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
              <LoaderCircleIcon className="size-4 animate-spin" />
              {t(`settings.data_move_stage_${stage}`)}
            </div>
          )}
          <DialogFooter>
            <Button variant="ghost" disabled={busy} onClick={() => setSelection(null)}>
              {t('common.cancel')}
            </Button>
            <Button disabled={busy} onClick={() => void move()}>
              {busy ? <LoaderCircleIcon className="animate-spin" /> : <HardDriveIcon />}
              {busy ? t('settings.data_move_working') : t('settings.data_move_confirm')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
