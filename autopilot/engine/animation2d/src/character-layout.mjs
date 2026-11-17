/** Fit an authored character canvas into the target composition without distortion. */
export function fitCharacterToCanvas(character, canvasWidth, canvasHeight) {
  // Fall back only when a source dimension is absent; preserve explicit zero
  // and other invalid values so the validation below can reject them.
  const sourceWidth = Number(character?.canvas?.width ?? canvasWidth);
  const sourceHeight = Number(character?.canvas?.height ?? canvasHeight);
  const targetWidth = Number(canvasWidth);
  const targetHeight = Number(canvasHeight);

  if (![sourceWidth, sourceHeight, targetWidth, targetHeight].every(Number.isFinite) ||
      sourceWidth <= 0 || sourceHeight <= 0 || targetWidth <= 0 || targetHeight <= 0) {
    throw new TypeError("Character and composition canvas dimensions must be positive finite numbers.");
  }

  const scale = Math.min(targetWidth / sourceWidth, targetHeight / sourceHeight);
  const fittedWidth = sourceWidth * scale;
  const fittedHeight = sourceHeight * scale;
  return {
    sourceWidth,
    sourceHeight,
    scale,
    offsetX: (targetWidth - fittedWidth) / 2,
    offsetY: (targetHeight - fittedHeight) / 2,
    width: fittedWidth,
    height: fittedHeight
  };
}
