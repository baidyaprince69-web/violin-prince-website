import { createVoicePackage, openVoicePackage, encodeMonoPcm16Wav, MAX_ORIGINAL_BYTES, MAX_PACKAGE_BYTES, VOICE_SAMPLE_RATE } from "./voice-package.mjs";
import { GOOGLE_OAUTH_CLIENT_ID } from "./config.mjs";

const $ = (id) => document.getElementById(id);
const DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file";
const DRIVE_API = "https://www.googleapis.com/drive/v3";
const DRIVE_UPLOAD_API = "https://www.googleapis.com/upload/drive/v3";
const FOLDER_NAME = "Violin Prince Voice Vault";
const FOLDER_PROPERTY = "vpVoiceVault";
const MAX_RECORDING_SECONDS = 120;
let selected = null;
let previewUrl = null;
let recorder = null;
let recorderStream = null;
let recorderChunks = [];
let recordingStartedAt = 0;
let clockTimer = null;
let accessToken = null;
let accessTokenExpiresAt = 0;
let googleLoadPromise = null;

function setStatus(elementId, message, kind = "") {
  const element = $(elementId);
  if (!element) return;
  element.textContent = message;
  element.classList.remove("success", "error");
  if (kind) element.classList.add(kind);
}
function safeError(error, fallback) {
  const message = error instanceof Error ? error.message : "";
  return message && message.length < 240 ? message : fallback;
}
function clearSelected() {
  selected = null;
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = null;
  $("preview-wrap").hidden = true;
  $("audio-preview").removeAttribute("src");
  $("recording-details").textContent = "";
  updateSaveState();
}
function updateSaveState() {
  const transcript = $("transcript").value.trim();
  const passphrase = $("passphrase").value;
  const confirmed = $("passphrase-confirm").value;
  const valid = Boolean(
    selected &&
    transcript.length >= 20 &&
    transcript.split(/\s+/).filter(Boolean).length >= 5 &&
    accessToken && accessTokenExpiresAt > Date.now() + 5000 &&
    passphrase.length >= 12 &&
    passphrase === confirmed &&
    $("acknowledge-encryption").checked
  );
  $("save-recording").disabled = !valid;
}
function updateClock(seconds) {
  const value = Math.max(0, Math.floor(seconds));
  const minutes = String(Math.floor(value / 60)).padStart(2, "0");
  const remaining = String(value % 60).padStart(2, "0");
  $("recording-clock").textContent = minutes + ":" + remaining;
}

async function prepareAudio(blob, filename) {
  if (!(blob instanceof Blob) || !blob.size) throw new Error("The selected recording is empty.");
  if (blob.size > MAX_ORIGINAL_BYTES) throw new Error("Choose a recording smaller than 20 MB.");
  const originalBytes = new Uint8Array(await blob.arrayBuffer());
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextClass || !window.OfflineAudioContext) {
    throw new Error("This browser does not support secure local audio preparation. Try an updated Chrome or Edge browser.");
  }
  const context = new AudioContextClass();
  let decoded;
  try {
    decoded = await context.decodeAudioData(originalBytes.slice().buffer);
  } catch {
    throw new Error("The browser could not decode this audio file. Try WAV, MP3, M4A, WebM or OGG.");
  } finally {
    try { await context.close(); } catch { /* No device resources remain. */ }
  }
  if (!Number.isFinite(decoded.duration) || decoded.duration < 10 || decoded.duration > MAX_RECORDING_SECONDS) {
    throw new Error("Recording must be between 10 seconds and 2 minutes. A clean 30–60 second sample is recommended.");
  }
  const outputFrames = Math.ceil(decoded.duration * VOICE_SAMPLE_RATE);
  const offline = new OfflineAudioContext(1, outputFrames, VOICE_SAMPLE_RATE);
  const source = offline.createBufferSource();
  source.buffer = decoded;
  source.connect(offline.destination);
  source.start(0);
  const normalized = await offline.startRendering();
  const wavBytes = encodeMonoPcm16Wav(normalized);

  clearSelected();
  selected = {
    blob,
    originalBytes,
    wavBytes,
    originalName: String(filename || "voice-reference.webm"),
    originalType: blob.type || "application/octet-stream",
    durationSeconds: decoded.duration
  };
  previewUrl = URL.createObjectURL(blob);
  $("audio-preview").src = previewUrl;
  $("preview-wrap").hidden = false;
  $("recording-details").textContent =
    decoded.duration.toFixed(1) + " sec · original " + (blob.size / 1024 / 1024).toFixed(2) +
    " MB · prepared WAV 24 kHz mono";
  setStatus("recording-status", "Recording prepared locally. Nothing has been uploaded.", "success");
  updateSaveState();
}

function stopTracks() {
  if (recorderStream) {
    for (const track of recorderStream.getTracks()) track.stop();
    recorderStream = null;
  }
}
function stopClock() {
  if (clockTimer !== null) window.clearInterval(clockTimer);
  clockTimer = null;
}
async function startRecording() {
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    setStatus("recording-status", "Microphone recording is not available in this browser. Use the audio-file upload option instead.", "error");
    return;
  }
  try {
    clearSelected();
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false }
    });
    recorderStream = stream;
    const formats = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/mp4"];
    const mimeType = formats.find(type => MediaRecorder.isTypeSupported(type));
    recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
    recorderChunks = [];
    recorder.ondataavailable = event => {
      if (event.data?.size) recorderChunks.push(event.data);
    };
    recorder.onerror = () => {
      stopTracks();
      stopClock();
      $("start-recording").disabled = false;
      $("stop-recording").disabled = true;
      setStatus("recording-status", "The microphone recording stopped unexpectedly. Please try again.", "error");
    };
    recorder.onstop = async () => {
      stopTracks();
      stopClock();
      $("start-recording").disabled = false;
      $("stop-recording").disabled = true;
      const actualType = recorder?.mimeType || mimeType || "audio/webm";
      const extension = actualType.includes("ogg") ? "ogg" : actualType.includes("mp4") ? "m4a" : "webm";
      const blob = new Blob(recorderChunks, { type: actualType });
      recorderChunks = [];
      try {
        await prepareAudio(blob, "violin-prince-voice-reference." + extension);
      } catch (error) {
        clearSelected();
        setStatus("recording-status", safeError(error, "Could not prepare the microphone recording."), "error");
      } finally {
        recorder = null;
      }
    };
    recordingStartedAt = Date.now();
    recorder.start(250);
    $("start-recording").disabled = true;
    $("stop-recording").disabled = false;
    setStatus("recording-status", "Recording locally. Press Stop when you have finished reading your reference.", "success");
    updateClock(0);
    clockTimer = window.setInterval(() => {
      const elapsed = (Date.now() - recordingStartedAt) / 1000;
      updateClock(elapsed);
      if (elapsed >= MAX_RECORDING_SECONDS && recorder?.state === "recording") recorder.stop();
    }, 250);
  } catch (error) {
    stopTracks();
    stopClock();
    setStatus("recording-status", safeError(error, "Microphone permission was not granted."), "error");
  }
}
function stopRecording() {
  if (recorder?.state === "recording") recorder.stop();
}

function loadGoogleIdentity() {
  if (window.google?.accounts?.oauth2) return Promise.resolve();
  if (googleLoadPromise) return googleLoadPromise;
  googleLoadPromise = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.onload = () => window.google?.accounts?.oauth2
      ? resolve()
      : reject(new Error("Google authorization loaded but its API is unavailable."));
    script.onerror = () => reject(new Error("Could not load Google authorization. Check your connection and reload."));
    document.head.append(script);
  }).catch(error => {
    googleLoadPromise = null;
    throw error;
  });
  return googleLoadPromise;
}
function connectGoogleDrive() {
  if (!GOOGLE_OAUTH_CLIENT_ID || GOOGLE_OAUTH_CLIENT_ID.includes("REPLACE_ME")) {
    return Promise.reject(new Error("The Google OAuth client ID has not been configured for this site yet."));
  }
  const oauth = window.google?.accounts?.oauth2;
  if (!oauth) return Promise.reject(new Error("Google authorization is still loading. Wait for the Connect button to become available."));
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (error) => {
      if (settled) return;
      settled = true;
      if (error) reject(error);
      else resolve();
    };
    try {
      const client = oauth.initTokenClient({
        client_id: GOOGLE_OAUTH_CLIENT_ID,
        scope: DRIVE_SCOPE,
        include_granted_scopes: true,
        callback: response => {
          if (response.error || !response.access_token) {
            accessToken = null;
            accessTokenExpiresAt = 0;
            finish(new Error(response.error_description || response.error || "Google did not return an access token."));
            return;
          }
          accessToken = response.access_token;
          accessTokenExpiresAt = Date.now() + Math.max(60, Number(response.expires_in) || 3600) * 1000;
          $("drive-status").textContent = "Connected for this browser session. The access token is held only in page memory.";
          $("connect-drive").textContent = "Disconnect";
          setStatus("upload-status", "Google Drive connected. Your recording is still only in this browser.");
          updateSaveState();
          finish();
        },
        error_callback: error => finish(new Error(error.message || "Google authorization popup could not be completed."))
      });
      client.requestAccessToken({ prompt: "select_account" });
    } catch (error) {
      finish(error instanceof Error ? error : new Error(String(error)));
    }
  });
}
function disconnectGoogleDrive() {
  accessToken = null;
  accessTokenExpiresAt = 0;
  $("drive-status").textContent = "Disconnected. No Google access token remains in this page.";
  $("connect-drive").textContent = "Connect Google Drive";
  $("drive-folder-link").hidden = true;
  updateSaveState();
}
function requireAccessToken() {
  if (!accessToken || accessTokenExpiresAt <= Date.now() + 5000) {
    disconnectGoogleDrive();
    throw new Error("Your Google Drive session expired. Connect again and retry.");
  }
  return accessToken;
}
async function driveRequest(url, init = {}) {
  const token = requireAccessToken();
  const headers = new Headers(init.headers || {});
  headers.set("Authorization", "Bearer " + token);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  const response = await fetch(url, { ...init, headers });
  if (!response.ok) {
    if (response.status === 401) disconnectGoogleDrive();
    let detail = "";
    try {
      const body = await response.json();
      detail = body?.error?.message ? ": " + String(body.error.message).slice(0, 160) : "";
    } catch { /* Do not expose raw server responses. */ }
    throw new Error("Google Drive request failed (HTTP " + response.status + ")" + detail + ".");
  }
  return response.status === 204 ? null : await response.json();
}
async function findOrCreateVaultFolder() {
  const query = new URLSearchParams({
    q: "name = '" + FOLDER_NAME + "' and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
    pageSize: "100",
    fields: "files(id,name,mimeType,shared,webViewLink,appProperties)"
  });
  const found = await driveRequest(DRIVE_API + "/files?" + query.toString());
  const ownFolders = (found.files || []).filter(file =>
    file.name === FOLDER_NAME && file.mimeType === "application/vnd.google-apps.folder" &&
    file.appProperties?.[FOLDER_PROPERTY] === "1"
  );
  const existing = ownFolders.find(file => file.shared === false);
  if (existing) return existing;
  if (ownFolders.some(file => file.shared === true)) {
    throw new Error("An existing Voice Vault folder is shared. Remove its sharing in Google Drive before using it.");
  }
  const created = await driveRequest(DRIVE_API + "/files?fields=id,name,mimeType,shared,webViewLink,appProperties", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: FOLDER_NAME,
      mimeType: "application/vnd.google-apps.folder",
      appProperties: { [FOLDER_PROPERTY]: "1", app: "ViolinPrinceVoiceVault" }
    })
  });
  if (!created?.id) throw new Error("Google Drive did not return the new Voice Vault folder ID.");
  if (created.shared !== false) {
    await driveRequest(DRIVE_API + "/files/" + encodeURIComponent(created.id), { method: "DELETE" });
    throw new Error("Google Drive reports that the new Voice Vault folder is shared. Upload has been blocked.");
  }
  return created;
}
async function verifyUploadedFileIsPrivate(fileId) {
  const fields = "id,shared,permissions(type,role,domain,emailAddress)";
  const info = await driveRequest(DRIVE_API + "/files/" + encodeURIComponent(fileId) + "?fields=" + encodeURIComponent(fields));
  const permissions = Array.isArray(info?.permissions) ? info.permissions : [];
  const publicPermission = permissions.some(item => item.type === "anyone" || item.type === "domain");
  if (info?.shared !== false || publicPermission) {
    try { await driveRequest(DRIVE_API + "/files/" + encodeURIComponent(fileId), { method: "DELETE" }); } catch { /* Keep the privacy warning if cleanup is denied. */ }
    throw new Error("Google Drive reports that the uploaded file is shared. The upload has been blocked and cleanup was attempted. Review Drive sharing settings.");
  }
  return true;
}
async function uploadEncryptedPackage(encryptedBytes) {
  const folder = await findOrCreateVaultFolder();
  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  const filename = "violin-prince-voice-" + timestamp + ".vprvoice";
  const boundary = "vpvoice_" + crypto.randomUUID().replace(/-/g, "");
  const metadata = {
    name: filename,
    mimeType: "application/octet-stream",
    parents: [folder.id],
    appProperties: { vpVoiceVault: "1", packageVersion: "1" }
  };
  const body = new Blob([
    "--" + boundary + "\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n",
    JSON.stringify(metadata),
    "\r\n--" + boundary + "\r\nContent-Type: application/octet-stream\r\n\r\n",
    encryptedBytes,
    "\r\n--" + boundary + "--"
  ], { type: "multipart/related; boundary=" + boundary });
  const result = await driveRequest(
    DRIVE_UPLOAD_API + "/files?uploadType=multipart&fields=id,name,createdTime,webViewLink",
    { method: "POST", headers: { "Content-Type": "multipart/related; boundary=" + boundary }, body }
  );
  if (!result?.id || !result.name) throw new Error("Google Drive did not confirm the encrypted upload.");
  await verifyUploadedFileIsPrivate(result.id);
  const folderLink = folder.webViewLink || "https://drive.google.com/drive/u/0/folders/" + encodeURIComponent(folder.id);
  return { fileName: result.name, folderLink };
}
function validateForm() {
  if (!selected) throw new Error("Record your voice or select an audio file first.");
  const transcript = $("transcript").value.trim();
  if (transcript.length < 20 || transcript.split(/\s+/).filter(Boolean).length < 5) {
    throw new Error("Enter the exact transcript of your recording.");
  }
  const passphrase = $("passphrase").value;
  if (passphrase.length < 12 || passphrase !== $("passphrase-confirm").value) {
    throw new Error("Passphrases must match and contain at least 12 characters.");
  }
  if (!$("acknowledge-encryption").checked) throw new Error("Confirm that you will keep your encryption passphrase safe.");
  requireAccessToken();
  return { transcript, passphrase };
}
async function saveRecording() {
  try {
    const { transcript, passphrase } = validateForm();
    $("save-recording").disabled = true;
    $("save-recording").textContent = "Preparing local encrypted package…";
    setStatus("upload-status", "Preparing audio and encrypting it in this browser. No plaintext audio is sent to Google Drive.");
    const encrypted = await createVoicePackage({
      originalBytes: selected.originalBytes,
      wavBytes: selected.wavBytes,
      transcript,
      originalName: selected.originalName,
      originalType: selected.originalType,
      durationSeconds: selected.durationSeconds
    }, passphrase);
    if (encrypted.length > MAX_PACKAGE_BYTES) throw new Error("The encrypted voice package exceeds the 50 MB limit.");
    $("save-recording").textContent = "Uploading encrypted package…";
    const result = await uploadEncryptedPackage(encrypted);
    $("drive-folder-link").href = result.folderLink;
    $("drive-folder-link").hidden = false;
    $("passphrase").value = "";
    $("passphrase-confirm").value = "";
    $("acknowledge-encryption").checked = false;
    setStatus("upload-status", "Encrypted voice package saved: " + result.fileName + ". The Drive privacy check passed. Keep your passphrase safe.", "success");
  } catch (error) {
    setStatus("upload-status", safeError(error, "Could not save the encrypted voice package."), "error");
  } finally {
    $("save-recording").textContent = "Encrypt and save to my Google Drive";
    updateSaveState();
  }
}

function downloadBytes(bytes, filename, type) {
  const url = URL.createObjectURL(new Blob([bytes], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.hidden = true;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
}
function safeDownloadName(name) {
  return String(name || "voice-reference").split(/[\\/]/).pop().replace(/[^a-zA-Z0-9._-]/g, "_").slice(0, 100) || "voice-reference";
}
async function unlockPackage() {
  const file = $("vault-file").files?.[0];
  if (!file) {
    setStatus("restore-status", "Choose your .vprvoice package first.", "error");
    return;
  }
  if (file.size > MAX_PACKAGE_BYTES) {
    setStatus("restore-status", "This package exceeds the 50 MB safety limit.", "error");
    return;
  }
  const passphrase = $("restore-passphrase").value;
  try {
    $("unlock-package").disabled = true;
    setStatus("restore-status", "Unlocking and checking the encrypted package locally…");
    const opened = await openVoicePackage(new Uint8Array(await file.arrayBuffer()), passphrase);
    const base = safeDownloadName(opened.metadata.originalFileName).replace(/\.[^.]+$/, "") || "voice-reference";
    downloadBytes(opened.originalAudio, safeDownloadName(opened.metadata.originalFileName), opened.metadata.originalMimeType || "application/octet-stream");
    downloadBytes(opened.normalizedWav, base + "-24khz-mono.wav", "audio/wav");
    downloadBytes(new TextEncoder().encode(opened.metadata.transcript), base + "-transcript.txt", "text/plain;charset=utf-8");
    setStatus("restore-status", "Package unlocked and integrity-checked. The original recording, model-ready WAV and transcript were downloaded to this device.", "success");
    $("restore-passphrase").value = "";
  } catch (error) {
    setStatus("restore-status", safeError(error, "Could not unlock this voice package."), "error");
  } finally {
    $("unlock-package").disabled = !$("vault-file").files?.length;
  }
}

$("connect-drive").disabled = true;
setStatus("drive-status", "Loading Google's secure authorisation service…");
loadGoogleIdentity().then(() => {
  $("drive-status").textContent = "Google authorisation is ready. Connect your account to save the encrypted package.";
  $("connect-drive").disabled = false;
}).catch(error => {
  $("drive-status").textContent = safeError(error, "Could not load Google authorisation.");
  $("connect-drive").disabled = true;
});

$("start-recording").addEventListener("click", startRecording);
$("stop-recording").addEventListener("click", stopRecording);
$("audio-file").addEventListener("change", async event => {
  const file = event.target.files?.[0];
  if (!file) return;
  try {
    await prepareAudio(file, file.name);
  } catch (error) {
    clearSelected();
    setStatus("recording-status", safeError(error, "Could not prepare this audio file."), "error");
  }
});
$("transcript").addEventListener("input", () => {
  $("transcript-count").textContent = $("transcript").value.length + " characters";
  updateSaveState();
});
for (const id of ["passphrase", "passphrase-confirm", "acknowledge-encryption"]) {
  $(id).addEventListener(id === "acknowledge-encryption" ? "change" : "input", updateSaveState);
}
$("connect-drive").addEventListener("click", async () => {
  if (accessToken) {
    disconnectGoogleDrive();
    return;
  }
  $("connect-drive").disabled = true;
  try {
    await connectGoogleDrive();
  } catch (error) {
    setStatus("drive-status", safeError(error, "Could not connect Google Drive."), "error");
  } finally {
    $("connect-drive").disabled = false;
    updateSaveState();
  }
});
$("save-recording").addEventListener("click", saveRecording);
$("vault-file").addEventListener("change", () => {
  $("unlock-package").disabled = !$("vault-file").files?.length;
});
$("unlock-package").addEventListener("click", unlockPackage);
window.addEventListener("pagehide", () => {
  stopClock();
  if (recorder?.state === "recording") {
    try { recorder.stop(); } catch { /* The page is closing. */ }
  }
  stopTracks();
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  accessToken = null;
  accessTokenExpiresAt = 0;
});
