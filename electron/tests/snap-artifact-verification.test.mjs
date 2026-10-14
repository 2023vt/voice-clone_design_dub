import assert from 'node:assert/strict';
import test from 'node:test';

import metadata from '../../store/metadata.json' with { type: 'json' };
import { verifySnapMetadata } from '../../scripts/verify_snap_artifact.mjs';

const snapYaml = `base: core22
grade: stable
confinement: strict
name: voicestudio
version: 0.5.7
title: VoiceStudio
summary: ${metadata.listing.shortDescription}
description: ${metadata.listing.description}
apps:
  voicestudio:
    plugs:
      - browser-support
      - desktop
      - desktop-legacy
      - home
      - x11
      - wayland
      - unity7
      - network
      - network-bind
      - gsettings
      - audio-playback
      - audio-record
      - pulseaudio
      - opengl
`;

test('accepts canonical strict Snap metadata', () => {
  assert.deepEqual(verifySnapMetadata(snapYaml, { ...metadata, version: '0.5.7' }), {
    name: 'voicestudio',
    version: '0.5.7',
    confinement: 'strict',
    base: 'core22',
    plugs: [
      'browser-support',
      'desktop',
      'desktop-legacy',
      'home',
      'x11',
      'wayland',
      'unity7',
      'network',
      'network-bind',
      'gsettings',
      'audio-playback',
      'audio-record',
      'pulseaudio',
      'opengl',
    ],
  });
});

test('rejects weakened confinement, missing capabilities and broad removable access', () => {
  const expected = { ...metadata, version: '0.5.7' };
  assert.throws(() => verifySnapMetadata(snapYaml.replace('strict', 'classic'), expected));
  assert.throws(() => verifySnapMetadata(snapYaml.replace('      - audio-record\n', ''), expected));
  assert.throws(() =>
    verifySnapMetadata(`${snapYaml}      - removable-media\n`, expected),
  );
});
