import test from "node:test";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { createVoicePackage, encodeMonoPcm16Wav } from "../../../../voice-vault/voice-package.mjs";
import { decryptVprvoiceBytes } from "../decrypt_vprvoice.mjs";

const testPassphrase = "synthetic-package-test-passphrase";
const referenceTranscript = "This is synthetic test audio for checking the encrypted package decoder.";

function makeSyntheticWav() {
  const samples = new Float32Array(10 * 24_000);
  for (let index = 0; index < samples.length; index += 1) {
    samples[index] = Math.sin((2 * Math.PI * 220 * index) / 24_000) * 0.1;
  }
  return encodeMonoPcm16Wav({
    sampleRate: 24_000,
    getChannelData: () => samples
  });
}

async function makePackage() {
  return await createVoicePackage({
    originalBytes: new Uint8Array(Buffer.from("synthetic-only-audio-source")),
    wavBytes: makeSyntheticWav(),
    transcript: referenceTranscript,
    durationSeconds: 10,
    originalName: "synthetic-test.wav",
    originalType: "audio/wav"
  }, testPassphrase, webcrypto);
}

test("decrypts a synthetic Voice Vault package and validates its reference WAV", async () => {
  const packageBytes = await makePackage();
  const result = decryptVprvoiceBytes(packageBytes, testPassphrase);
  assert.equal(result.transcript, referenceTranscript);
  assert.equal(result.normalizedWav.toString("ascii", 0, 4), "RIFF");
  assert.equal(result.normalizedWav.readUInt32LE(24), 24_000);
  assert.equal(result.normalizedWav.readUInt16LE(22), 1);
  result.normalizedWav.fill(0);
  packageBytes.fill(0);
});

test("rejects a wrong passphrase", async () => {
  const packageBytes = await makePackage();
  assert.throws(
    () => decryptVprvoiceBytes(packageBytes, "incorrect-synthetic-passphrase"),
    /Could not unlock the package/
  );
  packageBytes.fill(0);
});

test("rejects a tampered encrypted package", async () => {
  const packageBytes = await makePackage();
  packageBytes[packageBytes.length - 1] ^= 0x01;
  assert.throws(
    () => decryptVprvoiceBytes(packageBytes, testPassphrase),
    /Could not unlock the package/
  );
  packageBytes.fill(0);
});
