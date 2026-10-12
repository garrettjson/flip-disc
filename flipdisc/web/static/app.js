async function parseResponse(path, res) {
  if (res.ok) return res.json();
  // FastAPI puts the reason in `detail`; surface it instead of a bare status code
  let detail = '';
  try { detail = (await res.json()).detail || ''; } catch (_) { /* no body */ }
  throw new Error(detail || `${path} failed: ${res.status}`);
}

async function fetchJSON(path) {
  return parseResponse(path, await fetch(path));
}

async function postJSON(path, payload) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: payload ? JSON.stringify(payload) : null,
  });
  return parseResponse(path, res);
}

// Parameter schema per animation, served by GET /animations (see animations/params.py)
let paramSchemas = {};

// Inputs for the weather fetch loop (POST /weather/config). These configure the
// server's data source, not the animation, so they are not part of its schema.
const WEATHER_SOURCE_FIELDS = [
  { name: 'latitude', label: 'Latitude', type: 'float', step: 0.01, default: 40.71 },
  { name: 'longitude', label: 'Longitude', type: 'float', step: 0.01, default: -74.01 },
];

// UI elements
const runningEl = document.getElementById('running');
const connectedEl = document.getElementById('connected');
const fpsEl = document.getElementById('fps');
const presentedEl = document.getElementById('presented');
const sizeEl = document.getElementById('size');
const bufferEl = document.getElementById('buffer');
const animSelect = document.getElementById('anim');
const startBtn = document.getElementById('start');
const stopBtn = document.getElementById('stop');
const fpsInput = document.getElementById('fps-input');
const setFpsBtn = document.getElementById('set-fps');
const refreshBtn = document.getElementById('refresh');
const canvas = document.getElementById('preview');
const ctx = canvas.getContext('2d');
const paramsContainer = document.getElementById('params-container');
const paramErrorEl = document.getElementById('param-error');
const currentAnimEl = document.getElementById('current-anim');
const lastErrorEl = document.getElementById('last-error');

function drawBits(bits, width, height) {
  if (!bits || bits.length === 0) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    return;
  }
  const scaleX = canvas.width / width;
  const scaleY = canvas.height / height;
  ctx.fillStyle = 'black';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = 'white';
  for (let y = 0; y < height; y++) {
    const row = bits[y];
    for (let x = 0; x < width; x++) {
      if (row[x]) {
        ctx.fillRect(Math.floor(x * scaleX), Math.floor(y * scaleY), Math.ceil(scaleX), Math.ceil(scaleY));
      }
    }
  }
}

async function loadAnimations() {
  const data = await fetchJSON('/animations');
  paramSchemas = data.params || {};
  animSelect.innerHTML = '';
  (data.animations || []).forEach(name => {
    const opt = document.createElement('option');
    opt.value = name; opt.textContent = name;
    animSelect.appendChild(opt);
  });
  updateAnimationParams();
}

// Scalar params only: structured ones (e.g. composed `layers`) have no form control
function getAnimationParams(animationName) {
  return (paramSchemas[animationName] || []).filter(p => p.type !== 'list');
}

function extraFields(animationName) {
  return animationName === 'weather' ? WEATHER_SOURCE_FIELDS : [];
}

function isNumeric(param) {
  return param.type === 'float' || param.type === 'int';
}

function buildInput(param) {
  let input;
  if (param.choices) {
    input = document.createElement('select');
    param.choices.forEach(choice => {
      const option = document.createElement('option');
      option.value = choice;
      option.textContent = choice === '' ? '(none)' : choice;
      if (choice === param.default) option.selected = true;
      input.appendChild(option);
    });
  } else if (param.type === 'bool' && param.nullable) {
    // Three states: leave unset, on, off
    input = document.createElement('select');
    [['', '(default)'], ['true', 'on'], ['false', 'off']].forEach(([value, text]) => {
      const option = document.createElement('option');
      option.value = value; option.textContent = text;
      input.appendChild(option);
    });
    if (param.default !== null) input.value = String(param.default);
  } else if (param.type === 'bool') {
    input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = !!param.default;
  } else if (isNumeric(param)) {
    input = document.createElement('input');
    input.type = 'number';
    if (param.default !== null && param.default !== undefined) {
      // Trim float noise such as 0.3333333333333333
      input.value = Number(param.default.toFixed(4));
    }
    if (param.min !== undefined) input.min = param.min;
    if (param.max !== undefined) input.max = param.max;
    input.step = param.step !== undefined ? param.step : (param.type === 'int' ? 1 : 'any');
    if (param.nullable) input.placeholder = 'auto';
    input.style.width = '80px';
  } else {
    input = document.createElement('input');
    input.type = 'text';
    input.value = param.default ?? '';
    input.style.width = '160px';
  }
  input.id = `param-${param.name}`;
  return input;
}

// Returns undefined when the field is empty, meaning "don't send this param"
function readInput(param) {
  const input = document.getElementById(`param-${param.name}`);
  if (!input) return undefined;
  if (param.type === 'bool' && !param.nullable) return input.checked;
  if (param.type === 'bool') return input.value === '' ? undefined : input.value === 'true';
  if (isNumeric(param)) return input.value === '' ? undefined : parseFloat(input.value);
  if (param.nullable && input.value === '' && !param.choices) return undefined;
  return input.value;
}

function showParamError(message) {
  paramErrorEl.textContent = message || '';
}

function updateAnimationParams() {
  const selectedAnim = animSelect.value;
  const params = getAnimationParams(selectedAnim);
  const extras = extraFields(selectedAnim);

  paramsContainer.innerHTML = '';
  showParamError('');

  if (params.length + extras.length === 0) {
    paramsContainer.innerHTML = '<p style="color: #666; font-style: italic;">No configurable parameters</p>';
    return;
  }

  const addRow = (param, onChange) => {
    const row = document.createElement('div');
    row.style.marginBottom = '8px';

    const label = document.createElement('label');
    label.textContent = param.label + (param.unit ? ` (${param.unit})` : '') + ':';
    label.style.display = 'inline-block';
    label.style.width = '190px';
    label.style.fontWeight = 'bold';

    const input = buildInput(param);
    if (onChange) input.addEventListener('change', onChange);

    row.appendChild(label);
    row.appendChild(input);
    paramsContainer.appendChild(row);
  };

  extras.forEach(field => addRow(field, null));
  params.forEach(param => addRow(param, () => configureParam(param)));
}

// Push one changed parameter to the running animation
async function configureParam(param) {
  const value = readInput(param);
  if (value === undefined) return;

  try {
    await postJSON('/animations/configure', { [param.name]: value });
    showParamError('');
  } catch (error) {
    showParamError(error.message);
  }
}

async function refreshStatus() {
  const s = await fetchJSON('/status');
  // Adapt to pipeline-shaped status
  const p = s.pipeline || {};
  runningEl.textContent = p.running ? 'Yes' : 'No';
  connectedEl.textContent = p.serial_connected ? 'Yes' : 'No';
  fpsEl.textContent = s.config?.refresh_rate ?? '-';
  presentedEl.textContent = (p.frames_presented ?? 0).toString();
  currentAnimEl.textContent = p.animation ?? '-';
  lastErrorEl.textContent = p.last_error ?? '';
  if (s.config) {
    sizeEl.textContent = `${s.config.width} x ${s.config.height}`;
  }
  const cap = p.buffer_capacity !== undefined ? p.buffer_capacity : '-';
  bufferEl.textContent = `capacity ${cap}`;
}

// Live preview over WebSocket; falls back to HTTP polling on disconnect
let previewWS = null;
function connectPreviewWS() {
  try {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    previewWS = new WebSocket(`${proto}://${window.location.host}/ws/preview`);
    previewWS.onmessage = (ev) => {
      try {
        const p = JSON.parse(ev.data);
        drawBits(p.bits, p.width, p.height);
      } catch (_) {
        // ignore
      }
    };
    previewWS.onclose = () => {
      // Retry after a short delay
      setTimeout(connectPreviewWS, 2000);
    };
  } catch (_) {
    // ignore
  }
}

async function startSelected() {
  const name = animSelect.value;
  if (!name) {
    if (animSelect.options.length > 0) {
      animSelect.selectedIndex = 0;
    } else {
      return;
    }
  }
  const sel = animSelect.value;

  const params = {};
  getAnimationParams(sel).forEach(param => {
    const value = readInput(param);
    if (value !== undefined) params[param.name] = value;
  });

  try {
    await postJSON(`/anim/${encodeURIComponent(sel)}`, params);

    // For weather, also configure the background fetch loop
    if (sel === 'weather') {
      const source = { unit: params.unit };
      WEATHER_SOURCE_FIELDS.forEach(field => { source[field.name] = readInput(field); });
      await postJSON('/weather/config', source);
    }
    showParamError('');
  } catch (error) {
    showParamError(error.message);
  }

  await refreshStatus();
}
async function stopAnimation() {
  await postJSON('/animations/stop');
  await refreshStatus();
}
// Clear/reset removed from UI; only start/stop remain.
async function setFps() {
  const v = parseFloat(fpsInput.value || '0');
  if (v > 0) {
    await postJSON(`/fps?new_fps=${encodeURIComponent(v)}`);
    await refreshStatus();
  }
}

startBtn.addEventListener('click', startSelected);
setFpsBtn.addEventListener('click', setFps);
refreshBtn.addEventListener('click', refreshStatus);
stopBtn.addEventListener('click', stopAnimation);
animSelect.addEventListener('change', updateAnimationParams);

// Init
(async function init() {
  await loadAnimations();
  // Default to weather animation if available, otherwise first
  const weatherOpt = Array.from(animSelect.options).findIndex(o => o.value === 'weather');
  if (weatherOpt >= 0) {
    animSelect.selectedIndex = weatherOpt;
  } else if (animSelect.options.length > 0 && !animSelect.value) {
    animSelect.selectedIndex = 0;
  }
  updateAnimationParams();
  await refreshStatus();
  connectPreviewWS();
  setInterval(refreshStatus, 1000);
})();
