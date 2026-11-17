import test from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import {
  createVoicePackage,
  openVoicePackage,
  encodeMonoPcm16Wav,
  PBKDF2_ITERATIONS,
  VOICE_SAMPLE_RATE,
  MAX_ORIGINAL_BYTES
} from "../voice-package.mjs";

globalThis.crypto = webcrypto;

function fakeAudioBuffer(seconds = 10) {
  const length = seconds * VOICE_SAMPLE_RATE;
  const samples = new Float32Array(length);
  for (let i = 0; i < length; i++) samples[i] = Math.sin((2 * Math.PI * 220 * i) / VOICE_SAMPLE_RATE) * 0.18;
  return {
    sampleRate: VOICE_SAMPLE_RATE,
    length,
    duration: seconds,
    getChannelData: channel => {
      assert.equal(channel, 0);
      return samples;
    }
  };
}

const wav = encodeMonoPcm16Wav(fakeAudioBuffer());
const rawAudio = new TextEncoder().encode("RAW-REFERENCE-AUDIO-BYTES-DO-NOT-LEAK");
const transcript = "This is my own voice recording for the Violin Prince voice reference.";
const password = "correct horse battery staple";
const packageBytes = await createVoicePackage({
  originalBytes: rawAudio,
  wavBytes: wav,
  transcript,
  originalName: "../../voice reference.webm",
  originalType: "audio/webm",
  durationSeconds: 10
}, password);

test("WAV encoder creates 24 kHz mono 16-bit PCM", () => {
  const view = new DataView(wav.buffer, wav.byteOffset, wav.byteLength);
  assert.equal(new TextDecoder().decode(wav.slice(0, 4)), "RIFF");
  assert.equal(new TextDecoder().decode(wav.slice(8, 12)), "WAVE");
  assert.equal(view.getUint16(20, true), 1);
  assert.equal(view.getUint16(22, true), 1);
  assert.equal(view.getUint32(24, true), VOICE_SAMPLE_RATE);
  assert.equal(view.getUint16(34, true), 16);
  assert.equal(view.getUint32(40, true), fakeAudioBuffer().length * 2);
});

test("voice package encrypts transcript and both recordings before storage", () => {
  const binaryText = new TextDecoder("latin1").decode(packageBytes);
  assert.ok(packageBytes.length > 100);
  assert.equal(binaryText.includes(transcript), false);
  assert.equal(binaryText.includes("voice reference.webm"), false);
  assert.equal(binaryText.includes(new TextDecoder().decode(rawAudio)), false);
  assert.equal(PBKDF2_ITERATIONS, 600_000);
});

test("voice package decrypts locally and preserves original and prepared audio", async () => {
  const opened = await openVoicePackage(packageBytes, password);
  assert.equal(opened.metadata.transcript, transcript);
  assert.equal(opened.metadata.durationSeconds, 10);
  assert.equal(opened.metadata.wavSampleRate, VOICE_SAMPLE_RATE);
  assert.equal(opened.metadata.originalFileName, "voice_reference.webm");
  assert.deepEqual(opened.originalAudio, rawAudio);
  assert.deepEqual(opened.normalizedWav, wav);
});

test("wrong passphrase is rejected", async () => {
  await assert.rejects(openVoicePackage(packageBytes, "this is the wrong passphrase"), /Could not unlock this package/);
});

test("header tampering is rejected by authenticated encryption", async () => {
  const tampered = packageBytes.slice();
  tampered[9] ^= 0x01;
  await assert.rejects(openVoicePackage(tampered, password), /Could not unlock this package/);
});

test("ciphertext tampering is rejected", async () => {
  const tampered = packageBytes.slice();
  tampered[tampered.length - 1] ^= 0x80;
  await assert.rejects(openVoicePackage(tampered, password), /Could not unlock this package/);
});

test("malformed or unrelated file is rejected", async () => {
  await assert.rejects(openVoicePackage(new Uint8Array(100), password), /not a Violin Prince voice package/);
  await assert.rejects(openVoicePackage(packageBytes.slice(0, 30), password), /too small/);
});

test("weak passphrases and invalid enrollment input are rejected", async () => {
  await assert.rejects(createVoicePackage({
    originalBytes: rawAudio, wavBytes: wav, transcript, originalName: "voice.webm",
    originalType: "audio/webm", durationSeconds: 10
  }, "short"));
  await assert.rejects(createVoicePackage({
    originalBytes: rawAudio, wavBytes: wav, transcript: "hello", originalName: "voice.webm",
    originalType: "audio/webm", durationSeconds: 10
  }, password), /exact transcript/);
  await assert.rejects(createVoicePackage({
    originalBytes: new Uint8Array(MAX_ORIGINAL_BYTES + 1), wavBytes: wav, transcript,
    originalName: "voice.webm", originalType: "audio/webm", durationSeconds: 10
  }, password), /20 MB/);
});

test("source keeps tokens in memory and only sends encrypted package bytes to Drive", async () => {
  const fs = await import("node:fs/promises");
  const app = await fs.readFile(new URL("../app.mjs", import.meta.url), "utf8");
  assert.doesNotMatch(app, /localStorage|sessionStorage|indexedDB/);
  assert.match(app, /let accessToken = null/);
  assert.match(app, /accessToken = null/);
  const start = app.indexOf("async function uploadEncryptedPackage");
  const end = app.indexOf("function validateForm", start);
  assert.ok(start >= 0 && end > start);
  const uploadFunction = app.slice(start, end);
  assert.match(uploadFunction, /encryptedBytes/);
  assert.doesNotMatch(uploadFunction, /originalBytes|wavBytes|transcript/);
  assert.match(app, /info\?\.shared !== false/);
});
