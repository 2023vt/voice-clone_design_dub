// @vitest-environment node
import { EventEmitter } from 'node:events';
import type { BackendSupervisor } from './backend';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { registerRepairAgents, REPAIR_CHANNELS } from './repair-agents';
const mock = vi.hoisted(() => ({
  handlers: new Map<string, (...args: any[]) => any>(),
  spawn: vi.fn(),
  bridge: vi.fn(),
  close: vi.fn(async () => {}),
  output: vi.fn(),
}));
vi.mock('electron', () => ({
  app: { getPath: () => '/temp', getAppPath: () => '/app' },
  BrowserWindow: {},
  dialog: {},
  ipcMain: {
    handle: (name: string, callback: (...args: any[]) => any) => mock.handlers.set(name, callback),
    removeHandler: (name: string) => mock.handlers.delete(name),
  },
}));
vi.mock('node:fs', () => ({
  existsSync: () => true,
  accessSync: () => {},
  constants: { W_OK: 2 },
  readFileSync: vi.fn(),
  mkdtempSync: vi.fn(),
  rmSync: vi.fn(),
  writeFileSync: vi.fn(),
}));
vi.mock('node:child_process', () => ({
  spawn: mock.spawn,
  spawnSync: () => ({
    status: 0,
    stdout: process.platform === 'win32' ? 'C:\\agents\\codex.exe' : '/usr/bin/codex',
  }),
}));
vi.mock('./repair-api-bridge', () => ({ startRepairApiBridge: mock.bridge }));
vi.mock('./llm-agent-bridge', () => ({
  startLlmAgentBridge: async () => ({ url: '', token: '', close() {} }),
}));
vi.mock('./window-safety', () => ({ sendToLiveWindow: mock.output }));
const frame = { url: 'app://voicestudio/index.html' };
const contents = { mainFrame: frame };
const owner = { webContents: contents };
const event = { sender: contents, senderFrame: frame };
const request = {
  agent: 'codex',
  mode: 'fix',
  workspace: 'app',
  report: 'Create a preview',
  context: '{}',
};
let dispose: (() => void) | undefined;
beforeEach(() => {
  vi.clearAllMocks();
  mock.bridge.mockResolvedValue({ contextFile: '/temp/isolated/context.json', close: mock.close });
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({ ok: true, text: async () => '{}' })),
  );
});
afterEach(() => {
  dispose?.();
  vi.unstubAllGlobals();
});
const start = () => mock.handlers.get(REPAIR_CHANNELS.start)!(event, request);
async function setup() {
  dispose = await registerRepairAgents(
    {
      baseUrl: 'http://localhost',
      requestHeaders: () => ({}),
      status: { stage: 'ready' },
    } as unknown as BackendSupervisor,
    '/source',
    () => owner as any,
  );
}

it('cancels during setup and rejects a concurrent request before launching a process', async () => {
  let release!: (value: unknown) => void;
  mock.bridge.mockReturnValue(
    new Promise((resolve) => {
      release = resolve;
    }),
  );
  await setup();
  const first = start();
  await expect(start()).rejects.toThrow('already running');
  const stopped = mock.handlers.get(REPAIR_CHANNELS.stop)!(event);
  expect(stopped.status).toBe('stopped');
  release({ contextFile: '/temp/isolated/context.json', close: mock.close });
  await first;
  expect(mock.spawn).not.toHaveBeenCalled();
  expect(mock.close).toHaveBeenCalled();
  expect(mock.handlers.get(REPAIR_CHANNELS.state)!(event).status).toBe('stopped');
});
it('launches app chat outside the checkout and closes its capability after streaming completion', async () => {
  const child = Object.assign(new EventEmitter(), {
    stdin: Object.assign(new EventEmitter(), { end: vi.fn() }),
    stdout: new EventEmitter(),
    stderr: new EventEmitter(),
    kill: vi.fn(),
  });
  mock.spawn.mockReturnValue(child);
  await setup();
  const result = await start();
  expect(mock.spawn.mock.calls[0][2].cwd.replaceAll('\\', '/')).toBe('/temp/isolated');
  expect(child.stdin.end).toHaveBeenCalledWith(
    expect.stringContaining('No source checkout is attached'),
  );
  child.stdout.emit('data', Buffer.from('Preview ready'));
  child.emit('close', 0);
  expect(mock.output).toHaveBeenCalledWith(
    owner,
    REPAIR_CHANNELS.event,
    expect.objectContaining({ sessionId: result.sessionId, type: 'output', text: 'Preview ready' }),
  );
  expect(mock.handlers.get(REPAIR_CHANNELS.state)!(event).status).toBe('complete');
  expect(mock.close).toHaveBeenCalled();
});
