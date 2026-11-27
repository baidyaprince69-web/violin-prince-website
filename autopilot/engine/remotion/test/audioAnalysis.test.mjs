import test from "node:test";
import assert from "node:assert/strict";
import {
  AUDIO_ANALYSIS_SAMPLE_RATE,
  buildAudioEnvelope,
} from "../src/audioAnalysis.mjs";

function createPcmBuffer(frameLevels, samplesPerFrame = AUDIO_ANALYSIS_SAMPLE_RATE / 25) {
  const buffer = Buffer.alloc(frameLevels.length * samplesPerFrame * 4);
  let offset = 0;
  for (const level of frameLevels) {
    for (let sample = 0; sample < samplesPerFrame; sample += 1) {
      const phase = (sample / samplesPerFrame) * Math.PI * 2 * 8;
      buffer.writeFloatLE(Math.sin(phase) * level, offset);
      offset += 4;
    }
  }
  return buffer;
}

test("audio envelope follows changing soundtrack loudness", () => {
  const levels = [...Array(25).fill(0.025), ...Array(25).fill(0.24)];
  const envelope = buildAudioEnvelope(createPcmBuffer(levels), {
    durationSeconds: 2,
  });
  const quietAverage = envelope.slice(5, 20).reduce((sum, value) => sum + value, 0) / 15;
  const loudAverage = envelope.slice(32, 48).reduce((sum, value) => sum + value, 0) / 16;
  assert.equal(envelope.length, 50);
  assert.ok(loudAverage > quietAverage + 0.35);
  assert.ok(envelope.every((value) => value >= 0 && value <= 1));
});

test("silent audio produces a restrained stable fallback", () => {
  const envelope = buildAudioEnvelope(Buffer.alloc(AUDIO_ANALYSIS_SAMPLE_RATE * 2 * 4), {
    durationSeconds: 2,
  });
  assert.equal(envelope.length, 50);
  assert.ok(envelope.every((value) => value === 0.06));
});

test("rejects malformed PCM buffers and invalid timing", () => {
  assert.throws(
    () => buildAudioEnvelope(Buffer.from([1, 2, 3]), { durationSeconds: 1 }),
    /incomplete sample/,
  );
  assert.throws(
    () => buildAudioEnvelope(Buffer.alloc(400), { durationSeconds: 1, sampleRate: 0 }),
    /positive sample-rate/,
  );
});
