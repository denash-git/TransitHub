const state = {
  config: null,
  startedAt: null,
  resultText: '',
};

const elements = {
  themeToggle: document.getElementById('theme-toggle'),
  startTest: document.getElementById('start-test'),
  retest: document.getElementById('retest'),
  copyResult: document.getElementById('copy-result'),
  sessionStatus: document.getElementById('session-status'),
  connectionStatus: document.getElementById('connection-status'),
  expiresAt: document.getElementById('expires-at'),
  latencyValue: document.getElementById('latency-value'),
  downloadValue: document.getElementById('download-value'),
  uploadValue: document.getElementById('upload-value'),
  phaseLabel: document.getElementById('phase-label'),
  progressFill: document.getElementById('progress-fill'),
  sessionUrl: document.getElementById('session-url'),
  startedAt: document.getElementById('started-at'),
  clientInfo: document.getElementById('client-info'),
};

function setTheme(theme) {
  document.body.classList.toggle('theme-light', theme === 'light');
  document.body.classList.toggle('theme-dark', theme !== 'light');
  localStorage.setItem('transithub-diag-theme', theme);
  elements.themeToggle.textContent = theme === 'light' ? 'Dark Theme' : 'Light Theme';
}

function loadTheme() {
  const stored = localStorage.getItem('transithub-diag-theme');
  setTheme(stored === 'light' ? 'light' : 'dark');
}

function formatNumber(value) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return '--';
  }
  return value.toFixed(value >= 100 ? 0 : 2);
}

function setPhase(label, progressPercent) {
  elements.phaseLabel.textContent = label;
  elements.progressFill.style.width = `${progressPercent}%`;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, { cache: 'no-store', ...options });
  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }
  return response.json();
}

async function loadConfig() {
  const config = await fetchJson('./api/config');
  state.config = config;
  elements.expiresAt.textContent = new Date(config.expires_at).toLocaleString();
  elements.sessionUrl.textContent = config.public_url;
}

async function measureLatency() {
  const attempts = [];
  for (let i = 0; i < 5; i += 1) {
    const started = performance.now();
    await fetchJson(`./api/ping?cacheBust=${Date.now()}-${i}`);
    attempts.push(performance.now() - started);
  }
  attempts.sort((a, b) => a - b);
  return attempts[Math.floor(attempts.length / 2)];
}

async function downloadOnce(bytes) {
  const response = await fetch(`./api/download?bytes=${bytes}&cacheBust=${Date.now()}`, { cache: 'no-store' });
  if (!response.ok || !response.body) {
    throw new Error('Download stream failed.');
  }
  const reader = response.body.getReader();
  let received = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    received += value.byteLength;
  }
  return received;
}

async function measureDownload(bytes, streams) {
  const started = performance.now();
  const results = await Promise.all(Array.from({ length: streams }, () => downloadOnce(bytes)));
  const durationSeconds = (performance.now() - started) / 1000;
  const totalBytes = results.reduce((sum, current) => sum + current, 0);
  const mbps = (totalBytes * 8) / 1_000_000 / durationSeconds;
  return { mbps, totalBytes };
}

async function uploadOnce(payload) {
  const response = await fetch('./api/upload', {
    method: 'POST',
    cache: 'no-store',
    headers: {
      'Content-Type': 'application/octet-stream',
    },
    body: payload,
  });
  if (!response.ok) {
    throw new Error('Upload stream failed.');
  }
  return response.json();
}

async function measureUpload(bytes, streams) {
  const payload = new Uint8Array(bytes);
  const started = performance.now();
  const results = await Promise.all(Array.from({ length: streams }, () => uploadOnce(payload)));
  const durationSeconds = (performance.now() - started) / 1000;
  const totalBytes = results.reduce((sum, current) => sum + (current.received_bytes || 0), 0);
  const mbps = (totalBytes * 8) / 1_000_000 / durationSeconds;
  return { mbps, totalBytes };
}

async function publishResult(result) {
  await fetchJson('./api/report', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(result),
  });
}

function renderResult(result) {
  elements.latencyValue.textContent = formatNumber(result.latency_ms);
  elements.downloadValue.textContent = formatNumber(result.download_mbps);
  elements.uploadValue.textContent = formatNumber(result.upload_mbps);
  elements.sessionStatus.textContent = 'Completed';
  elements.connectionStatus.textContent = 'Browser HTTPS test finished';
  elements.clientInfo.textContent = navigator.userAgent;

  state.resultText = [
    `Latency: ${formatNumber(result.latency_ms)} ms`,
    `Download: ${formatNumber(result.download_mbps)} Mbps`,
    `Upload: ${formatNumber(result.upload_mbps)} Mbps`,
    `Started at: ${state.startedAt}`,
    `URL: ${state.config.public_url}`,
  ].join('\n');
}

async function runTest() {
  elements.startTest.disabled = true;
  elements.retest.disabled = true;
  elements.copyResult.disabled = true;
  elements.sessionStatus.textContent = 'Running';
  elements.connectionStatus.textContent = 'Browser HTTPS test in progress';
  state.startedAt = new Date().toLocaleString();
  elements.startedAt.textContent = state.startedAt;

  try {
    setPhase('Measuring latency', 18);
    const latency = await measureLatency();

    setPhase('Measuring download', 48);
    const download = await measureDownload(state.config.download_bytes, state.config.download_streams);

    setPhase('Measuring upload', 78);
    const upload = await measureUpload(state.config.upload_bytes, state.config.upload_streams);

    const result = {
      latency_ms: Number(latency.toFixed(2)),
      download_mbps: Number(download.mbps.toFixed(2)),
      upload_mbps: Number(upload.mbps.toFixed(2)),
      download_bytes: download.totalBytes,
      upload_bytes: upload.totalBytes,
    };

    setPhase('Publishing result', 92);
    await publishResult(result);
    renderResult(result);
    setPhase('Completed', 100);
    elements.retest.disabled = false;
    elements.copyResult.disabled = false;
  } catch (error) {
    elements.sessionStatus.textContent = 'Failed';
    elements.connectionStatus.textContent = error.message;
    setPhase('Test failed', 100);
  } finally {
    elements.startTest.disabled = false;
  }
}

async function copyResult() {
  if (!state.resultText) {
    return;
  }
  try {
    await navigator.clipboard.writeText(state.resultText);
    elements.connectionStatus.textContent = 'Result copied to clipboard';
  } catch {
    elements.connectionStatus.textContent = 'Clipboard copy is not available in this browser';
  }
}

function bindEvents() {
  elements.themeToggle.addEventListener('click', () => {
    const nextTheme = document.body.classList.contains('theme-light') ? 'dark' : 'light';
    setTheme(nextTheme);
  });
  elements.startTest.addEventListener('click', runTest);
  elements.retest.addEventListener('click', runTest);
  elements.copyResult.addEventListener('click', copyResult);
}

async function main() {
  loadTheme();
  bindEvents();
  await loadConfig();
  setPhase('Ready to start', 0);
}

main().catch((error) => {
  elements.sessionStatus.textContent = 'Failed';
  elements.connectionStatus.textContent = error.message;
});
