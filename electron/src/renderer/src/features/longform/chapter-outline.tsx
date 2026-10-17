import type { RefObject } from 'react';
import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { ListTreeIcon } from 'lucide-react';
import { parseChapterOutline } from '@shared/utils/audiobookScript';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export function scrollTextareaToOffset(textarea: HTMLTextAreaElement, start: number, end = start) {
  const length = textarea.value.length;
  const from = Math.max(0, Math.min(start, length));
  const to = Math.max(from, Math.min(end, length));
  textarea.focus();
  textarea.setSelectionRange(from, to);
  const style = window.getComputedStyle(textarea);
  const lineHeight =
    Number.parseFloat(style.lineHeight) || Number.parseFloat(style.fontSize) * 1.75 || 28;
  const lineIndex = textarea.value.slice(0, from).split('\n').length - 1;
  textarea.scrollTop = Math.max(0, lineIndex * lineHeight - textarea.clientHeight / 3);
}

export function ChapterOutline({
  script,
  caret = 0,
  textareaRef,
  disabled,
  onJump,
}: {
  script: string;
  caret?: number;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  disabled?: boolean;
  onJump?: (start: number) => void;
}) {
  const { t } = useTranslation();
  const chapters = useMemo(() => parseChapterOutline(script), [script]);
  const activeIndex = chapters.reduce(
    (current, chapter) => (chapter.start <= caret ? chapter.index : current),
    -1,
  );
  const jump = (start: number, headingEnd: number) => {
    const input = textareaRef.current;
    if (!input) return;
    scrollTextareaToOffset(input, start, headingEnd);
    onJump?.(start);
  };

  return (
    <nav
      data-slot="audiobook-chapter-outline"
      aria-label={t('audiobook.outline')}
      className="flex max-h-36 min-w-0 flex-col gap-1 overflow-y-auto rounded-lg border border-border/60 bg-muted/15 p-1.5 lg:max-h-none lg:w-56 lg:shrink-0"
    >
      <p className="flex items-center gap-1.5 px-1.5 py-0.5 text-[11px] font-medium tracking-[0.01em] text-muted-foreground">
        <ListTreeIcon className="size-3.5" />
        {t('audiobook.outline')}
      </p>
      {chapters.length === 0 ? (
        <p className="px-1.5 py-1 text-xs leading-5 text-muted-foreground">
          {t('audiobook.outline_empty')}
        </p>
      ) : (
        <ul className="flex flex-wrap gap-1 lg:flex-col lg:flex-nowrap">
          {chapters.map((chapter) => {
            const title = chapter.title || t('audiobook.chapter_n', { n: chapter.index + 1 });
            const active = chapter.index === activeIndex;
            return (
              <li key={`${chapter.index}:${chapter.start}`} className="min-w-0 lg:w-full">
                <Button
                  type="button"
                  size="sm"
                  variant={active ? 'secondary' : 'ghost'}
                  disabled={disabled}
                  aria-current={active ? 'true' : undefined}
                  aria-label={t('audiobook.jump_chapter', { title })}
                  title={title}
                  className={cn(
                    'h-auto min-h-8 w-full justify-start px-2 py-1 text-left whitespace-normal',
                    chapter.words === 0 && 'text-muted-foreground',
                  )}
                  onClick={() => jump(chapter.start, chapter.headingEnd)}
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-xs font-medium">{title}</span>
                    <span className="block text-[10px] font-normal text-muted-foreground">
                      {t('audiobook.outline_words', { count: chapter.words })}
                    </span>
                  </span>
                </Button>
              </li>
            );
          })}
        </ul>
      )}
    </nav>
  );
}
