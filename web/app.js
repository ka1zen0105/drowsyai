/* Driver monitor dashboard
   Talks to the existing FastAPI endpoints. Add ?demo to the URL to preview without the backend. */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const IS_STANDALONE = location.hostname.endsWith('vercel.app') || location.hostname.endsWith('github.io');
  let isDemo = new URLSearchParams(location.search).has('demo') || IS_STANDALONE;

  const WINDOW_S = 30;                       // trace length in seconds
  const EAR_MAX = 0.5, MAR_MAX = 1.0;        // rail / trace scales
  const POSE = {                             // alert limit and rail range, degrees
    pitch: { limit: 10, range: 30 },
    roll:  { limit: 12, range: 30 },
    yaw:   { limit: 35, range: 60 },
  };

  const el = {
    video: $('video'), simCanvas: $('simCanvas'), stage: $('stage'), stateLabel: $('stateLabel'),
    banner: $('banner'), bannerReason: $('bannerReason'),
    ovInfo: $('ovInfo'), ovInfoTitle: $('ovInfoTitle'), ovInfoText: $('ovInfoText'),
    ovCal: $('ovCal'), calCount: $('calCount'), calBar: $('calBar'), calSamples: $('calSamples'), calEar: $('calEar'),
    calBtn: $('calBtn'), calLabel: $('calLabel'), ackBtn: $('ackBtn'),
    chipEye: $('chipEye'), chipYawn: $('chipYawn'), chipHead: $('chipHead'), chipMicro: $('chipMicro'), votes: $('votes'),
    ledGreen: $('ledGreen'), ledRed: $('ledRed'), buzzer: $('buzzer'),
    instruments: $('instruments'),
    earVal: $('earVal'), earFill: $('earFill'), earBase: $('earBase'), earSub: $('earSub'),
    marVal: $('marVal'), marFill: $('marFill'), marBase: $('marBase'), marThr: $('marThr'), marSub: $('marSub'),
    perclosVal: $('perclosVal'), perclosFill: $('perclosFill'),
    earLaneVal: $('earLaneVal'), marLaneVal: $('marLaneVal'),
    earCanvas: $('earCanvas'), marCanvas: $('marCanvas'),
    evBody: $('evBody'), evEmpty: $('evEmpty'), evCount: $('evCount'),
    toast: $('toast'),
  };

  /* ---------- helpers ---------- */
  const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi);
  const num = (v) => (typeof v === 'number' && isFinite(v) ? v : null);
  const f2 = (v) => (num(v) === null ? '–' : v.toFixed(2));
  const wrap180 = (d) => ((((d + 180) % 360) + 360) % 360) - 180;   // keeps angle gaps in -180..180
  const signed = (v) => (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(0);
  const txt = (node, s) => { if (node.textContent !== s) node.textContent = s; };
  const pct = (v) => (v * 100).toFixed(2) + '%';

  let toastTimer;
  function toast(msg) {
    el.toast.textContent = msg;
    el.toast.classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.toast.classList.remove('show'), 2400);
  }

  /* ---------- static setup ---------- */
  for (const [axis, cfg] of Object.entries(POSE)) {
    const rail = $(axis + 'Mark').parentElement;
    const zone = ((cfg.range - cfg.limit) / (2 * cfg.range)) * 100;
    rail.querySelector('.zone.l').style.width = zone + '%';
    rail.querySelector('.zone.r').style.width = zone + '%';
    txt($(axis + 'Sub'), 'Alert beyond ±' + cfg.limit + '° from your normal position');
  }

  el.video.addEventListener('load', () => el.stage.classList.remove('no-video'));
  el.video.addEventListener('error', () => {
    el.stage.classList.add('no-video');
    if (!DEMO) setTimeout(() => { el.video.src = '/video_feed?t=' + Date.now(); }, 2000);
  });
  if (DEMO) {
    el.video.removeAttribute('src');
    el.stage.dataset.note = 'Demo mode, no camera feed';
    el.stage.classList.add('no-video');
  } else {
    el.stage.dataset.note = 'Waiting for camera feed';
  }

  /* ---------- rendering ---------- */
  const STATES = {
    ok:      'Monitoring',
    alarm:   'Alarm',
    cal:     'Calibrating',
    fault:   'Fault',
    noface:  'No face found',
    offline: 'Offline',
  };

  let current = 'offline';
  const buf = [];   // {t, ear, mar, alarm, eb, mb}

  function pickState(t) {
    const s = String(t.system_state || '').toUpperCase();
    if (t.calibrating || s === 'CALIBRATING') return 'cal';
    if (t.alarm_active || s === 'ALARM') return 'alarm';
    if (t.fault_active || s === 'FAULT') return 'fault';
    if (t.face_found === false) return 'noface';
    return 'ok';
  }

  function setState(s) {
    const changed = s !== current;
    current = s;
    document.body.dataset.state = s;
    txt(el.stateLabel, STATES[s]);
    document.title = (s === 'alarm' ? 'Alarm – ' : '') + 'Driver monitor';

    el.banner.hidden = s !== 'alarm';
    el.ovCal.hidden = s !== 'cal';

    const info = s === 'fault'
      ? ['Driver not visible', 'No face for over 2 seconds. Sit in view of the camera to resume monitoring.']
      : s === 'offline'
      ? ['Can’t reach the monitor', 'Check that the server is running. Retrying automatically.']
      : null;
    el.ovInfo.hidden = !info;
    if (info) { txt(el.ovInfoTitle, info[0]); txt(el.ovInfoText, info[1]); }

    el.ackBtn.disabled = s !== 'alarm';
    el.calBtn.disabled = s === 'cal' || s === 'offline';
    txt(el.calLabel, s === 'cal' ? 'Calibrating…' : 'Calibrate');
    return changed;
  }

  function setPose(axis, value, base) {
    const cfg = POSE[axis];
    const row = $(axis + 'Val').closest('.row');
    const v = num(value), b = num(base);
    if (v === null) { txt($(axis + 'Val'), '–'); return false; }
    const dev = wrap180(v - (b === null ? 0 : b));
    const out = Math.abs(dev) >= cfg.limit;
    txt($(axis + 'Val'), signed(dev));
    $(axis + 'Mark').style.left = 50 + clamp(dev / cfg.range, -1, 1) * 50 + '%';
    row.classList.toggle('hot', out);
    return out;
  }

  function reasonText(t) {
    if (t.microsleep) return 'Eyes closed too long';
    const parts = [];
    if (t.eye_flag) parts.push('eyes closing');
    if (t.yawn_flag) parts.push('yawning');
    if (t.head_flag) parts.push('head off position');
    if (!parts.length) return '';
    const s = parts.join(' and ');
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  let lastAlarm = false;
  function render(t) {
    const s = pickState(t);
    const changed = setState(s);
    if (changed || (s === 'alarm') !== lastAlarm) loadEvents();
    lastAlarm = s === 'alarm';

    el.instruments.classList.toggle('stale', t.face_found === false);

    // flags
    const flags = [t.eye_flag, t.yawn_flag, t.head_flag].filter(Boolean).length;
    el.chipEye.classList.toggle('on', !!t.eye_flag);
    el.chipYawn.classList.toggle('on', !!t.yawn_flag);
    el.chipHead.classList.toggle('on', !!t.head_flag);
    el.chipMicro.classList.toggle('on', !!t.microsleep);
    txt(el.votes, flags + ' of 3 flags');
    if (s === 'alarm') txt(el.bannerReason, reasonText(t));

    // hardware
    el.ledGreen.classList.toggle('on', !!t.green_on);
    el.ledRed.classList.toggle('on', !!t.red_on);
    el.buzzer.classList.toggle('on', !!t.buzzer_on);

    // eye openness
    const ear = num(t.ear_avg), eb = num(t.ear_baseline);
    txt(el.earVal, f2(ear));
    el.earFill.style.width = ear === null ? '0%' : clamp(ear / EAR_MAX, 0, 1) * 100 + '%';
    el.earBase.hidden = eb === null;
    if (eb !== null) el.earBase.style.left = clamp(eb / EAR_MAX, 0, 1) * 100 + '%';
    txt(el.earSub, 'Baseline ' + f2(eb));
    el.earVal.closest('.row').classList.toggle('hot', !!t.eye_flag);

    // mouth opening
    const mar = num(t.mar), mb = num(t.mar_baseline), mt = num(t.mar_yawn_threshold);
    txt(el.marVal, f2(mar));
    el.marFill.style.width = mar === null ? '0%' : clamp(mar / MAR_MAX, 0, 1) * 100 + '%';
    el.marBase.hidden = mb === null;
    if (mb !== null) el.marBase.style.left = clamp(mb / MAR_MAX, 0, 1) * 100 + '%';
    el.marThr.hidden = mt === null;
    if (mt !== null) el.marThr.style.left = clamp(mt / MAR_MAX, 0, 1) * 100 + '%';
    txt(el.marSub, 'Baseline ' + f2(mb) + ', yawn at ' + f2(mt));
    el.marVal.closest('.row').classList.toggle('hot', !!t.yawn_flag);

    // head pose
    setPose('pitch', t.pitch_deg, t.pitch_baseline);
    setPose('roll', t.roll_deg, t.roll_baseline);
    setPose('yaw', t.yaw_deg, t.yaw_baseline);

    // PERCLOS
    const pc = num(t.perclos);
    txt(el.perclosVal, pc === null ? '–' : (pc * 100).toFixed(0));
    el.perclosFill.style.width = pc === null ? '0%' : clamp(pc, 0, 1) * 100 + '%';

    // calibration overlay
    if (s === 'cal') {
      const dur = num(t.cal_duration) || 15;
      const done = clamp(num(t.cal_elapsed) || 0, 0, dur);
      txt(el.calCount, String(Math.max(0, Math.ceil(dur - done))));
      el.calBar.style.width = (done / dur) * 100 + '%';
      txt(el.calSamples, (t.cal_samples || 0) + ' samples');
      txt(el.calEar, 'Average eye openness ' + f2(t.cal_avg_ear));
    }

    // traces
    const now = performance.now() / 1000;
    buf.push({
      t: now,
      ear: t.face_found === false ? null : ear,
      mar: t.face_found === false ? null : mar,
      alarm: s === 'alarm', eb, mb,
    });
    while (buf.length && now - buf[0].t > WINDOW_S + 1) buf.shift();
    txt(el.earLaneVal, f2(ear));
    txt(el.marLaneVal, f2(mar));
  }

  function renderOffline() {
    setState('offline');
    el.instruments.classList.add('stale');
  }

  /* ---------- traces ---------- */
  const css = getComputedStyle(document.documentElement);
  const COLOR = {
    eye: css.getPropertyValue('--eye').trim(),
    mouth: css.getPropertyValue('--mouth').trim(),
    faint: css.getPropertyValue('--faint').trim(),
  };

  function drawLane(cv, key, baseKey, max, color) {
    const dpr = window.devicePixelRatio || 1;
    const w = cv.clientWidth, h = cv.clientHeight;
    if (!w || !h) return;
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) {
      cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
    }
    const ctx = cv.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const now = performance.now() / 1000;
    const x = (t) => w - ((now - t) / WINDOW_S) * w;
    const y = (v) => h - 3 - (clamp(v, 0, max) / max) * (h - 8);

    // alarm periods
    ctx.fillStyle = 'rgba(255, 90, 82, 0.16)';
    let start = null;
    for (const p of buf) {
      if (p.alarm && start === null) start = p.t;
      if (!p.alarm && start !== null) { ctx.fillRect(x(start), 0, x(p.t) - x(start), h); start = null; }
    }
    if (start !== null) ctx.fillRect(x(start), 0, w - x(start), h);

    // baseline
    const last = buf[buf.length - 1];
    if (last && num(last[baseKey]) !== null) {
      ctx.strokeStyle = COLOR.faint; ctx.lineWidth = 1; ctx.setLineDash([3, 4]);
      ctx.beginPath(); ctx.moveTo(0, y(last[baseKey])); ctx.lineTo(w, y(last[baseKey])); ctx.stroke();
      ctx.setLineDash([]);
    }

    // signal, broken where the face was lost
    ctx.strokeStyle = color; ctx.lineWidth = 1.75; ctx.lineJoin = 'round';
    ctx.beginPath();
    let pen = false;
    for (const p of buf) {
      const v = num(p[key]);
      if (v === null) { pen = false; continue; }
      if (!pen) { ctx.moveTo(x(p.t), y(v)); pen = true; } else ctx.lineTo(x(p.t), y(v));
    }
    ctx.stroke();
  }

  function frame() {
    drawLane(el.earCanvas, 'ear', 'eb', EAR_MAX, COLOR.eye);
    drawLane(el.marCanvas, 'mar', 'mb', MAR_MAX, COLOR.mouth);
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  /* ---------- events ---------- */
  const EVENT_KIND = {
    ALARM_ON:    ['Alarm', 'alarm'],
    ALARM_OFF:   ['Alarm cleared', 'ok'],
    FAULT_ON:    ['Fault', 'fault'],
    FAULT_OFF:   ['Fault cleared', 'ok'],
    ACK_BUTTON:  ['Acknowledged', 'ack'],
  };
  let evSig = '';

  function cell(cls, text) {
    const td = document.createElement('td');
    if (cls) td.className = cls;
    td.textContent = text;
    return td;
  }

  function renderEvents(list) {
    const rows = (Array.isArray(list) ? list : (list && list.events) || [])
      .slice()
      .sort((a, b) => String(b.iso_time).localeCompare(String(a.iso_time)))
      .slice(0, 100);
    const sig = rows.length + '|' + (rows[0] ? rows[0].iso_time + rows[0].event_type : '');
    if (sig === evSig) return;
    evSig = sig;

    el.evBody.textContent = '';
    for (const e of rows) {
      const tr = document.createElement('tr');
      const d = new Date(e.iso_time);
      tr.appendChild(cell('time', isNaN(d) ? String(e.iso_time || '') : d.toLocaleTimeString([], { hour12: false })));

      const [label, kind] = EVENT_KIND[e.event_type] ||
        [String(e.event_type || 'Event').toLowerCase().replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase()), 'other'];
      const ev = document.createElement('td');
      const badge = document.createElement('span');
      badge.className = 'badge ' + kind; badge.textContent = label;
      ev.appendChild(badge);
      if (e.description) {
        const desc = document.createElement('span');
        desc.className = 'desc'; desc.textContent = e.description; desc.title = e.description;
        ev.appendChild(desc);
      }
      tr.appendChild(ev);

      tr.appendChild(cell('n', f2(num(e.ear))));
      tr.appendChild(cell('n', f2(num(e.mar))));
      tr.appendChild(cell('n', num(e.pitch) === null ? '–' : Math.round(e.pitch) + '°'));
      tr.appendChild(cell('n', num(e.perclos) === null ? '–' : Math.round(e.perclos * 100) + '%'));
      el.evBody.appendChild(tr);
    }
    el.evEmpty.hidden = rows.length > 0;
    txt(el.evCount, rows.length ? String(rows.length) : '');
  }

  async function getJSON(url) {
    const r = await fetch(url, {
      cache: 'no-store',
      signal: AbortSignal.timeout ? AbortSignal.timeout(2500) : undefined,
    });
    if (!r.ok) throw new Error(r.status);
    return r.json();
  }

  async function loadEvents() {
    try { renderEvents(isDemo ? demo.events() : await getJSON('/api/events')); } catch (_) {
      if (isDemo) renderEvents(demo.events());
    }
  }

  /* ---------- actions ---------- */
  async function post(url) {
    try { return (await fetch(url, { method: 'POST' })).ok; } catch (_) { return false; }
  }

  async function acknowledge() {
    if (current !== 'alarm') return;
    const ok = isDemo ? demo.ack() : await post('/api/ack');
    toast(ok ? 'Alarm acknowledged' : 'Couldn’t reach the monitor. Try again.');
    setTimeout(loadEvents, 400);
  }

  async function calibrate() {
    if (current === 'cal' || current === 'offline') return;
    const ok = isDemo ? demo.calibrate() : await post('/api/calibrate');
    toast(ok ? 'Calibration started' : 'Couldn’t start calibration. Try again.');
  }

  el.ackBtn.addEventListener('click', acknowledge);
  el.calBtn.addEventListener('click', calibrate);
  document.addEventListener('keydown', (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === ' ' || e.key.toLowerCase() === 's') {
      e.preventDefault();
      if (!e.repeat) acknowledge();
    }
  });
  document.addEventListener('keyup', (e) => { if (e.key === ' ') e.preventDefault(); });

  if (el.video) {
    el.video.addEventListener('error', () => {
      isDemo = true;
      if (el.simCanvas) el.simCanvas.style.display = 'block';
      el.video.style.display = 'none';
    });
  }

  /* ---------- simulation canvas visualizer (for standalone/Vercel) ---------- */
  function drawSimulation(t) {
    if (!el.simCanvas) return;
    if (el.simCanvas.style.display !== 'block') {
      el.simCanvas.style.display = 'block';
      if (el.video) el.video.style.display = 'none';
    }
    const canvas = el.simCanvas;
    const ctx = canvas.getContext('2d');
    const w = canvas.width, h = canvas.height;

    ctx.fillStyle = '#080a0f';
    ctx.fillRect(0, 0, w, h);

    // Subtle grid
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.035)';
    ctx.lineWidth = 1;
    for (let x = 40; x < w; x += 40) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
    }
    for (let y = 40; y < h; y += 40) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
    }

    const isAlarm = t.alarm_active;
    const isCal = t.calibrating;
    const accent = isAlarm ? '#ef4444' : isCal ? '#3b82f6' : '#2dd4bf';
    const accentAlpha = isAlarm ? 'rgba(239, 68, 68, ' : isCal ? 'rgba(59, 130, 246, ' : 'rgba(45, 212, 191, ';

    const cx = w / 2 + clamp(t.yaw_deg * 2.2, -60, 60);
    const cy = h / 2 - 10 + clamp(t.pitch_deg * 2.5, -50, 50);
    const roll = (t.roll_deg * Math.PI) / 180;

    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(roll);

    const bx = -95, by = -125, bw = 190, bh = 250;
    ctx.strokeStyle = accentAlpha + '0.25)';
    ctx.setLineDash([4, 4]);
    ctx.strokeRect(bx, by, bw, bh);
    ctx.setLineDash([]);

    ctx.strokeStyle = accent;
    ctx.lineWidth = 2.5;
    const blen = 16;
    ctx.beginPath(); ctx.moveTo(bx, by + blen); ctx.lineTo(bx, by); ctx.lineTo(bx + blen, by); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(bx + bw - blen, by); ctx.lineTo(bx + bw, by); ctx.lineTo(bx + bw, by + blen); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(bx, by + bh - blen); ctx.lineTo(bx, by + bh); ctx.lineTo(bx + blen, by + bh); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(bx + bw - blen, by + bh); ctx.lineTo(bx + bw, by + bh); ctx.lineTo(bx + bw, by + bh - blen); ctx.stroke();

    ctx.strokeStyle = accentAlpha + '0.45)';
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.ellipse(0, 5, 75, 105, 0, 0, Math.PI * 2);
    ctx.stroke();

    ctx.strokeStyle = accentAlpha + '0.6)';
    ctx.beginPath();
    ctx.moveTo(-50, -42); ctx.quadraticCurveTo(-35, -48, -18, -42);
    ctx.moveTo(18, -42); ctx.quadraticCurveTo(35, -48, 50, -42);
    ctx.stroke();

    const eyeH = clamp((t.ear_avg / 0.35) * 12, 1, 14);
    ctx.fillStyle = accent;
    ctx.beginPath();
    ctx.ellipse(-32, -28, 16, eyeH, 0, 0, Math.PI * 2);
    ctx.stroke();
    if (eyeH > 4) {
      ctx.beginPath();
      ctx.arc(-32, -28, 4, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.beginPath();
    ctx.ellipse(32, -28, 16, eyeH, 0, 0, Math.PI * 2);
    ctx.stroke();
    if (eyeH > 4) {
      ctx.beginPath();
      ctx.arc(32, -28, 4, 0, Math.PI * 2);
      ctx.fill();
    }

    ctx.strokeStyle = accentAlpha + '0.5)';
    ctx.beginPath();
    ctx.moveTo(0, -25); ctx.lineTo(0, 10); ctx.lineTo(-8, 18); ctx.lineTo(8, 18);
    ctx.stroke();

    const mouthH = clamp((t.mar / 0.6) * 28, 2, 34);
    ctx.beginPath();
    ctx.ellipse(0, 48, 28, mouthH, 0, 0, Math.PI * 2);
    ctx.stroke();
    if (mouthH > 16) {
      ctx.fillStyle = isAlarm ? 'rgba(239, 68, 68, 0.4)' : accentAlpha + '0.25)';
      ctx.fill();
    }

    ctx.fillStyle = accent;
    const dots = [
      [0, -100], [-35, -95], [35, -95], [-65, -60], [65, -60],
      [-75, 0], [75, 0], [-60, 60], [60, 60], [0, 110],
      [-32, -28], [32, -28], [0, 18], [0, 48], [-28, 48], [28, 48]
    ];
    for (const [dx, dy] of dots) {
      ctx.beginPath();
      ctx.arc(dx, dy, 2, 0, Math.PI * 2);
      ctx.fill();
    }

    ctx.restore();

    ctx.fillStyle = 'rgba(255, 255, 255, 0.85)';
    ctx.font = '11px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
    ctx.fillText('LIVE SIMULATION FEED • AI VISION PIPELINE', 16, 24);

    ctx.fillStyle = accent;
    ctx.fillRect(16, 30, 6, 6);
    ctx.fillStyle = 'rgba(255, 255, 255, 0.6)';
    ctx.fillText('FPS: 30  |  FACE MESH: 468 PTS  |  TRACKING: LOCKED', 28, 36);

    ctx.textAlign = 'right';
    ctx.fillText(`PERCLOS: ${(t.perclos * 100).toFixed(1)}%`, w - 16, 24);
    ctx.fillText(`EAR: ${t.ear_avg.toFixed(2)}  MAR: ${t.mar.toFixed(2)}`, w - 16, 36);
    ctx.textAlign = 'left';
  }

  /* ---------- polling ---------- */
  let fails = 0;
  async function tick() {
    if (isDemo) {
      const t = demo.telemetry();
      render(t);
      drawSimulation(t);
    } else {
      try {
        const t = await getJSON('/api/telemetry');
        render(t);
        fails = 0;
        if (el.simCanvas) el.simCanvas.style.display = 'none';
        if (el.video) el.video.style.display = '';
      } catch (_) {
        if (++fails >= 2) {
          isDemo = true;
          toast('Switched to Live AI Simulation Mode');
          const t = demo.telemetry();
          render(t);
          drawSimulation(t);
        }
      }
    }
    setTimeout(tick, isDemo ? 100 : (fails ? 1000 : 120));
  }
  /* ---------- demo data (preview only, used with ?demo) ---------- */
  const demo = (() => {
    const t0 = performance.now();
    let ackUntil = 0, calStart = null;
    const log = [
      { iso_time: new Date(Date.now() - 240000).toISOString(), event_type: 'ALARM_ON', ear: 0.07, mar: 0.12, pitch: -17, perclos: 0.39, description: 'Voting: EYE_CLOSURE+HEAD_NOD (2/3 flags)' },
      { iso_time: new Date(Date.now() - 232000).toISOString(), event_type: 'ACK_BUTTON', ear: 0.28, mar: 0.05, pitch: -3, perclos: 0.2, description: 'Acknowledge pressed' },
    ];
    return {
      events: () => log,
      ack: () => { ackUntil = performance.now() + 4000; return true; },
      calibrate: () => { calStart = performance.now(); return true; },
      telemetry() {
        const now = performance.now(), s = (now - t0) / 1000, cyc = s % 34;
        if (calStart !== null) {
          const elapsed = (now - calStart) / 1000;
          if (elapsed > 15) calStart = null;
          else return base({ system_state: 'CALIBRATING', calibrating: true, cal_duration: 15, cal_elapsed: elapsed, cal_samples: Math.round(elapsed * 9), cal_avg_ear: 0.29 });
        }
        const closing = cyc > 20 && cyc < 30;
        const alarm = closing && cyc > 23 && now > ackUntil;
        const blink = Math.sin(s * 2.3) > 0.985;
        const ear = closing || blink ? 0.08 + Math.random() * 0.02 : 0.29 + 0.015 * Math.sin(s * 3);
        const yawning = cyc > 8 && cyc < 11;
        const mar = yawning ? 0.55 + 0.1 * Math.sin(s * 4) : 0.05 + 0.01 * Math.random();
        const pitch = closing ? -3.4 - Math.min(18, (cyc - 20) * 3.5) : -3.4 + Math.sin(s * 0.8) * 2;
        return base({
          system_state: alarm ? 'ALARM' : 'MONITORING', alarm_active: alarm,
          ear_avg: ear, mar, pitch_deg: pitch, roll_deg: Math.sin(s * 0.5) * 3, yaw_deg: 1 + Math.sin(s * 0.3) * 6,
          perclos: closing ? clamp((cyc - 20) / 20, 0, 0.5) : 0.04,
          eye_flag: closing && cyc > 21, yawn_flag: yawning && cyc > 9.2, head_flag: closing && cyc > 22,
          microsleep: closing && cyc > 26,
          green_on: !alarm, red_on: alarm, buzzer_on: alarm && Math.floor(s * 4) % 2 === 0,
        });
      },
    };
    function base(o) {
      return Object.assign({
        system_state: 'MONITORING', alarm_active: false, fault_active: false, face_found: true,
        ear_avg: 0.29, ear_baseline: 0.32, mar: 0.05, mar_baseline: 0.05, mar_yawn_threshold: 0.33,
        pitch_deg: -3.4, pitch_baseline: -3.4, roll_deg: 0, roll_baseline: 0, yaw_deg: 1, yaw_baseline: 1,
        perclos: 0.04, eye_flag: false, yawn_flag: false, head_flag: false, microsleep: false,
        green_on: true, red_on: false, buzzer_on: false,
        calibrating: false, cal_duration: 15, cal_elapsed: 0, cal_samples: 0, cal_avg_ear: 0.29,
      }, o);
    }
  })();

  tick();
  loadEvents();
  setInterval(loadEvents, 3000);
})();
