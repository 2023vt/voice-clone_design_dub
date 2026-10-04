import { useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { DownloadIcon, LoaderCircleIcon, SparklesIcon } from 'lucide-react';
import { AudioPreviewButton } from '@/components/audio-preview-button';
import { PipelineFailure } from '@/components/pipeline-failure';
import { SaveAudioButton } from '@/components/save-audio-button';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { apiJson, audioUrl, describeError } from '@/lib/api/client';
import { cn } from '@/lib/utils';

interface SfxStatus {
  ready: boolean;
  stage: 'idle' | 'installing' | 'downloading' | 'done' | 'ready' | 'error';
  error: string | null;
  license: string;
  download_bytes: number;
  max_seconds: number;
  max_variations: number;
}

interface SfxTake {
  id: string;
  audio_url: string;
  duration_s: number | null;
}

const STATUS_KEY = ['sfx-status'];
const EXAMPLES = ['rain', 'door', 'crowd', 'whoosh', 'footsteps', 'thunder'] as const;
const VARIATION_CHOICES = [1, 2, 3, 4] as const;

function installing(stage: SfxStatus['stage'] | undefined) {
  return stage === 'installing' || stage === 'downloading';
}

/** Text → sound effects, rendered locally (ElevenLabs Sound Effects parity). */
export function SoundEffects() {
  const { t } = useTranslation();
  const client = useQueryClient();
  const status = useQuery({
    queryKey: STATUS_KEY,
    queryFn: () => apiJson<SfxStatus>('/sfx/status'),
    refetchInterval: (query) => (installing(query.state.data?.stage) ? 2000 : false),
  });
  const [prompt, setPrompt] = useState('');
  const [seconds, setSeconds] = useState('5');
  const [variations, setVariations] = useState<number>(4);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [takes, setTakes] = useState<{ prompt: string; items: SfxTake[] } | null>(null);
  const request = useRef<AbortController | null>(null);
  const data = status.data;
  const maxSeconds = data?.max_seconds ?? 20;
  const duration = Number(seconds);
  const valid = Boolean(prompt.trim()) && duration >= 1 && duration <= maxSeconds;

  const install = async () => {
    setError(null);
    try {
      client.setQueryData(STATUS_KEY, await apiJson<SfxStatus>('/sfx/install', { method: 'POST' }));
    } catch (failure) {
      setError(describeError(failure));
    }
  };

  const generate = async () => {
    if (request.current || !valid) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true);
    setError(null);
    try {
      const body = new FormData();
      body.set('prompt', prompt.trim());
      body.set('seconds', String(duration));
      body.set('variations', String(variations));
      const result = await apiJson<{ prompt: string; takes: SfxTake[] }>('/sfx/generate', {
        method: 'POST',
        body,
        signal: controller.signal,
      });
      setTakes({ prompt: result.prompt, items: result.takes });
    } catch (failure) {
      if (!controller.signal.aborted) setError(describeError(failure));
    } finally {
      request.current = null;
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div>
        <h2 className="text-lg font-medium">{t('soundEffects.title')}</h2>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          {t('soundEffects.description')}
        </p>
      </div>
      {error && <PipelineFailure fallback={error} onDismiss={() => setError(null)} />}
      {status.isPending ? (
        <p role="status" className="text-sm text-muted-foreground">
          {t('common.loading')}
        </p>
      ) : !data?.ready ? (
        <section className="space-y-3 rounded-xl border border-border/60 bg-muted/20 p-4">
          <p className="text-sm">
            {t('soundEffects.install_body', {
              size: ((data?.download_bytes ?? 0) / 1e9).toFixed(1),
              license: data?.license ?? '',
            })}
          </p>
          {data?.stage === 'error' && data.error && <PipelineFailure fallback={data.error} />}
          <Button disabled={installing(data?.stage)} onClick={() => void install()}>
            {installing(data?.stage) ? (
              <LoaderCircleIcon className="animate-spin motion-reduce:animate-none" />
            ) : (
              <DownloadIcon />
            )}
            {installing(data?.stage)
              ? t(
                  data?.stage === 'downloading'
                    ? 'soundEffects.downloading'
                    : 'soundEffects.installing',
                )
              : t('soundEffects.install')}
          </Button>
        </section>
      ) : (
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            void generate();
          }}
        >
          <label className="block space-y-2 text-sm">
            <span>{t('soundEffects.prompt_label')}</span>
            <textarea
              className="min-h-28 w-full resize-y rounded-lg border border-input bg-transparent p-3 leading-7 outline-none focus-visible:ring-2 focus-visible:ring-ring"
              maxLength={500}
              disabled={busy}
              value={prompt}
              placeholder={t('soundEffects.prompt_placeholder')}
              onChange={(event) => setPrompt(event.target.value)}
            />
          </label>
          <div className="flex flex-wrap gap-1">
            {EXAMPLES.map((example) => (
              <Button
                key={example}
                type="button"
                size="xs"
                variant="ghost"
                disabled={busy}
                onClick={() => setPrompt(t('soundEffects.example_' + example))}
              >
                <SparklesIcon />
                {t('soundEffects.example_' + example)}
              </Button>
            ))}
          </div>
          <div className="flex flex-wrap items-end gap-4">
            <label className="space-y-2 text-sm">
              <span>{t('soundEffects.seconds_label', { max: maxSeconds })}</span>
              <Input
                className="w-28"
                type="number"
                min={1}
                max={maxSeconds}
                step={0.5}
                disabled={busy}
                value={seconds}
                onChange={(event) => setSeconds(event.target.value)}
              />
            </label>
            <fieldset className="space-y-2 text-sm" disabled={busy}>
              <legend>{t('soundEffects.variations_label')}</legend>
              <div className="flex gap-1">
                {VARIATION_CHOICES.map((count) => (
                  <Button
                    key={count}
                    type="button"
                    size="sm"
                    variant={variations === count ? 'secondary' : 'ghost'}
                    aria-pressed={variations === count}
                    onClick={() => setVariations(count)}
                  >
                    {count}
                  </Button>
                ))}
              </div>
            </fieldset>
            <Button type="submit" disabled={busy || !valid}>
              {busy ? (
                <LoaderCircleIcon className="animate-spin motion-reduce:animate-none" />
              ) : (
                <SparklesIcon />
              )}
              {t(busy ? 'soundEffects.generating' : 'soundEffects.generate')}
            </Button>
          </div>
        </form>
      )}
      {takes && (
        <section
          aria-label={t('soundEffects.results')}
          className="space-y-2 rounded-xl border border-border/60 p-3"
        >
          <h3 className="text-sm font-medium">{t('soundEffects.results')}</h3>
          <ul className="grid grid-cols-[repeat(auto-fill,minmax(14rem,1fr))] gap-2">
            {takes.items.map((take, index) => {
              const file = take.audio_url.split('/').pop() ?? '';
              return (
                <li
                  key={take.id}
                  className={cn('flex items-center gap-2 rounded-lg border border-border/60 p-2')}
                >
                  <AudioPreviewButton src={audioUrl(file)} source={'sfx-' + take.id} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">
                      {t('soundEffects.take', { number: index + 1 })}
                    </p>
                    <p className="truncate text-xs tabular-nums text-muted-foreground">
                      {take.duration_s == null ? takes.prompt : `${take.duration_s.toFixed(1)}s`}
                    </p>
                  </div>
                  <SaveAudioButton url={audioUrl(file)} suggestedName={`sound-effect-${file}`} />
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </div>
  );
}
