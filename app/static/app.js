// Pulse Guard AI dashboard logic
let trendChart;

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

async function loadServices() {
  const services = await api('/api/services');
  const sel = document.getElementById('serviceSelect');
  const current = sel.value;
  sel.innerHTML = '';
  if (!services.length) {
    const opt = document.createElement('option');
    opt.textContent = '(no data — load demo)';
    opt.value = '';
    sel.appendChild(opt);
    return;
  }
  services.forEach(s => {
    const opt = document.createElement('option');
    opt.value = s.service;
    opt.textContent = `${s.service} (${s.errors} err / ${s.total})`;
    sel.appendChild(opt);
  });
  if (current) sel.value = current;
}

function healthClass(score) {
  if (score >= 95) return 'health-good';
  if (score >= 80) return 'health-mid';
  return 'health-bad';
}

async function loadTrend() {
  const service = document.getElementById('serviceSelect').value;
  if (!service) return;
  const minutes = document.getElementById('windowSelect').value;
  const data = await api(`/api/trends?service=${encodeURIComponent(service)}&minutes=${minutes}`);

  const labels = data.points.map(p => new Date(p.bucket).toLocaleTimeString());
  const totals = data.points.map(p => p.total);
  const errors = data.points.map(p => p.errors);

  const kpiHealth = document.getElementById('kpiHealth');
  kpiHealth.textContent = data.health_score.toFixed(1);
  kpiHealth.className = 'kpi ' + healthClass(data.health_score);
  document.getElementById('kpiTotal').textContent = totals.reduce((a, b) => a + b, 0);
  document.getElementById('kpiErrors').textContent = errors.reduce((a, b) => a + b, 0);

  const ctx = document.getElementById('trendChart');
  if (trendChart) trendChart.destroy();
  trendChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        { label: 'Total', data: totals, borderColor: '#58a6ff', backgroundColor: 'rgba(88,166,255,.1)', fill: true, tension: .3 },
        { label: 'Errors', data: errors, borderColor: '#f85149', backgroundColor: 'rgba(248,81,73,.1)', fill: true, tension: .3 }
      ]
    },
    options: {
      responsive: true,
      plugins: { legend: { labels: { color: '#c9d1d9' } } },
      scales: { x: { ticks: { color: '#8b949e' }, grid: { color: '#21262d' } }, y: { ticks: { color: '#8b949e' }, grid: { color: '#21262d' }, beginAtZero: true } }
    }
  });
}

async function loadAnomalies() {
  const anomalies = await api('/api/anomalies?limit=50');
  document.getElementById('kpiAnomalies').textContent = anomalies.length;
  const body = document.getElementById('anomalyBody');
  if (!anomalies.length) { body.innerHTML = '<tr><td colspan="7" class="empty">No anomalies yet.</td></tr>'; return; }
  body.innerHTML = anomalies.map(a => `
    <tr>
      <td>${a.service}</td>
      <td>${new Date(a.bucket_start).toLocaleString()}</td>
      <td>${a.error_count}</td>
      <td>${a.baseline.toFixed(1)}</td>
      <td>${a.zscore.toFixed(2)}</td>
      <td><span class="badge ${a.severity}">${a.severity}</span></td>
      <td>${a.alert_sent ? '✅' : '—'}</td>
    </tr>`).join('');
}

async function loadAlerts() {
  const alerts = await api('/api/alerts?limit=50');
  const body = document.getElementById('alertBody');
  if (!alerts.length) { body.innerHTML = '<tr><td colspan="4" class="empty">No alerts fired.</td></tr>'; return; }
  body.innerHTML = alerts.map(a => `
    <tr>
      <td>${a.service}</td>
      <td>${a.target}</td>
      <td>${a.status}</td>
      <td>${new Date(a.created_at).toLocaleString()}</td>
    </tr>`).join('');
}

async function loadScheduler() {
  const st = await api('/api/scheduler/status');
  const badge = document.getElementById('schedBadge');
  badge.textContent = st.running ? 'running' : 'stopped';
  badge.className = 'badge ' + (st.running ? 'info' : 'warning');
  const last = st.last_result || {};
  document.getElementById('schedInfo').textContent =
    `${st.directory}/${st.glob} · every ${st.interval_seconds}s · files=${st.tracked_files.length} · last ingested=${last.ingested || 0}`;
}

async function schedAction(path) {
  await api(path, { method: 'POST' });
  await loadScheduler();
  await refreshAll();
}

async function refreshAll() {
  try {
    await loadServices();
    await Promise.all([loadTrend(), loadAnomalies(), loadAlerts(), loadScheduler()]);
    document.getElementById('statusDot').style.background = '#3fb950';
  } catch (e) {
    document.getElementById('statusDot').style.background = '#f85149';
    console.error(e);
  }
}

async function loadDemo() {
  const btn = document.getElementById('demoBtn');
  btn.disabled = true; btn.textContent = 'Loading…';
  try {
    const demo = generateDemoLogs();
    await api('/api/ingest/raw', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: demo })
    });
    await refreshAll();
  } finally {
    btn.disabled = false; btn.textContent = 'Load Demo Data';
  }
}

// Generate synthetic logs with a deliberate error spike for demoing detection.
function generateDemoLogs() {
  const services = ['payment-svc', 'auth-svc'];
  const now = Date.now();
  const lines = [];
  for (let m = 20; m >= 0; m--) {
    const base = new Date(now - m * 60000);
    services.forEach(svc => {
      const normal = 8 + Math.floor(Math.random() * 4);
      // inject a spike into payment-svc around 5 minutes ago
      const spike = (svc === 'payment-svc' && m >= 4 && m <= 6) ? 25 : 0;
      for (let i = 0; i < normal; i++) {
        const ts = new Date(base.getTime() + i * 1000).toISOString().replace(/\.\d+Z$/, 'Z');
        lines.push(`${ts} INFO [${svc}] request handled ok`);
      }
      const errCount = (Math.random() < 0.3 ? 1 : 0) + spike;
      for (let i = 0; i < errCount; i++) {
        const ts = new Date(base.getTime() + i * 800).toISOString().replace(/\.\d+Z$/, 'Z');
        lines.push(`${ts} ERROR [${svc}] downstream timeout / 500`);
      }
    });
  }
  return lines.join('\n');
}

async function loadEnterprise() {
  const btn = document.getElementById('enterpriseBtn');
  btn.disabled = true; btn.textContent = 'Seeding…';
  try {
    await api('/api/demo/enterprise', { method: 'POST' });
    await refreshAll();
  } finally {
    btn.disabled = false; btn.textContent = 'Load Enterprise Data';
  }
}

document.getElementById('refreshBtn').addEventListener('click', refreshAll);
document.getElementById('demoBtn').addEventListener('click', loadDemo);
document.getElementById('enterpriseBtn').addEventListener('click', loadEnterprise);
document.getElementById('schedStartBtn').addEventListener('click', () => schedAction('/api/scheduler/start'));
document.getElementById('schedStopBtn').addEventListener('click', () => schedAction('/api/scheduler/stop'));
document.getElementById('schedPollBtn').addEventListener('click', () => schedAction('/api/scheduler/poll'));
document.getElementById('serviceSelect').addEventListener('change', () => { loadTrend(); });
document.getElementById('windowSelect').addEventListener('change', () => { loadTrend(); });

refreshAll();
setInterval(refreshAll, 15000); // live auto-refresh

