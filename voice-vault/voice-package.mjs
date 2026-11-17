export const VOICE_PACKAGE_MAGIC = "VPRVOICE";
export const VOICE_PACKAGE_VERSION = 1;
export const PBKDF2_ITERATIONS = 600_000;
export const VOICE_SAMPLE_RATE = 24_000;
export const MAX_ORIGINAL_BYTES = 20 * 1024 * 1024;
export const MAX_PACKAGE_BYTES = 50 * 1024 * 1024;
export const MIN_PASSPHRASE_LENGTH = 12;

const encoder = new TextEncoder();
const decoder = new TextDecoder("utf-8", { fatal: true });
const HEADER_BYTES = 8 + 16 + 12 + 4;
const FIXED_PAYLOAD_BYTES = 12;

function cryptoApi(cryptoOverride) {
  const api = cryptoOverride || globalThis.crypto;
  if (!api?.subtle || !api?.getRandomValues) {
    throw new Error("Secure browser cryptography is unavailable. Open this page over HTTPS in a modern browser.");
  }
  return api;
}

function asBytes(value, label) {
  if (value instanceof Uint8Array) return value;
  if (value instanceof ArrayBuffer) return new Uint8Array(value);
  if (ArrayBuffer.isView(value)) return new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  throw new TypeError(label + " must be binary audio data.");
}

function safeFilename(name) {
  const last = String(name || "voice-recording").split(/[\\/]/).pop() || "voice-recording";
  return last.replace(/[^a-zA-Z0-9._-]/g, "_").slice(0, 120) || "voice-recording";
}

function concat(parts) {
  const total = parts.reduce((sum, part) => sum + part.length, 0);
  const result = new Uint8Array(total);
  let offset = 0;
  for (const part of parts) {
    result.set(part, offset);
    offset += part.length;
  }
  return result;
}

function readUint32(view, offset, label) {
  if (offset < 0 || offset + 4 > view.byteLength) throw new Error("Voice package is truncated (" + label + ").");
  return view.getUint32(offset, false);
}

async function digestHex(bytes, crypto) {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  return Array.from(digest, byte => byte.toString(16).padStart(2, "0")).join("");
}

async function deriveKey(passphrase, salt, crypto) {
  if (typeof passphrase !== "string" || passphrase.length < MIN_PASSPHRASE_LENGTH) {
    throw new Error("Use an encryption passphrase of at least 12 characters.");
  }
  const material = await crypto.subtle.importKey(
    "raw", encoder.encode(passphrase), "PBKDF2", false, ["deriveKey"]
  );
  return await crypto.subtle.deriveKey(
    { name: "PBKDF2", salt, iterations: PBKDF2_ITERATIONS, hash: "SHA-256" },
    material,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"]
  );
}

function validateWav(wav) {
  if (wav.length < 44) throw new Error("The prepared WAV is incomplete.");
  const view = new DataView(wav.buffer, wav.byteOffset, wav.byteLength);
  const ascii = (offset, size) => String.fromCharCode(...wav.subarray(offset, offset + size));
  if (ascii(0, 4) !== "RIFF" || ascii(8, 4) !== "WAVE" || ascii(12, 4) !== "fmt ") {
    throw new Error("The prepared audio must be a valid PCM WAV file.");
  }
  const channels = view.getUint16(22, true);
  const sampleRate = view.getUint32(24, true);
  const bitsPerSample = view.getUint16(34, true);
  if (view.getUint16(20, true) !== 1 || channels !== 1 || sampleRate !== VOICE_SAMPLE_RATE || bitsPerSample !== 16) {
    throw new Error("The prepared WAV must be mono, 24 kHz, 16-bit PCM.");
  }
}

export function encodeMonoPcm16Wav(audioBuffer) {
  if (!audioBuffer || typeof audioBuffer.getChannelData !== "function") {
    throw new TypeError("A decoded mono audio buffer is required.");
  }
  const sampleRate = Number(audioBuffer.sampleRate);
  const samples = audioBuffer.getChannelData(0);
  if (sampleRate !== VOICE_SAMPLE_RATE || !samples?.length) {
    throw new Error("Audio must first be resampled to 24 kHz mono in the browser.");
  }
  const byteLength = samples.length * 2;
  if (byteLength + 44 > MAX_PACKAGE_BYTES) throw new Error("The prepared WAV is unexpectedly large.");
  const wav = new Uint8Array(44 + byteLength);
  const view = new DataView(wav.buffer);
  const write = (offset, value) => {
    for (let i = 0; i < value.length; i++) wav[offset + i] = value.charCodeAt(i);
  };
  write(0, "RIFF");
  view.setUint32(4, 36 + byteLength, true);
  write(8, "WAVE");
  write(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, VOICE_SAMPLE_RATE, true);
  view.setUint32(28, VOICE_SAMPLE_RATE * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  write(36, "data");
  view.setUint32(40, byteLength, true);
  for (let i = 0; i < samples.length; i++) {
    const sample = Math.max(-1, Math.min(1, Number(samples[i]) || 0));
    view.setInt16(44 + i * 2, sample < 0 ? Math.round(sample * 32768) : Math.round(sample * 32767), true);
  }
  return wav;
}

export async function createVoicePackage(input, passphrase, cryptoOverride) {
  const crypto = cryptoApi(cryptoOverride);
  const original = asBytes(input?.originalBytes, "Original recording");
  const wav = asBytes(input?.wavBytes, "Prepared WAV");
  const transcript = String(input?.transcript || "").trim();
  const duration = Number(input?.durationSeconds);
  if (!original.length || original.length > MAX_ORIGINAL_BYTES) {
    throw new Error("The original recording must be between 1 byte and 20 MB.");
  }
  validateWav(wav);
  if (transcript.length < 20 || transcript.length > 12_000 || transcript.split(/\s+/).filter(Boolean).length < 5) {
    throw new Error("Enter the exact transcript of your recording (at least 20 characters and five words).");
  }
  if (!Number.isFinite(duration) || duration < 10 || duration > 120) {
    throw new Error("Recording duration must be between 10 seconds and 2 minutes. A 30–60 second reference is recommended.");
  }

  const metadata = {
    format: "VIOLIN-PRINCE-VOICE-VAULT",
    version: VOICE_PACKAGE_VERSION,
    createdAt: new Date().toISOString(),
    transcript,
    originalFileName: safeFilename(input.originalName),
    originalMimeType: String(input.originalType || "application/octet-stream").slice(0, 100),
    originalBytes: original.length,
    wavBytes: wav.length,
    durationSeconds: Math.round(duration * 100) / 100,
    wavSampleRate: VOICE_SAMPLE_RATE,
    wavChannels: 1,
    wavEncoding: "PCM_S16LE",
    originalSha256: await digestHex(original, crypto),
    wavSha256: await digestHex(wav, crypto)
  };
  const metadataBytes = encoder.encode(JSON.stringify(metadata));
  const payloadLength = FIXED_PAYLOAD_BYTES + metadataBytes.length + original.length + wav.length;
  if (HEADER_BYTES + payloadLength + 16 > MAX_PACKAGE_BYTES) {
    throw new Error("Encrypted voice package would exceed the 50 MB safety limit.");
  }

  const payload = new Uint8Array(payloadLength);
  const payloadView = new DataView(payload.buffer);
  payloadView.setUint32(0, metadataBytes.length, false);
  payloadView.setUint32(4, original.length, false);
  payloadView.setUint32(8, wav.length, false);
  let offset = FIXED_PAYLOAD_BYTES;
  payload.set(metadataBytes, offset); offset += metadataBytes.length;
  payload.set(original, offset); offset += original.length;
  payload.set(wav, offset);

  const salt = crypto.getRandomValues(new Uint8Array(16));
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const header = new Uint8Array(HEADER_BYTES);
  header.set(encoder.encode(VOICE_PACKAGE_MAGIC), 0);
  header.set(salt, 8);
  header.set(iv, 24);
  new DataView(header.buffer).setUint32(36, PBKDF2_ITERATIONS, false);
  const key = await deriveKey(passphrase, salt, crypto);
  try {
    const ciphertext = new Uint8Array(await crypto.subtle.encrypt(
      { name: "AES-GCM", iv, additionalData: header, tagLength: 128 }, key, payload
    ));
    return concat([header, ciphertext]);
  } finally {
    payload.fill(0);
  }
}

export async function openVoicePackage(packageValue, passphrase, cryptoOverride) {
  const crypto = cryptoApi(cryptoOverride);
  const bytes = asBytes(packageValue, "Encrypted voice package");
  if (bytes.length < HEADER_BYTES + 16 || bytes.length > MAX_PACKAGE_BYTES) {
    throw new Error("The encrypted voice package is too small, too large or incomplete.");
  }
  if (decoder.decode(bytes.subarray(0, 8)) !== VOICE_PACKAGE_MAGIC) {
    throw new Error("This is not a Violin Prince voice package.");
  }
  const header = bytes.slice(0, HEADER_BYTES);
  const salt = header.slice(8, 24);
  const iv = header.slice(24, 36);
  const iterations = readUint32(new DataView(header.buffer), 36, "encryption settings");
  if (iterations !== PBKDF2_ITERATIONS) throw new Error("This voice package uses an unsupported encryption version.");
  const key = await deriveKey(passphrase, salt, crypto);
  let plaintext;
  try {
    plaintext = new Uint8Array(await crypto.subtle.decrypt(
      { name: "AES-GCM", iv, additionalData: header, tagLength: 128 },
      key,
      bytes.subarray(HEADER_BYTES)
    ));
  } catch {
    throw new Error("Could not unlock this package. Check the passphrase or use an unmodified original file.");
  }

  try {
    if (plaintext.length < FIXED_PAYLOAD_BYTES) throw new Error("The decrypted voice package is incomplete.");
    const view = new DataView(plaintext.buffer, plaintext.byteOffset, plaintext.byteLength);
    const metadataLength = readUint32(view, 0, "metadata length");
    const originalLength = readUint32(view, 4, "original audio length");
    const wavLength = readUint32(view, 8, "prepared WAV length");
    const expected = FIXED_PAYLOAD_BYTES + metadataLength + originalLength + wavLength;
    if (expected !== plaintext.length || !metadataLength || !originalLength || !wavLength) {
      throw new Error("The decrypted voice package has inconsistent file lengths.");
    }
    let offset = FIXED_PAYLOAD_BYTES;
    let metadata;
    try { metadata = JSON.parse(decoder.decode(plaintext.subarray(offset, offset + metadataLength))); }
    catch { throw new Error("Voice package metadata is damaged."); }
    offset += metadataLength;
    const originalAudio = plaintext.slice(offset, offset + originalLength); offset += originalLength;
    const normalizedWav = plaintext.slice(offset, offset + wavLength);
    if (metadata?.format !== "VIOLIN-PRINCE-VOICE-VAULT" || metadata?.version !== VOICE_PACKAGE_VERSION ||
        typeof metadata.transcript !== "string" || !metadata.transcript.trim() ||
        !Number.isFinite(metadata.durationSeconds) || metadata.originalBytes !== originalAudio.length ||
        metadata.wavBytes !== normalizedWav.length) {
      throw new Error("This package does not contain a supported voice-enrollment recording.");
    }
    validateWav(normalizedWav);
    if (await digestHex(originalAudio, crypto) !== metadata.originalSha256 ||
        await digestHex(normalizedWav, crypto) !== metadata.wavSha256) {
      throw new Error("The voice package failed its audio integrity check.");
    }
    return { metadata, originalAudio, normalizedWav };
  } finally {
    plaintext.fill(0);
  }
}
