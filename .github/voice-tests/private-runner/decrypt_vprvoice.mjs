#!/usr/bin/env node
/**
 * Decrypt a Violin Prince .vprvoice package inside an isolated private runner.
 * Writes only the prepared WAV and transcript to a temporary directory.
 * The original recording is authenticated but never written to disk.
 */
import { createHash, createDecipheriv, pbkdf2Sync } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { resolve, join } from "node:path";
import { fileURLToPath } from "node:url";

const HEADER_BYTES = 40;
const ITERATIONS = 600_000;
const MAX_PACKAGE_BYTES = 50 * 1024 * 1024;
const SAMPLE_RATE = 24_000;

function sha256Hex(value) {
  return createHash("sha256").update(value).digest("hex");
}

function validatePreparedWav(wav) {
  if (wav.length < 44 || wav.toString("ascii", 0, 4) !== "RIFF" ||
      wav.toString("ascii", 8, 12) !== "WAVE" ||
      wav.toString("ascii", 12, 16) !== "fmt ") {
    throw new Error("The decrypted reference WAV is incomplete or invalid.");
  }
  if (wav.readUInt16LE(20) !== 1 || wav.readUInt16LE(22) !== 1 ||
      wav.readUInt32LE(24) !== SAMPLE_RATE || wav.readUInt16LE(34) !== 16) {
    throw new Error("The reference WAV must be mono, 24 kHz, 16-bit PCM.");
  }
}

export function decryptVprvoiceBytes(packageValue, passphrase) {
  const bytes = Buffer.from(packageValue);
  let key = null;
  let plaintext = null;
  let normalizedWav = null;
  let transferWavToCaller = false;

  try {
    if (bytes.length < HEADER_BYTES + 16 || bytes.length > MAX_PACKAGE_BYTES) {
      throw new Error("The encrypted package is outside the supported size limits.");
    }
    if (bytes.toString("ascii", 0, 8) !== "VPRVOICE") {
      throw new Error("The selected file is not a Violin Prince Voice Vault package.");
    }
    if (typeof passphrase !== "string" || passphrase.length < 12) {
      throw new Error("The private VOICE_PACKAGE_PASSPHRASE Actions secret is missing or invalid.");
    }

    const header = bytes.subarray(0, HEADER_BYTES);
    const salt = header.subarray(8, 24);
    const iv = header.subarray(24, 36);
    if (header.readUInt32BE(36) !== ITERATIONS) {
      throw new Error("The package uses an unsupported encryption setting.");
    }

    const passphraseBytes = Buffer.from(passphrase, "utf8");
    try {
      key = pbkdf2Sync(passphraseBytes, salt, ITERATIONS, 32, "sha256");
    } finally {
      passphraseBytes.fill(0);
    }

    const ciphertextAndTag = bytes.subarray(HEADER_BYTES);
    const ciphertext = ciphertextAndTag.subarray(0, -16);
    const authTag = ciphertextAndTag.subarray(-16);
    try {
      const decipher = createDecipheriv("aes-256-gcm", key, iv, { authTagLength: 16 });
      decipher.setAAD(header);
      decipher.setAuthTag(authTag);
      plaintext = Buffer.concat([decipher.update(ciphertext), decipher.final()]);
    } catch {
      throw new Error("Could not unlock the package. Check the private repository secret and original encrypted file.");
    } finally {
      key.fill(0);
      key = null;
    }

    if (plaintext.length < 12) {
      throw new Error("The decrypted package payload is incomplete.");
    }
    const metadataLength = plaintext.readUInt32BE(0);
    const originalLength = plaintext.readUInt32BE(4);
    const wavLength = plaintext.readUInt32BE(8);
    if (!metadataLength || !originalLength || !wavLength ||
        12 + metadataLength + originalLength + wavLength !== plaintext.length) {
      throw new Error("The encrypted package has inconsistent internal lengths.");
    }

    let metadata;
    try {
      metadata = JSON.parse(plaintext.toString("utf8", 12, 12 + metadataLength));
    } catch {
      throw new Error("The authenticated package metadata is malformed.");
    }

    const originalStart = 12 + metadataLength;
    const originalAudio = plaintext.subarray(originalStart, originalStart + originalLength);
    const wavStart = originalStart + originalLength;
    normalizedWav = Buffer.from(plaintext.subarray(wavStart, wavStart + wavLength));

    if (metadata?.format !== "VIOLIN-PRINCE-VOICE-VAULT" || metadata?.version !== 1 ||
        typeof metadata.transcript !== "string" || metadata.transcript.trim().length < 20 ||
        metadata.originalBytes !== originalAudio.length || metadata.wavBytes !== normalizedWav.length ||
        !Number.isFinite(metadata.durationSeconds) || metadata.durationSeconds < 10 ||
        metadata.durationSeconds > 120) {
      throw new Error("The package metadata does not match the expected enrollment format.");
    }

    validatePreparedWav(normalizedWav);
    if (sha256Hex(originalAudio) !== metadata.originalSha256 ||
        sha256Hex(normalizedWav) !== metadata.wavSha256) {
      throw new Error("The authenticated package failed its audio-integrity check.");
    }

    transferWavToCaller = true;
    return { normalizedWav, transcript: metadata.transcript };
  } finally {
    key?.fill(0);
    plaintext?.fill(0);
    bytes.fill(0);
    if (!transferWavToCaller) normalizedWav?.fill(0);
  }
}

async function main() {
  const [packagePath, outputDirectory] = process.argv.slice(2);
  if (!packagePath || !outputDirectory) {
    throw new Error("Usage: decrypt_vprvoice.mjs <encrypted-package> <temporary-output-directory>");
  }

  let passphrase = process.env.VOICE_PACKAGE_PASSPHRASE || "";
  delete process.env.VOICE_PACKAGE_PASSPHRASE;
  if (!passphrase) {
    throw new Error("The private VOICE_PACKAGE_PASSPHRASE Actions secret is not configured.");
  }

  const packageBytes = await readFile(packagePath);
  let result;
  try {
    result = decryptVprvoiceBytes(packageBytes, passphrase);
  } finally {
    packageBytes.fill(0);
    passphrase = "";
  }

  const destination = resolve(outputDirectory);
  await mkdir(destination, { recursive: true, mode: 0o700 });
  try {
    await writeFile(join(destination, "reference.wav"), result.normalizedWav, { mode: 0o600, flag: "wx" });
    await writeFile(join(destination, "reference.txt"), result.transcript, { mode: 0o600, flag: "wx" });
    console.log("Encrypted package authenticated; temporary reference files are ready.");
  } finally {
    result.normalizedWav.fill(0);
    result.transcript = "";
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : "Voice package processing failed.");
    process.exitCode = 1;
  });
}
