import { fireEvent, render, screen } from '@testing-library/react';
import { useRef, useState } from 'react';
import { expect, it, vi } from 'vitest';
import '@/i18n';
import { ChapterOutline } from './chapter-outline';

function OutlineHost({ script, onJump }: { script: string; onJump?: (start: number) => void }) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [caret, setCaret] = useState(0);
  return (
    <>
      <ChapterOutline
        script={script}
        caret={caret}
        textareaRef={textareaRef}
        onJump={(start) => {
          setCaret(start);
          onJump?.(start);
        }}
      />
      <textarea ref={textareaRef} aria-label="Script" value={script} onChange={() => undefined} />
    </>
  );
}

const script = '# One\nHello world here.\n# Two\nFour more spoken words.';

it('lists chapters and jumps the script caret to the heading', () => {
  const onJump = vi.fn();
  render(<OutlineHost script={script} onJump={onJump} />);
  expect(screen.getByRole('navigation', { name: 'Chapters' })).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Jump to Two' }));
  expect(onJump).toHaveBeenCalledWith(script.indexOf('# Two'));
  expect(screen.getByRole('button', { name: 'Jump to Two' })).toHaveAttribute(
    'aria-current',
    'true',
  );
  expect(screen.getByLabelText('Script')).toHaveProperty('selectionStart', script.indexOf('# Two'));
});

it('explains how to add chapters when the manuscript has no headings', () => {
  render(<OutlineHost script="just some words" />);
  expect(screen.getByText('Add a # heading to jump between chapters.')).toBeVisible();
  expect(screen.queryByRole('button', { name: /Jump to/ })).toBeNull();
});
