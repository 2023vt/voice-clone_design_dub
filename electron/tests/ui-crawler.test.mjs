import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const dir = dirname(fileURLToPath(import.meta.url));
const crawler = readFileSync(join(dir, 'ui-crawler.mjs'), 'utf8');
const ci = readFileSync(join(dir, '../../.github/workflows/ci.yml'), 'utf8');

const list = (source) => source.match(/'([^']+)'|[\w/-]+/g).map((item) => item.replaceAll("'", ''));

test('CI crawls every fault mode the crawler defines', () => {
  const modes = list(crawler.match(/const MODES = \[([^\]]+)\]/)[1]);
  const matrix = list(ci.match(/ui-crawler:[\s\S]*?mode: \[([^\]]+)\]/)[1]);
  assert.deepEqual(matrix, modes);
});

test('CI shards cover every route exactly once', () => {
  const shards = list(ci.match(/ui-crawler:[\s\S]*?shard: \[([^\]]+)\]/)[1]);
  const total = Number(shards[0].split('/')[1]);
  assert.deepEqual(
    shards,
    Array.from({ length: total }, (_, index) => `${index + 1}/${total}`),
  );
});

test('crawler findings are fixed, not allowlisted', () => {
  assert.match(crawler, /export const KNOWN_FINDINGS = \{\};/);
});
