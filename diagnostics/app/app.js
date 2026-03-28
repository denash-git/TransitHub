const state = {
  config: null,
  countdownTimer: null,
  running: false,
};

const elements = {
  themeToggle: document.getElementById('theme-toggle'),
  themeIcon: document.getElementById('theme-icon'),
  expiresSeconds: document.getElementById('expires-seconds'),
  statusLine: document.getElementById('status-line'),
  pingValue: document.getElementById('ping-value'),
  downloadValue: document.getElementById('download-value'),
  uploadValue: document.getElementById('upload-value'),
  phaseLabel: document.getElementById('phase-label'),
  progressText: document.getElementById('progress-text'),
  progressFill: document.getElementById('progress-fill'),
  startTest: document.getElementById('start-test'),
};

function setTheme(theme) {
  const isLight = theme === 'light';
  document.body.classList.toggle('theme-light', isLight);
  document.body.classList.toggle('theme-dark', !isLight);
  localStorage.setItem('transithub-diag-theme', isLight ? 'light' : 'dark');
  elements.themeIcon.textContent = isLight ? '☾' : '☀';
  elements.themeToggle.setAttribute('aria-label', isLight ? 'Switch to dark theme' : 'Switch to light theme');
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

function setPhase(label, percent) {
  const clamped = Math.max(0, Math.min(100, percent));
  elements.phaseLabel.textContent = label;
  elements.progressText.textContent = `${Math.round(clamped)}%`;
  elements.progressFill.style.width = `${clamped}%`;
}

function setStatus(text) {
  elements.statusLine.textContent = text;
}

function setMetrics({ ping = '--', download = '--', upload = '--' } = {}) {
  elements.pingValue.textContent = ping;
  elements.downloadValue.textContent = download;
  elements.uploadValue.textContent = upload;
}

async function fetchJson(url, options = {}) {
  const response = await fetch(url, { cache: 'no-store', ...options });
  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`);
  }
  return response.json();
}

function isExpired() {
  if (!state.config) {
    return false;
  }
  return Date.now() >= new Date(state.config.expires_at).getTime();
}

function updateExpiryCountdown() {
  if (!state.config) {
    return;
  }
  const diffMs = new Date(state.config.expires_at).getTime() - Date.now();
  const seconds = Math.max(0, Math.ceil(diffMs / 1000));
  elements.expiresSeconds.textContent = `${seconds}`;

  if (seconds === 0) {
    if (state.countdownTimer) {
      clearInterval(state.countdownTimer);
      state.countdownTimer = null;
    }
    elements.startTest.disabled = true;
    if (!state.running) {
      setStatus('Session expired. Create a new browser link from TransitHub menu.');
      setPhase('Session expired', 100);
    }
  }
}

function startExpiryCountdown() {
  updateExpiryCountdown();
  if (state.countdownTimer) {
    clearInterval(state.countdownTimer);
  }
  state.countdownTimer = window.setInterval(updateExpiryCountdown, 1000);
}

async function loadConfig() {
  state.config = await fetchJson('./api/config');
  startExpiryCountdown();
}

async function measureLatency() {
  const attempts = [];
  for (let index = 0; index < 5; index += 1) {
    const started = performance.now();
    await fetchJson(`./api/ping?cacheBust=${Date.now()}-${index}`);
    attempts.push(performance.now() - started);
  }
  attempts.sort((left, right) => left - right);
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
  return {
    totalBytes,
    mbps: (totalBytes * 8) / 1_000_000 / durationSeconds,
  };
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
  return {
    totalBytes,
    mbps: (totalBytes * 8) / 1_000_000 / durationSeconds,
  };
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

async function runTest() {
  if (state.running || isExpired()) {
    if (isExpired()) {
      setStatus('Session expired. Create a new browser link from TransitHub menu.');
      setPhase('Session expired', 100);
    }
    return;
  }

  state.running = true;
  elements.startTest.disabled = true;
  setMetrics();

  try {
    setStatus('Measuring browser HTTPS path to the VPS.');

    setPhase('Measuring ping', 16);
    const latency = await measureLatency();
    elements.pingValue.textContent = formatNumber(latency);

    setPhase('Measuring download', 46);
    const download = await measureDownload(state.config.download_bytes, state.config.download_streams);
    elements.downloadValue.textContent = formatNumber(download.mbps);

    setPhase('Measuring upload', 78);
    const upload = await measureUpload(state.config.upload_bytes, state.config.upload_streams);
    elements.uploadValue.textContent = formatNumber(upload.mbps);

    const result = {
      latency_ms: Number(latency.toFixed(2)),
      download_mbps: Number(download.mbps.toFixed(2)),
      upload_mbps: Number(upload.mbps.toFixed(2)),
      download_bytes: download.totalBytes,
      upload_bytes: upload.totalBytes,
    };

    setPhase('Publishing result', 92);
    await publishResult(result);

    setStatus('Current browser session completed successfully.');
    setPhase('Completed', 100);
  } catch (error) {
    setStatus(error.message);
    setPhase('Test failed', 100);
  } finally {
    state.running = false;
    elements.startTest.disabled = isExpired();
  }
}

function bindEvents() {
  elements.themeToggle.addEventListener('click', () => {
    const nextTheme = document.body.classList.contains('theme-light') ? 'dark' : 'light';
    setTheme(nextTheme);
  });
  elements.startTest.addEventListener('click', runTest);
}

async function main() {
  loadTheme();
  bindEvents();
  setMetrics();
  setPhase('Waiting for start', 0);
  setStatus('Ready to start HTTPS browser test.');
  await loadConfig();
}

main().catch((error) => {
  setStatus(error.message);
  setPhase('Initialization failed', 100);
  elements.startTest.disabled = true;
});
