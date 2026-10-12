async function fetchJSON(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path} failed: ${res.status}`);
  return res.json();
}

async function postJSON(path, payload) {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: payload ? JSON.stringify(payload) : null,
  });
  if (!res.ok) throw new Error(`${path} failed: ${res.status}`);
  return res.json();
}

let availableFonts = ['standard'];

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
  animSelect.innerHTML = '';
  (data.animations || []).forEach(name => {
    const opt = document.createElement('option');
    opt.value = name; opt.textContent = name;
    animSelect.appendChild(opt);
  });
  updateAnimationParams();
}

function getAnimationParams(animationName) {
  const params = {
    bouncing_dot: [
      { name: 'start_x', label: 'Start X', type: 'number', min: 0, max: 39, value: 2 },
      { name: 'start_y', label: 'Start Y', type: 'number', min: 0, max: 27, value: 5 },
      { name: 'speed_x', label: 'Speed X (px/s)', type: 'number', min: -100, max: 100, step: 5, value: 20 },
      { name: 'speed_y', label: 'Speed Y (px/s)', type: 'number', min: -100, max: 100, step: 5, value: 40 }
    ],
    life: [
      { name: 'density', label: 'Density', type: 'number', min: 0.1, max: 0.9, step: 0.1, value: 0.3 },
      { name: 'pattern', label: 'Pattern', type: 'select', options: ['random', 'glider', 'blinker', 'block', 'beacon'], value: 'random' },
      { name: 'rate', label: 'Generations/s', type: 'number', min: 1, max: 30, step: 1, value: 20 }
    ],
    simplex_noise: [
      { name: 'scale', label: 'Scale', type: 'number', min: 1, max: 20, step: 0.5, value: 4.0 },
      { name: 'speed', label: 'Speed', type: 'number', min: 0.2, max: 10, step: 0.2, value: 1.0 }
    ],
    wireframe_cube: [
      { name: 'size', label: 'Size', type: 'number', min: 0.1, max: 0.5, step: 0.05, value: 0.35 },
      { name: 'rotation_speed', label: 'Rot Speed (rad/s)', type: 'number', min: 0.05, max: 2.0, step: 0.05, value: 0.35 },
      { name: 'axis_x', label: 'Axis X', type: 'number', min: 0, max: 2.0, step: 0.1, value: 1.0 },
      { name: 'axis_y', label: 'Axis Y', type: 'number', min: 0, max: 2.0, step: 0.1, value: 0.7 },
      { name: 'axis_z', label: 'Axis Z', type: 'number', min: 0, max: 2.0, step: 0.1, value: 0.3 }
    ],
    text: [
      { name: 'text', label: 'Text', type: 'text', value: 'HELLO' },
      { name: 'mode', label: 'Mode', type: 'select', options: ['static', 'scroll_left', 'scroll_up', 'scroll_down'], value: 'scroll_left' },
      { name: 'font', label: 'Font', type: 'select', options: availableFonts, value: availableFonts[0] },
      { name: 'speed', label: 'Speed (px/s)', type: 'number', min: 1, max: 40, step: 1, value: 7 },
      { name: 'loop', label: 'Loop', type: 'checkbox', value: true }
    ],
    clock: [
      { name: 'style', label: 'Style', type: 'select', options: ['digital', 'analog'], value: 'digital' },
      { name: 'font', label: 'Font', type: 'select', options: availableFonts, value: availableFonts[0] },
      { name: 'format', label: 'Format', type: 'select', options: ['24h', '12h'], value: '24h' },
      { name: 'blink_colon', label: 'Blink Colon', type: 'checkbox', value: false }
    ],
    weather: [
      { name: 'latitude', label: 'Latitude', type: 'number', step: 0.01, value: 40.71 },
      { name: 'longitude', label: 'Longitude', type: 'number', step: 0.01, value: -74.01 },
      { name: 'unit', label: 'Unit', type: 'select', options: ['F', 'C'], value: 'F' },
      { name: 'show_degree', label: 'Degree Symbol', type: 'checkbox', value: true },
      { name: 'override_condition', label: 'Condition Override', type: 'select', options: ['', 'sunny', 'partly_cloudy', 'cloudy', 'rain', 'snow', 'thunderstorm', 'fog', 'sunrise', 'sunset'], value: '', optionLabels: ['— API —', 'Sunny', 'Partly Cloudy', 'Cloudy', 'Rain', 'Snow', 'Thunderstorm', 'Fog', 'Sunrise', 'Sunset'] },
      { name: 'sun_progress', label: 'Sun Progress', type: 'number', min: 0, max: 1, step: 0.05, value: 0.5 },
      { name: 'spawn_rate', label: 'Precip Rate (/s)', type: 'number', min: 0.1, max: 4, step: 0.1, value: 0.7 },
      { name: 'fall_speed', label: 'Fall Speed (px/s)', type: 'number', min: 0.5, max: 10, step: 0.1, value: 2.0 },
      { name: 'droplet_size', label: 'Droplet Size', type: 'number', min: 1, max: 3, step: 1, value: 2 },
      { name: 'strike_interval', label: 'Strike Interval (s)', type: 'number', min: 1, max: 1800, step: 1, value: 900 }
    ]
  };
  return params[animationName] || [];
}

function updateAnimationParams() {
  const selectedAnim = animSelect.value;
  const params = getAnimationParams(selectedAnim);

  paramsContainer.innerHTML = '';

  if (params.length === 0) {
    paramsContainer.innerHTML = '<p style="color: #666; font-style: italic;">No configurable parameters</p>';
    return;
  }

  params.forEach(param => {
    const row = document.createElement('div');
    row.style.marginBottom = '8px';

    const label = document.createElement('label');
    label.textContent = param.label + ':';
    label.style.display = 'inline-block';
    label.style.width = '120px';
    label.style.fontWeight = 'bold';

    let input;
    if (param.type === 'select') {
      input = document.createElement('select');
      param.options.forEach((opt, i) => {
        const option = document.createElement('option');
        option.value = opt;
        option.textContent = param.optionLabels ? param.optionLabels[i] : opt;
        if (opt === param.value) option.selected = true;
        input.appendChild(option);
      });
    } else if (param.type === 'checkbox') {
      input = document.createElement('input');
      input.type = 'checkbox';
      input.checked = param.value;
    } else if (param.type === 'text') {
      input = document.createElement('input');
      input.type = 'text';
      input.value = param.value;
      input.style.width = '160px';
    } else {
      input = document.createElement('input');
      input.type = param.type;
      input.value = param.value;
      if (param.min !== undefined) input.min = param.min;
      if (param.max !== undefined) input.max = param.max;
      if (param.step !== undefined) input.step = param.step;
      input.style.width = '80px';
    }

    input.id = `param-${param.name}`;
    input.addEventListener('change', updateAnimationConfig);

    row.appendChild(label);
    row.appendChild(input);
    paramsContainer.appendChild(row);
  });
}

async function updateAnimationConfig() {
  const selectedAnim = animSelect.value;
  if (!selectedAnim) return;

  const params = getAnimationParams(selectedAnim);
  const config = { name: selectedAnim };

  params.forEach(param => {
    const input = document.getElementById(`param-${param.name}`);
    if (input) {
      let value;
      if (param.type === 'checkbox') {
        value = input.checked;
      } else if (param.type === 'number') {
        value = parseFloat(input.value);
      } else {
        value = input.value;
      }
      config[param.name] = value;
    }
  });

  try {
    await postJSON(`/animations/configure`, config);
  } catch (error) {
    console.error('Failed to configure animation:', error);
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

  const paramDefs = getAnimationParams(sel);
  const params = {};
  paramDefs.forEach(param => {
    const input = document.getElementById(`param-${param.name}`);
    if (input) {
      if (param.type === 'checkbox') params[param.name] = input.checked;
      else if (param.type === 'number') params[param.name] = parseFloat(input.value);
      else params[param.name] = input.value;
    }
  });

  await postJSON(`/anim/${encodeURIComponent(sel)}`, params);

  // For weather, also configure the background fetch loop
  if (sel === 'weather') {
    await postJSON('/weather/config', {
      latitude: params.latitude,
      longitude: params.longitude,
      unit: params.unit,
    });
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
  try {
    const data = await fetchJSON('/fonts');
    if (data.fonts && data.fonts.length > 0) availableFonts = data.fonts;
  } catch (_) { /* keep default */ }
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
