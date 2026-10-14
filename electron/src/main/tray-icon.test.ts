import { expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => {
  const resized = {
    addRepresentation: vi.fn(),
    setTemplateImage: vi.fn(),
    toPNG: vi.fn(() => Buffer.from('retina')),
  };
  const source = { resize: vi.fn(() => resized), toPNG: vi.fn(() => Buffer.from('icon')) };
  return { source, resized, createFromPath: vi.fn(() => source) };
});
vi.mock('electron', () => ({ nativeImage: { createFromPath: mocks.createFromPath } }));
import { createTrayIcon } from './tray-icon';

it.each([
  ['32x32.png', 'trayTemplate.png'],
  ['tray-recording.png', 'trayRecordingTemplate.png'],
])('uses an 18-point macOS template for %s', (file, template) => {
  mocks.createFromPath.mockClear();
  mocks.source.resize.mockClear();
  mocks.resized.setTemplateImage.mockClear();
  createTrayIcon(file, 'darwin');
  expect(mocks.createFromPath).toHaveBeenCalledWith(template);
  expect(mocks.source.resize).toHaveBeenCalledWith({ width: 18, height: 18, quality: 'best' });
  expect(mocks.source.resize).toHaveBeenCalledWith({ width: 36, height: 36, quality: 'best' });
  expect(mocks.resized.addRepresentation).toHaveBeenCalledWith({
    scaleFactor: 2,
    buffer: Buffer.from('retina'),
  });
  expect(mocks.resized.setTemplateImage).toHaveBeenCalledWith(true);
});

it.each(['win32', 'linux'] as const)('preserves the existing %s tray image', (platform) => {
  mocks.createFromPath.mockClear();
  mocks.source.resize.mockClear();
  expect(createTrayIcon('32x32.png', platform)).toBe(mocks.source);
  expect(mocks.createFromPath).toHaveBeenCalledWith('32x32.png');
  expect(mocks.source.resize).not.toHaveBeenCalled();
});
