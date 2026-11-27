export const AUDIO_ANALYSIS_SAMPLE_RATE = 8000;
const DEFAULT_LEVEL = 0.06;

function percentile(sortedValues, fraction) {
  const index = Math.min(
    sortedValues.length - 1,
    Math.max(0, Math.floor((sortedValues.length - 1) * fraction)),
  );
  return sortedValues[index] ?? 0;
}

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

/**
 * Converts mono float32 PCM into a normalized per-frame loudness envelope.
 * This is time-domain RMS analysis, not frequency-band or beat detection.
 */
export function buildAudioEnvelope(
  pcmBuffer,
  {
    durationSeconds,
    sampleRate = AUDIO_ANALYSIS_SAMPLE_RATE,
    fps = 25,
  } = {},
) {
  if (!Buffer.isBuffer(pcmBuffer)) {
    throw new TypeError("Audio analysis expects a Node.js Buffer containing float32 PCM.");
  }
  if (pcmBuffer.length % 4 !== 0) {
    throw new Error("The decoded float32 PCM buffer has an incomplete sample.");
  }
  if (!Number.isFinite(sampleRate) || sampleRate <= 0 || !Number.isFinite(fps) || fps <= 0) {
    throw new Error("Audio analysis requires positive sample-rate and frame-rate values.");
  }
  if (!Number.isFinite(durationSeconds) || durationSeconds <= 0) {
    throw new Error("Audio analysis requires a positive source duration.");
  }

  const frameCount = Math.ceil(durationSeconds * fps);
  const sampleCount = pcmBuffer.length / 4;
  const rawLevels = [];

  for (let frame = 0; frame < frameCount; frame += 1) {
    const start = Math.floor((frame * sampleRate) / fps);
    const end = Math.min(sampleCount, Math.floor(((frame + 1) * sampleRate) / fps));
    if (start >= sampleCount || end <= start) {
      rawLevels.push(0);
      continue;
    }

    let sumSquares = 0;
    let samplesRead = 0;
    for (let sample = start; sample < end; sample += 1) {
      const value = pcmBuffer.readFloatLE(sample * 4);
      if (!Number.isFinite(value)) {
        throw new Error("Audio analysis encountered a non-finite PCM sample.");
      }
      sumSquares += value * value;
      samplesRead += 1;
    }
    rawLevels.push(samplesRead > 0 ? Math.sqrt(sumSquares / samplesRead) : 0);
  }

  const sorted = [...rawLevels].sort((a, b) => a - b);
  const low = percentile(sorted, 0.1);
  const high = percentile(sorted, 0.95);

  if (high < 0.00001) {
    return rawLevels.map(() => DEFAULT_LEVEL);
  }

  const nearlyConstant = high - low < high * 0.075;
  const floor = low * 0.45;
  const range = Math.max(0.00001, high - floor);
  const shaped = rawLevels.map((level) => {
    const normalized = nearlyConstant
      ? 0.48
      : clamp((level - floor) / range, 0, 1);
    return Math.round(Math.pow(normalized, 0.8) * 1000) / 1000;
  });

  // Fast attack and softer release keep the graphic responsive without jitter.
  let smoothed = shaped[0] ?? DEFAULT_LEVEL;
  for (let frame = 0; frame < shaped.length; frame += 1) {
    const target = shaped[frame];
    const coefficient = target > smoothed ? 0.72 : 0.34;
    smoothed += (target - smoothed) * coefficient;
    shaped[frame] = Math.round(clamp(smoothed, 0, 1) * 1000) / 1000;
  }

  return shaped;
}
