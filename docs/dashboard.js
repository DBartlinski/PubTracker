'use strict';

// ============================================================
// STATE
// ============================================================
let publications = [];   // raw records from publications.json
let matches = [];        // raw records from facility_matches.json
let filtered = [];       // publications after current filters
let filteredMatches = []; // matches restricted to filtered publications
let recordsPage = 0;
const RECORDS_PAGE_SIZE = 50;
let facilitiesChartPage = 0;
const FACILITIES_CHART_PAGE_SIZE = 10;
const charts = {};

const BROAD_PORTFOLIO_ORDER = [
  'Brain, Behavioral and Mental Health',
  'Health Systems Research',
  'Medical Health',
  'Rehabilitation Research, Development, and Translation',
  'Cooperative Studies Program',
  'Quality Enhancement Research Initiative',
];
const AMP_ORDER = [
  'Gulf War Illness', 'Military Exposures', 'Pain/Opioid Use (POU)',
  'Precision Oncology', 'Suicide Prevention', 'Traumatic Brain Injury',
];
const NO_SIGNAL_LABEL = 'No ORD signal detected';

// ============================================================
// LOAD DATA
// ============================================================
async function loadData() {
  const [pubResp, matchResp] = await Promise.all([
    fetch('./data/publications.json'),
    fetch('./data/facility_matches.json'),
  ]);
  if (!pubResp.ok) throw new Error(`Could not load publications.json (${pubResp.status})`);
  if (!matchResp.ok) throw new Error(`Could not load facility_matches.json (${matchResp.status})`);
  publications = await pubResp.json();
  matches = await matchResp.json();
}

// ============================================================
// HELPERS
// ============================================================
function uniqueSorted(values) {
  return Array.from(new Set(values.filter(v => v !== null && v !== undefined && v !== ''))).sort();
}

function populateMultiSelect(selectEl, values) {
  selectEl.innerHTML = '';
  values.forEach(v => {
    const opt = document.createElement('option');
    opt.value = v;
    opt.textContent = v;
    selectEl.appendChild(opt);
  });
}

function getSelectedValues(selectEl) {
  return Array.from(selectEl.selectedOptions).map(o => o.value);
}

function fmtPct(n, total) {
  return total ? `${Math.round((100 * n) / total)}%` : '0%';
}

function metricCard(label, value, delta) {
  return `<div class="col-md-3"><div class="metric-card">
    <div class="label">${label}</div>
    <div class="value">${value}</div>
    ${delta ? `<div class="delta">${delta}</div>` : ''}
  </div></div>`;
}

function destroyChart(id) {
  if (charts[id]) { charts[id].destroy(); delete charts[id]; }
}

function barChart(canvasId, labels, data, color = '#005ea2') {
  destroyChart(canvasId);
  const ctx = document.getElementById(canvasId).getContext('2d');
  charts[canvasId] = new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets: [{ data, backgroundColor: color }] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      resizeDelay: 100,
      animation: false,
      plugins: { legend: { display: false } },
      scales: { x: { ticks: { autoSkip: false, maxRotation: 60, minRotation: 0 } } },
    },
  });
}

function horizontalBarChart(canvasId, labels, data, color = '#005ea2') {
  destroyChart(canvasId);
  const ctx = document.getElementById(canvasId).getContext('2d');
  charts[canvasId] = new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets: [{ data, backgroundColor: color }] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      resizeDelay: 100,
      animation: false,
      indexAxis: 'y',
      plugins: { legend: { display: false } },
      scales: { y: { ticks: { autoSkip: false } } },
    },
  });
}

// ============================================================
// FILTERS
// ============================================================
function initFilterOptions() {
  populateMultiSelect(document.getElementById('fltFiscalYear'), uniqueSorted(publications.map(p => p.fiscalYear)).reverse());
  populateMultiSelect(document.getElementById('fltFacility'), uniqueSorted(matches.map(m => m.facility)));
  populateMultiSelect(document.getElementById('fltOrdBroad'), BROAD_PORTFOLIO_ORDER.filter(name => publications.some(p => (p.ordBroad || []).includes(name))));
  populateMultiSelect(document.getElementById('fltOrdAmp'), AMP_ORDER.filter(name => publications.some(p => (p.ordAmp || []).includes(name))));
}

function applyFilters() {
  const fiscalYears = getSelectedValues(document.getElementById('fltFiscalYear')).map(Number);
  const facilities = getSelectedValues(document.getElementById('fltFacility'));
  const ordBroad = getSelectedValues(document.getElementById('fltOrdBroad'));
  const ordAmp = getSelectedValues(document.getElementById('fltOrdAmp'));
  const search = document.getElementById('fltSearch').value.trim().toLowerCase();
  const includeAll = document.getElementById('fltIncludeAll').checked;

  const facilityPubIds = facilities.length
    ? new Set(matches.filter(m => facilities.includes(m.facility)).map(m => m.pubId))
    : null;

  filtered = publications.filter(p => {
    if (!includeAll && !p.sopEligible) return false;
    if (fiscalYears.length && !fiscalYears.includes(p.fiscalYear)) return false;
    if (facilityPubIds && !facilityPubIds.has(p.id)) return false;
    if (ordBroad.length && !ordBroad.some(name => (p.ordBroad || []).includes(name))) return false;
    if (ordAmp.length && !ordAmp.some(name => (p.ordAmp || []).includes(name))) return false;
    if (search) {
      const hay = `${p.title || ''} ${p.authors || ''} ${p.id || ''}`.toLowerCase();
      if (!hay.includes(search)) return false;
    }
    return true;
  });

  const filteredIds = new Set(filtered.map(p => p.id));
  filteredMatches = matches.filter(m => filteredIds.has(m.pubId) && (!facilities.length || facilities.includes(m.facility)));

  document.getElementById('filterSummary').textContent =
    `Showing ${filtered.length.toLocaleString()} of ${publications.length.toLocaleString()} source publications`;

  recordsPage = 0;
  renderActiveTab();
}

function resetFilters() {
  ['fltFiscalYear', 'fltFacility', 'fltOrdBroad', 'fltOrdAmp'].forEach(id => {
    Array.from(document.getElementById(id).options).forEach(o => (o.selected = false));
  });
  document.getElementById('fltSearch').value = '';
  document.getElementById('fltIncludeAll').checked = false;
  applyFilters();
}

// ============================================================
// TABS
// ============================================================
let activeTab = 'overview';
function renderActiveTab() {
  if (activeTab === 'overview') renderOverview();
  else if (activeTab === 'records') renderRecords();
  else if (activeTab === 'facilities') renderFacilities();
  else if (activeTab === 'ord') renderOrdPortfolios();
  else if (activeTab === 'impact') renderImpact();
}

function setupTabs() {
  document.querySelectorAll('#dashTabs .nav-link').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('#dashTabs .nav-link').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.add('d-none'));
      activeTab = btn.dataset.tab;
      document.getElementById(`tab-${activeTab}`).classList.remove('d-none');
      renderActiveTab();
    });
  });
}

// ============================================================
// OVERVIEW
// ============================================================
function renderOverview() {
  const total = filtered.length;
  const matchedPubIds = new Set(filteredMatches.map(m => m.pubId));
  const matchedCount = filtered.filter(p => matchedPubIds.has(p.id)).length;
  const openAccessRate = total ? (filtered.filter(p => p.openAccess).length / total) * 100 : 0;

  document.getElementById('overviewMetrics').innerHTML = [
    metricCard('Publications', total.toLocaleString()),
    metricCard('Mapped to a VAMC', matchedCount.toLocaleString()),
    metricCard('Unmatched', (total - matchedCount).toLocaleString()),
    metricCard('Open access', `${openAccessRate.toFixed(0)}%`),
  ].join('');

  const fyCounts = {};
  filtered.forEach(p => { if (p.fiscalYear) fyCounts[p.fiscalYear] = (fyCounts[p.fiscalYear] || 0) + 1; });
  const fyLabels = Object.keys(fyCounts).sort().map(y => `FY ${y}`);
  barChart('chartFyTrend', fyLabels, Object.keys(fyCounts).sort().map(y => fyCounts[y]));

  const docTypeCounts = {};
  filtered.forEach(p => { const t = p.docType || 'Unknown'; docTypeCounts[t] = (docTypeCounts[t] || 0) + 1; });
  const topDocTypes = Object.entries(docTypeCounts).sort((a, b) => b[1] - a[1]).slice(0, 10);
  barChart('chartDocTypes', topDocTypes.map(e => e[0]), topDocTypes.map(e => e[1]), '#bd5727');

  facilitiesChartPage = 0;
  renderTopFacilitiesChart();
  renderOverviewPortfolioChart();

  const assigned = filtered.filter(p => p.fiscalPeriod && p.fiscalPeriod !== 'Unavailable').length;
  barChart('chartFyCoverage', ['Assigned', 'Unavailable'], [assigned, total - assigned], '#71767a');
}

function renderOverviewPortfolioChart() {
  const broadCounts = {};
  filtered.forEach(p => (p.ordBroad || []).forEach(name => { broadCounts[name] = (broadCounts[name] || 0) + 1; }));
  const ampCounts = {};
  filtered.forEach(p => (p.ordAmp || []).forEach(name => { ampCounts[name] = (ampCounts[name] || 0) + 1; }));

  const broadEntries = BROAD_PORTFOLIO_ORDER.filter(n => broadCounts[n]).map(n => ({ label: n, count: broadCounts[n], type: 'broad' }));
  const ampEntries = AMP_ORDER.filter(n => ampCounts[n]).map(n => ({ label: n, count: ampCounts[n], type: 'amp' }));
  const combined = [...broadEntries, ...ampEntries].sort((a, b) => b.count - a.count);

  const labels = combined.map(e => e.label);
  const data = combined.map(e => e.count);
  const colors = combined.map(e => (e.type === 'broad' ? '#005ea2' : '#bd5727'));
  horizontalBarChart('chartOrdOverview', labels, data, colors);
}

function renderTopFacilitiesChart() {
  const facilityCounts = {};
  filteredMatches.forEach(m => { facilityCounts[m.facility] = (facilityCounts[m.facility] || 0) + 1; });
  const sorted = Object.entries(facilityCounts).sort((a, b) => b[1] - a[1]);
  const totalPages = Math.max(1, Math.ceil(sorted.length / FACILITIES_CHART_PAGE_SIZE));
  facilitiesChartPage = Math.min(facilitiesChartPage, totalPages - 1);
  const start = facilitiesChartPage * FACILITIES_CHART_PAGE_SIZE;
  const page = sorted.slice(start, start + FACILITIES_CHART_PAGE_SIZE);

  horizontalBarChart('chartTopFacilities', page.map(e => e[0]), page.map(e => e[1]), '#ca8a2c');

  document.getElementById('facilitiesChartPageInfo').textContent = sorted.length
    ? `Facilities ${start + 1}–${Math.min(start + FACILITIES_CHART_PAGE_SIZE, sorted.length)} of ${sorted.length}`
    : 'No facility matches under the current filters';
  document.getElementById('facilitiesChartPrev').disabled = facilitiesChartPage === 0;
  document.getElementById('facilitiesChartNext').disabled = facilitiesChartPage >= totalPages - 1;
}

// ============================================================
// RECORDS
// ============================================================
function renderRecords() {
  const start = recordsPage * RECORDS_PAGE_SIZE;
  const pageRows = filtered.slice(start, start + RECORDS_PAGE_SIZE);
  const tbody = document.getElementById('recordsBody');
  tbody.innerHTML = pageRows.map(p => {
    const links = [
      p.doiLink ? `<a href="${p.doiLink}" target="_blank" rel="noopener">DOI</a>` : '',
      p.pubmedLink ? `<a href="${p.pubmedLink}" target="_blank" rel="noopener">PubMed</a>` : '',
      p.dimensionsLink ? `<a href="${p.dimensionsLink}" target="_blank" rel="noopener">Dimensions</a>` : '',
    ].filter(Boolean).join(' · ');
    return `<tr>
      <td>${escapeHtml(p.title || '')}</td>
      <td>${escapeHtml(p.id || '')}</td>
      <td>${p.date || ''}</td>
      <td>${escapeHtml(p.fiscalPeriod || '')}</td>
      <td>${escapeHtml(p.docType || '')}</td>
      <td>${escapeHtml((p.facilities || []).join('; '))}</td>
      <td>${escapeHtml(p.journal || '')}</td>
      <td>${p.citations ?? ''}</td>
      <td>${links}</td>
    </tr>`;
  }).join('');

  const totalPages = Math.max(1, Math.ceil(filtered.length / RECORDS_PAGE_SIZE));
  document.getElementById('recordsPageInfo').textContent =
    `Page ${filtered.length ? recordsPage + 1 : 0} of ${totalPages} (${filtered.length.toLocaleString()} records)`;
  document.getElementById('recordsPrev').disabled = recordsPage === 0;
  document.getElementById('recordsNext').disabled = recordsPage >= totalPages - 1;
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function downloadFilteredCsv() {
  const columns = ['id', 'title', 'authors', 'journal', 'docType', 'date', 'fiscalPeriod', 'facilities', 'citations', 'ordBroad', 'ordAmp'];
  const header = columns.join(',');
  const rows = filtered.map(p => columns.map(c => {
    let v = p[c];
    if (Array.isArray(v)) v = v.join('; ');
    v = (v ?? '').toString().replace(/"/g, '""');
    return `"${v}"`;
  }).join(','));
  const blob = new Blob([header + '\n' + rows.join('\n')], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `dimensions_filtered_${filtered.length}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ============================================================
// FACILITIES
// ============================================================
function renderFacilities() {
  const byFacility = {};
  filteredMatches.forEach(m => {
    const key = `${m.facility}||${m.stationNumbers}`;
    if (!byFacility[key]) byFacility[key] = { facility: m.facility, stations: m.stationNumbers, pubIds: new Set(), strong: 0, weak: 0 };
    byFacility[key].pubIds.add(m.pubId);
    if (m.matchStrength === 'strong') byFacility[key].strong += 1;
    else if (m.matchStrength === 'weak') byFacility[key].weak += 1;
  });
  const rows = Object.values(byFacility).sort((a, b) => b.pubIds.size - a.pubIds.size);
  document.getElementById('facilitiesBody').innerHTML = rows.map(r => `<tr>
    <td>${escapeHtml(r.facility)}</td><td>${escapeHtml(r.stations)}</td>
    <td>${r.pubIds.size}</td><td>${r.strong}</td><td>${r.weak}</td>
  </tr>`).join('') || '<tr><td colspan="5" class="text-muted">No facility matches under the current filters.</td></tr>';
}

// ============================================================
// ORD PORTFOLIOS
// ============================================================
function renderOrdPortfolios() {
  const total = filtered.length;
  const withBroad = filtered.filter(p => p.hasOrdEvidence).length;
  const withAmp = filtered.filter(p => (p.ordAmp || []).length > 0).length;
  const withNeither = filtered.filter(p => !p.hasOrdEvidence && (p.ordAmp || []).length === 0).length;
  const withAnyOrd = total - withNeither;

  document.getElementById('ordMetrics').innerHTML = [
    metricCard('Publications', total.toLocaleString()),
    metricCard('Total ORD-funded (unique)', withAnyOrd.toLocaleString(), fmtPct(withAnyOrd, total)),
    metricCard('With Broad Portfolio evidence', withBroad.toLocaleString(), fmtPct(withBroad, total)),
    metricCard('With Actively Managed tag', withAmp.toLocaleString(), fmtPct(withAmp, total)),
    metricCard(NO_SIGNAL_LABEL, withNeither.toLocaleString(), fmtPct(withNeither, total)),
  ].join('');

  const broadCounts = {};
  filtered.forEach(p => (p.ordBroad || []).forEach(name => { broadCounts[name] = (broadCounts[name] || 0) + 1; }));
  const broadEntries = BROAD_PORTFOLIO_ORDER.filter(n => broadCounts[n]).map(n => [n, broadCounts[n]]);
  barChart('chartOrdBroad', broadEntries.map(e => e[0]), broadEntries.map(e => e[1]));

  const ampCounts = {};
  filtered.forEach(p => (p.ordAmp || []).forEach(name => { ampCounts[name] = (ampCounts[name] || 0) + 1; }));
  const ampEntries = AMP_ORDER.filter(n => ampCounts[n]).map(n => [n, ampCounts[n]]);
  barChart('chartOrdAmp', ampEntries.map(e => e[0]), ampEntries.map(e => e[1]), '#bd5727');

  const facilityByPub = {};
  filteredMatches.forEach(m => { (facilityByPub[m.pubId] = facilityByPub[m.pubId] || []).push(m.facility); });
  const facilityPortfolioCounts = {};
  filtered.forEach(p => {
    if (!p.ordBroad || !p.ordBroad.length) return;
    const facilities = facilityByPub[p.id] || [];
    facilities.forEach(facility => {
      p.ordBroad.forEach(portfolio => {
        const key = `${facility}||${portfolio}`;
        facilityPortfolioCounts[key] = (facilityPortfolioCounts[key] || 0) + 1;
      });
    });
  });
  const rows = Object.entries(facilityPortfolioCounts)
    .map(([key, count]) => { const [facility, portfolio] = key.split('||'); return { facility, portfolio, count }; })
    .sort((a, b) => b.count - a.count);
  document.getElementById('ordFacilityBody').innerHTML = rows.map(r =>
    `<tr><td>${escapeHtml(r.facility)}</td><td>${escapeHtml(r.portfolio)}</td><td>${r.count}</td></tr>`
  ).join('') || '<tr><td colspan="3" class="text-muted">No Broad Portfolio evidence under the current filters.</td></tr>';
}

// ============================================================
// RESEARCH IMPACT
// ============================================================
function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}
function mean(values) {
  return values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
}

function renderImpact() {
  const citations = filtered.map(p => p.citations).filter(v => v !== null && v !== undefined);
  const rcrValues = filtered.map(p => p.rcr).filter(v => v !== null && v !== undefined);
  const fcrValues = filtered.map(p => p.fcr).filter(v => v !== null && v !== undefined);
  const journals = new Set(filtered.map(p => p.journal).filter(Boolean));

  document.getElementById('impactMetrics').innerHTML = [
    metricCard('Median citations', citations.length ? median(citations).toFixed(0) : '0'),
    metricCard('Mean RCR', rcrValues.length ? mean(rcrValues).toFixed(2) : 'N/A'),
    metricCard('Mean FCR', fcrValues.length ? mean(fcrValues).toFixed(2) : 'N/A'),
    metricCard('Unique journals', journals.size.toLocaleString()),
  ].join('');

  const journalCounts = {};
  filtered.forEach(p => { const j = p.journal || 'Unknown'; journalCounts[j] = (journalCounts[j] || 0) + 1; });
  const topJournals = Object.entries(journalCounts).sort((a, b) => b[1] - a[1]).slice(0, 15);
  barChart('chartJournals', topJournals.map(e => e[0]), topJournals.map(e => e[1]));

  const bins = [0, 0, 0, 0, 0, 0, 0]; // 0, 1-2, 3-5, 6-10, 11-25, 26-50, 51-100+
  citations.forEach(c => {
    const v = Math.min(c, 100);
    if (v === 0) bins[0]++;
    else if (v <= 2) bins[1]++;
    else if (v <= 5) bins[2]++;
    else if (v <= 10) bins[3]++;
    else if (v <= 25) bins[4]++;
    else if (v <= 50) bins[5]++;
    else bins[6]++;
  });
  barChart('chartCitations', ['0', '1–2', '3–5', '6–10', '11–25', '26–50', '51–100+'], bins, '#71767a');
}

// ============================================================
// INIT
// ============================================================
async function init() {
  try {
    await loadData();
    initFilterOptions();
    setupTabs();
    document.getElementById('fltFiscalYear').addEventListener('change', applyFilters);
    document.getElementById('fltFacility').addEventListener('change', applyFilters);
    document.getElementById('fltOrdBroad').addEventListener('change', applyFilters);
    document.getElementById('fltOrdAmp').addEventListener('change', applyFilters);
    document.getElementById('fltIncludeAll').addEventListener('change', applyFilters);
    document.getElementById('fltSearch').addEventListener('input', debounce(applyFilters, 250));
    document.getElementById('fltReset').addEventListener('click', resetFilters);
    document.getElementById('btnDownloadCsv').addEventListener('click', downloadFilteredCsv);
    document.getElementById('recordsPrev').addEventListener('click', () => { if (recordsPage > 0) { recordsPage--; renderRecords(); } });
    document.getElementById('recordsNext').addEventListener('click', () => {
      const totalPages = Math.max(1, Math.ceil(filtered.length / RECORDS_PAGE_SIZE));
      if (recordsPage < totalPages - 1) { recordsPage++; renderRecords(); }
    });
    document.getElementById('facilitiesChartPrev').addEventListener('click', () => {
      if (facilitiesChartPage > 0) { facilitiesChartPage--; renderTopFacilitiesChart(); }
    });
    document.getElementById('facilitiesChartNext').addEventListener('click', () => {
      facilitiesChartPage++; renderTopFacilitiesChart();
    });

    applyFilters();
    document.getElementById('loadingMsg').classList.add('d-none');
    document.getElementById('dashboardRoot').classList.remove('d-none');
  } catch (error) {
    document.getElementById('loadingMsg').classList.add('d-none');
    const errEl = document.getElementById('loadError');
    errEl.textContent = `Could not load dashboard data: ${error.message}`;
    errEl.classList.remove('d-none');
  }
}

function debounce(fn, delay) {
  let timer;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), delay); };
}

init();
