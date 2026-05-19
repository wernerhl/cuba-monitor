// Cuba Concordance Monitor — dashboard SPA
// Reads ../data/dashboard.json and renders four Chart.js panels.

const COLORS = {
  bg: '#1a1a2e',
  panel: '#16213e',
  text: '#e0e0e0',
  dim: '#93a1c0',
  grid: '#243056',
  concordance: '#00b4d8',
  no2: '#4895ef',
  dnb: '#f72585',
  ndvi: '#2ec4b6',
  ports: '#9b5de5',
  fx: '#ff6b6b',
  event: '#ffd166',
};

// Chart.js global defaults for dark theme
Chart.defaults.color = COLORS.text;
Chart.defaults.font.family = '-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif';
Chart.defaults.borderColor = COLORS.grid;
Chart.defaults.scale.grid.color = COLORS.grid;

async function load() {
  try {
    const resp = await fetch('../data/dashboard.json', { cache: 'no-store' });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    render(data);
  } catch (err) {
    document.getElementById('last-updated').textContent =
      `Could not load dashboard.json — ${err.message}`;
    throw err;
  }
}

function fmtDate(iso) {
  return new Date(iso + 'T00:00:00Z').toLocaleString('en', {
    timeZone: 'UTC', year: 'numeric', month: 'short',
  });
}

function eventLines(events, axis = 'x') {
  // Return Chart.js dataset overlays for event markers.
  return events.map(ev => ({
    type: 'line',
    label: ev.label,
    data: [],
    borderColor: COLORS.event,
    borderWidth: 1.5,
    borderDash: [4, 3],
    pointRadius: 0,
    showLine: false,
    yAxisID: 'y',
  }));
}

function renderHeader(data) {
  document.getElementById('last-updated').textContent =
    `Last updated · ${fmtDate(data.last_updated.substring(0, 10))}`;
  document.getElementById('eigenvalue-ratio').textContent =
    `PC1 share ${data.diagnostics.pc1_share}% · λ₁/λ₂ = ${data.diagnostics.eigenvalue_ratio}`;
}

function renderIndex(data) {
  const labels = data.monthly.map(r => r.date);
  const concordance = data.monthly.map(r => r.concordance_100);
  // Build event annotation lines as vertical bars via a plugin-free trick:
  // a separate dataset per event with two points spanning [min, max].
  const yMin = Math.min(...concordance.filter(v => v !== null)) - 5;
  const yMax = Math.max(...concordance.filter(v => v !== null)) + 5;
  const eventDatasets = data.events.map(ev => {
    const idx = labels.findIndex(d => d.startsWith(ev.date));
    if (idx < 0) return null;
    const arr = new Array(labels.length).fill(null);
    arr[idx] = yMax;
    return {
      label: ev.label,
      data: arr,
      backgroundColor: COLORS.event,
      borderColor: COLORS.event,
      borderWidth: 0,
      pointRadius: 6,
      pointStyle: 'triangle',
      showLine: false,
      tooltip: { callbacks: { title: () => ev.label } },
    };
  }).filter(Boolean);

  new Chart(document.getElementById('chart-index'), {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'Concordance index (2019 = 100)',
          data: concordance,
          borderColor: COLORS.concordance,
          backgroundColor: COLORS.concordance + '22',
          borderWidth: 2.5,
          pointRadius: 1.5,
          tension: 0.2,
          fill: true,
        },
        ...eventDatasets,
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title: items => fmtDate(items[0].label),
          },
        },
      },
      scales: {
        x: { type: 'time', time: { unit: 'year' }, grid: { display: false } },
        y: { suggestedMin: yMin, suggestedMax: yMax, title: { display: true, text: 'Index (2019=100)' } },
      },
    },
  });
}

function renderStreams(data) {
  const labels = data.monthly.map(r => r.date);
  const series = [
    { key: 'no2_100',   label: 'NO₂',       color: COLORS.no2 },
    { key: 'dnb_100',   label: 'DNB',       color: COLORS.dnb },
    { key: 'ndvi_100',  label: 'NDVI',      color: COLORS.ndvi },
    { key: 'ports_100', label: 'Ports',     color: COLORS.ports },
  ];
  new Chart(document.getElementById('chart-streams'), {
    type: 'line',
    data: {
      labels,
      datasets: series.map(s => ({
        label: s.label,
        data: data.monthly.map(r => r[s.key]),
        borderColor: s.color,
        backgroundColor: s.color + '22',
        borderWidth: 1.8,
        pointRadius: 0,
        tension: 0.25,
      })),
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { labels: { boxWidth: 10, boxHeight: 10 } },
      },
      scales: {
        x: { type: 'time', time: { unit: 'year' }, grid: { display: false } },
        y: { title: { display: true, text: 'Index (2019=100)' } },
      },
    },
  });
}

function renderFx(data) {
  const labels = data.monthly.map(r => r.date);
  new Chart(document.getElementById('chart-fx'), {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'CUP / USD informal',
          data: data.monthly.map(r => r.fx),
          borderColor: COLORS.fx,
          backgroundColor: COLORS.fx + '22',
          borderWidth: 2,
          pointRadius: 0,
          yAxisID: 'y',
          tension: 0.2,
        },
        {
          label: 'Import MT (PortWatch)',
          data: data.monthly.map(r => r.import_mt),
          borderColor: COLORS.ports,
          backgroundColor: COLORS.ports + '22',
          borderWidth: 1.5,
          pointRadius: 0,
          yAxisID: 'y2',
          tension: 0.2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: { legend: { labels: { boxWidth: 10, boxHeight: 10 } } },
      scales: {
        x: { type: 'time', time: { unit: 'year' }, grid: { display: false } },
        y:  { position: 'left',  title: { display: true, text: 'CUP / USD' } },
        y2: { position: 'right', title: { display: true, text: 'Import (MT)' }, grid: { display: false } },
      },
    },
  });
}

function renderSubnat(data) {
  const rows = data.subnational_dnb_latest;
  new Chart(document.getElementById('chart-subnat'), {
    type: 'bar',
    data: {
      labels: rows.map(r => r.province_name),
      datasets: [
        {
          label: 'DNB mean radiance',
          data: rows.map(r => r.dnb_mean),
          backgroundColor: COLORS.dnb + 'cc',
          borderColor: COLORS.dnb,
          borderWidth: 1,
        },
      ],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            afterBody: items => {
              const r = rows[items[0].dataIndex];
              return r.dnb_yoy_pct !== null ? `YoY change: ${r.dnb_yoy_pct.toFixed(1)}%` : '';
            },
          },
        },
      },
      scales: {
        x: { title: { display: true, text: 'nW/cm²/sr' } },
      },
    },
  });
}

function renderDiagnostics(data) {
  const tbody = document.getElementById('loadings-body');
  for (const [k, v] of Object.entries(data.diagnostics.loadings)) {
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${k}</td><td>${v.toFixed(3)}</td>`;
    tbody.appendChild(tr);
  }
  document.getElementById('diag-meta').textContent =
    `Fit on ${data.diagnostics.n_months_pca_fit} complete months · ` +
    `PC1 explains ${data.diagnostics.pc1_share}% of variance · ` +
    `PC2 explains ${data.diagnostics.pc2_share}% · ` +
    `Eigenvalue ratio λ₁/λ₂ = ${data.diagnostics.eigenvalue_ratio}.`;
}

function renderMethodology(data) {
  const ul = document.getElementById('methodology-list');
  const items = [
    `Streams: ${data.methodology.streams.join(', ')}`,
    `Window: ${data.panel_window.start} → ${data.panel_window.end} (${data.monthly.length} months)`,
    `Provinces aggregated: ${data.n_provinces}`,
    `Deseasonalization: ${data.methodology.deseasonalization}`,
    `Extraction: ${data.methodology.extraction}`,
    `Rescaling: ${data.methodology.rescaling}`,
    `Paper: ${data.methodology.paper}`,
  ];
  for (const t of items) {
    const li = document.createElement('li');
    li.textContent = t;
    ul.appendChild(li);
  }
}

function render(data) {
  renderHeader(data);
  renderIndex(data);
  renderStreams(data);
  renderFx(data);
  renderSubnat(data);
  renderDiagnostics(data);
  renderMethodology(data);
}

load();
