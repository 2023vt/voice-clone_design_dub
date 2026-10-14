// @vitest-environment node
import { createServer } from 'node:http';
import { afterEach, expect, it } from 'vitest';
import {
  proxyRequestRefused,
  startDevBackendProxy,
  type DevBackendProxy,
} from './dev-backend-proxy';

const cleanup: (() => Promise<void>)[] = [];
afterEach(async () => {
  await Promise.allSettled(cleanup.splice(0).map((close) => close()));
});

it('streams requests to the current backend with only main-owned authorization', async () => {
  let received: { path?: string; body?: string; authorization?: string; origin?: string } = {};
  const upstream = createServer((request, response) => {
    const chunks: Buffer[] = [];
    request.on('data', (chunk) => chunks.push(chunk));
    request.on('end', () => {
      received = {
        path: request.url,
        body: Buffer.concat(chunks).toString('utf8'),
        authorization: request.headers.authorization,
        origin: request.headers.origin,
      };
      response.writeHead(201, { 'content-type': 'text/plain' });
      response.end('proxied');
    });
  });
  await new Promise<void>((resolve) => upstream.listen(0, '127.0.0.1', resolve));
  cleanup.push(() => new Promise<void>((resolve) => upstream.close(() => resolve())));
  const address = upstream.address();
  if (!address || typeof address === 'string') throw new Error('upstream did not bind');

  const proxy: DevBackendProxy = await startDevBackendProxy(
    () => `http://127.0.0.1:${address.port}`,
    () => ({ Authorization: 'Bearer scoped-session' }),
    0,
    ['http://localhost:3902'],
  );
  cleanup.push(proxy.close);
  const response = await fetch(`${proxy.url}/system/info?full=1`, {
    method: 'POST',
    headers: { Authorization: 'Bearer renderer-secret', Origin: 'http://localhost:3902' },
    body: 'stream me',
  });

  expect(response.status).toBe(201);
  expect(await response.text()).toBe('proxied');
  expect(received).toEqual({
    path: '/system/info?full=1',
    body: 'stream me',
    authorization: 'Bearer scoped-session',
    origin: undefined,
  });
});

it('keeps the backend path prefix and never leaves the configured host', async () => {
  const paths: string[] = [];
  const upstream = createServer((request, response) => {
    paths.push(request.url || '');
    response.end('ok');
  });
  await new Promise<void>((resolve) => upstream.listen(0, '127.0.0.1', resolve));
  cleanup.push(() => new Promise<void>((resolve) => upstream.close(() => resolve())));
  const address = upstream.address();
  if (!address || typeof address === 'string') throw new Error('upstream did not bind');

  const proxy = await startDevBackendProxy(
    () => `http://127.0.0.1:${address.port}/studio/`,
    () => ({}),
    0,
  );
  cleanup.push(proxy.close);
  await fetch(`${proxy.url}/system/info?full=1`);
  await fetch(`${proxy.url}//elsewhere.invalid/health`);

  expect(paths).toEqual(['/studio/system/info?full=1', '/studio/elsewhere.invalid/health']);
});

it('closes while a renderer keeps a streaming backend response open', async () => {
  const upstream = createServer((_request, response) => {
    response.writeHead(200, { 'content-type': 'text/plain' });
    response.write('still streaming');
  });
  await new Promise<void>((resolve) => upstream.listen(0, '127.0.0.1', resolve));
  cleanup.push(
    () =>
      new Promise<void>((resolve) => {
        upstream.closeAllConnections();
        upstream.close(() => resolve());
      }),
  );
  const address = upstream.address();
  if (!address || typeof address === 'string') throw new Error('upstream did not bind');
  const proxy = await startDevBackendProxy(
    () => `http://127.0.0.1:${address.port}`,
    () => ({}),
    0,
  );
  const response = await fetch(proxy.url);

  await expect(proxy.close()).resolves.toBeUndefined();
  await expect(proxy.close()).resolves.toBeUndefined();
  await response.body?.cancel().catch(() => {});
});

it('refuses other websites and rebound host names before injecting credentials', () => {
  const renderer = ['http://localhost:3902'];
  expect(proxyRequestRefused({ host: '127.0.0.1:3903' }, renderer)).toBe(false);
  expect(
    proxyRequestRefused({ host: 'localhost:3903', 'sec-fetch-site': 'same-origin' }, renderer),
  ).toBe(false);
  expect(
    proxyRequestRefused({ host: '127.0.0.1:3903', origin: 'http://localhost:3902' }, renderer),
  ).toBe(false);
  expect(proxyRequestRefused({ host: 'evil.example:3903' }, renderer)).toBe(true);
  expect(
    proxyRequestRefused({ host: '127.0.0.1:3903', origin: 'https://evil.example' }, renderer),
  ).toBe(true);
  expect(proxyRequestRefused({ host: '127.0.0.1:3903', origin: 'null' }, renderer)).toBe(true);
  expect(
    proxyRequestRefused({ host: '127.0.0.1:3903', 'sec-fetch-site': 'cross-site' }, renderer),
  ).toBe(true);
});

it('fails an interrupted backend response promptly and serves the next request', async () => {
  const upstream = createServer((request, response) => {
    if (request.url === '/truncated') {
      response.writeHead(200, { 'content-type': 'text/plain', 'content-length': '100' });
      response.write('short', () => setTimeout(() => response.destroy(), 20));
    } else response.end('healthy');
  });
  await new Promise<void>((resolve) => upstream.listen(0, '127.0.0.1', resolve));
  cleanup.push(
    () => new Promise<void>((resolve) => {
      upstream.closeAllConnections();
      upstream.close(() => resolve());
    }),
  );
  const address = upstream.address();
  if (!address || typeof address === 'string') throw new Error('upstream did not bind');
  const proxy = await startDevBackendProxy(() => `http://127.0.0.1:${address.port}`, () => ({}), 0);
  cleanup.push(proxy.close);
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    const response = await fetch(`${proxy.url}/truncated`, { signal: controller.signal });
    const outcome = await Promise.race([
      response.text().then(() => 'completed', () => 'failed'),
      new Promise<string>((resolve) => {
        timer = setTimeout(() => resolve('timed-out'), 500);
      }),
    ]);
    expect(outcome).toBe('failed');
    expect(await (await fetch(`${proxy.url}/health`)).text()).toBe('healthy');
  } finally {
    clearTimeout(timer);
    controller.abort();
  }
});
