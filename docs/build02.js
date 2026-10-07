'use strict';

// Build 02: Dimensions publications not in PubTracker. Data from data/not_in_pubtracker.json
// (build_static_dashboard_data.py), matched at a fixed 90% title threshold; Dimensions fields only.
(function () {
  const R = { ID: 0, DATE: 1, FP: 2, TITLE: 3, JOURNAL: 4, DOI: 5, PMID: 6, FACS: 7, FOUND: 8, ORD: 9, CODES: 10, PORTFOLIO: 11, FUNDERS: 12, GRANTS: 13 };
  const MAX_ROWS = 500;
  let payload = null;
  let view = 'missing';
  let facilityRows = [];
  let listRows = [];
  const selected = new Set();
  const $ = id => document.getElementById(id);

  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function download(rows, filename) {
    const csv = rows.map(r => r.map(v => `"${String(v ?? '').replace(/"/g, '""')}"`).join(',')).join('\n');
    const url = URL.createObjectURL(new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  const facilityNames = r => (r[R.FACS].length ? r[R.FACS].map(i => payload.facilities[i]) : [payload.unattributedLabel]);

  function periodRecords() {
    const period = payload.periods[$('b02Period').value];
    return payload.records.filter(r => r[R.DATE] >= period.start && r[R.DATE] <= period.end);
  }

  function links(r) {
    return [
      r[R.DOI] ? ['DOI', `https://doi.org/${r[R.DOI]}`] : null,
      r[R.PMID] ? ['PubMed', `https://pubmed.ncbi.nlm.nih.gov/${r[R.PMID]}/`] : null,
      ['Dimensions', `https://va.dimensions.ai/details/publication/${r[R.ID]}`],
    ].filter(Boolean);
  }

  function renderSummary(records) {
    const entered = records.filter(r => r[R.FOUND]).length;
    const rate = records.length ? (100 * entered / records.length).toFixed(1) : '0.0';
    const card = (label, value) => `<div class="col-6 col-md"><div class="card text-center h-100"><div class="card-body py-2">
      <div class="small text-muted">${label}</div><div class="fs-4 fw-semibold">${value}</div></div></div></div>`;
    $('b02Metrics').innerHTML = [
      card(`Dimensions publications (${esc($('b02Period').value)})`, records.length.toLocaleString()),
      card('Entered in PubTracker', entered.toLocaleString()),
      card('Not in PubTracker', (records.length - entered).toLocaleString()),
      card('Compliance %', `${rate}%`),
    ].join('');

    const stats = new Map();
    records.forEach(r => facilityNames(r).forEach(name => {
      if (!stats.has(name)) stats.set(name, { facility: name, total: 0, entered: 0 });
      const s = stats.get(name);
      s.total += 1;
      if (r[R.FOUND]) s.entered += 1;
    }));
    facilityRows = Array.from(stats.values())
      .map(s => ({ ...s, missing: s.total - s.entered, rate: 100 * s.entered / s.total }))
      .sort((a, b) => b.missing - a.missing || b.total - a.total);
    [...selected].forEach(name => { if (!stats.has(name)) selected.delete(name); });

    $('b02FacilityBody').innerHTML = facilityRows.map((f, i) => `<tr data-idx="${i}" style="cursor:pointer" class="${selected.has(f.facility) ? 'table-primary' : ''}">
      <td>${esc(f.facility)}</td><td>${f.missing.toLocaleString()}</td><td>${f.entered.toLocaleString()}</td><td>${f.total.toLocaleString()}</td>
      <td><div class="d-flex align-items-center gap-2"><div class="progress flex-grow-1" style="height:8px"><div class="progress-bar" style="width:${f.rate.toFixed(1)}%"></div></div><span>${f.rate.toFixed(1)}%</span></div></td></tr>`).join('');
    $('b02FacilityBody').querySelectorAll('tr').forEach(tr => tr.addEventListener('click', () => {
      const name = facilityRows[Number(tr.dataset.idx)].facility;
      if (selected.has(name)) selected.delete(name); else selected.add(name);
      render();
    }));
  }

  function matchesFilters(r) {
    const funding = $('b02Funding').value;
    if (funding === 'ord' && !r[R.ORD]) return false;
    if (funding === 'grant' && !r[R.GRANTS] && !r[R.CODES]) return false;
    if (funding === 'none' && (r[R.GRANTS] || r[R.CODES] || r[R.FUNDERS])) return false;
    const portfolio = $('b02Portfolio').value;
    if (portfolio && !r[R.PORTFOLIO].split('; ').includes(portfolio)) return false;
    const query = $('b02Search').value.trim().toLowerCase();
    if (query && ![r[R.TITLE], r[R.JOURNAL], r[R.FUNDERS], r[R.GRANTS], r[R.CODES]].join(' ').toLowerCase().includes(query)) return false;
    return true;
  }

  function renderList(records) {
    const filtered = records.filter(matchesFilters);
    const counts = { missing: 0, entered: 0 };
    filtered.forEach(r => {
      if (selected.size && !facilityNames(r).some(name => selected.has(name))) return;
      counts[r[R.FOUND] ? 'entered' : 'missing'] += 1;
    });
    $('b02TabMissing').textContent = `Not in PubTracker (${counts.missing.toLocaleString()} publications)`;
    $('b02TabEntered').textContent = `In PubTracker (${counts.entered.toLocaleString()} publications)`;

    listRows = [];
    filtered.filter(r => Boolean(r[R.FOUND]) === (view === 'entered')).forEach(r => {
      facilityNames(r).forEach(name => {
        if (!selected.size || selected.has(name)) listRows.push({ r, facility: name });
      });
    });
    $('b02SelectedFacilities').innerHTML = selected.size
      ? [...selected].map(name => `<span class="badge text-bg-primary me-1 mb-1">${esc(name)}</span>`).join('') +
        ' <a href="#" id="b02ClearFacilities">clear</a>'
      : '<span class="text-muted">All facilities (click rows above to choose)</span>';
    const clear = $('b02ClearFacilities');
    if (clear) clear.addEventListener('click', e => { e.preventDefault(); selected.clear(); render(); });

    const ordCount = new Set(listRows.filter(x => x.r[R.ORD]).map(x => x.r[R.ID])).size;
    const unique = new Set(listRows.map(x => x.r[R.ID])).size;
    $('b02ListNote').textContent = `${unique.toLocaleString()} publications (${listRows.length.toLocaleString()} facility rows); ` +
      `${ordCount.toLocaleString()} with VA/ORD grant evidence. Newest Dimensions publication date first.` +
      (listRows.length > MAX_ROWS ? ` Showing the first ${MAX_ROWS}; the download includes all rows.` : '');

    $('b02ListBody').innerHTML = listRows.slice(0, MAX_ROWS).map(({ r, facility }, i) => `<tr data-idx="${i}" style="cursor:pointer">
      <td class="text-nowrap">${esc(r[R.DATE])}</td><td>${esc(facility)}</td><td>${esc(r[R.TITLE])}</td><td>${esc(r[R.JOURNAL])}</td>
      <td>${r[R.ORD] ? '✔' : ''}</td><td>${esc(r[R.CODES])}</td><td>${esc(r[R.FUNDERS])}</td><td>${esc(r[R.GRANTS])}</td>
      <td class="text-nowrap">${links(r).map(([n, u]) => `<a href="${esc(u)}" target="_blank" rel="noopener">${n}</a>`).join(' · ')}</td></tr>`).join('')
      || '<tr><td colspan="9" class="text-muted">No publications match the current selection.</td></tr>';
    $('b02ListBody').querySelectorAll('tr[data-idx]').forEach(tr => tr.addEventListener('click', e => {
      if (e.target.closest('a')) return;
      const next = tr.nextElementSibling;
      if (next && next.classList.contains('b02-detail')) { next.remove(); return; }
      const { r } = listRows[Number(tr.dataset.idx)];
      tr.insertAdjacentHTML('afterend', `<tr class="b02-detail table-light"><td colspan="9" class="small">
        <div class="row">
          <div class="col-md-6">
            <div><strong>Dimensions date:</strong> ${esc(r[R.DATE])} (${esc(r[R.FP])})</div>
            <div><strong>Journal:</strong> ${esc(r[R.JOURNAL]) || '-'}</div>
            <div><strong>All facilities:</strong> ${esc(facilityNames(r).join('; '))}</div>
            <div><strong>In PubTracker:</strong> ${r[R.FOUND] ? 'Yes (title match)' : 'No'}</div>
          </div>
          <div class="col-md-6">
            <div><strong>ORD funded:</strong> ${r[R.ORD] ? 'Yes' : 'No evidence'}</div>
            <div><strong>VA grant codes:</strong> ${esc(r[R.CODES]) || '-'}</div>
            <div><strong>ORD portfolio:</strong> ${esc(r[R.PORTFOLIO]) || '-'}</div>
            <div><strong>Funders:</strong> ${esc(r[R.FUNDERS]) || '-'}</div>
            <div><strong>Grant numbers:</strong> ${esc(r[R.GRANTS]) || '-'}</div>
          </div>
        </div></td></tr>`);
    }));
  }

  function render() {
    const records = periodRecords();
    renderSummary(records);
    renderList(records);
  }

  async function init() {
    try {
      const resp = await fetch(`./data/not_in_pubtracker.json?v=${Date.now()}`, { cache: 'no-store' });
      payload = resp.ok ? await resp.json() : null;
    } catch (e) {
      payload = null;
    }
    if (!payload) {
      $('b02Metrics').innerHTML = '<div class="col-12 small text-muted">Build 02 data is not available.</div>';
      return;
    }
    $('b02Period').innerHTML = Object.keys(payload.periods).map(k => `<option>${esc(k)}</option>`).join('');
    const portfolios = new Set();
    payload.records.forEach(r => r[R.PORTFOLIO] && r[R.PORTFOLIO].split('; ').forEach(p => portfolios.add(p)));
    $('b02Portfolio').innerHTML += [...portfolios].sort().map(p => `<option>${esc(p)}</option>`).join('');

    ['b02Period', 'b02Funding', 'b02Portfolio'].forEach(id => $(id).addEventListener('change', render));
    let timer = null;
    $('b02Search').addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(render, 250); });
    $('b02ViewTabs').querySelectorAll('button').forEach(btn => btn.addEventListener('click', () => {
      view = btn.dataset.view;
      $('b02ViewTabs').querySelectorAll('button').forEach(b => b.classList.toggle('active', b === btn));
      renderList(periodRecords());
    }));
    $('b02DownloadFacilities').addEventListener('click', () => download(
      [['Facility', 'Not in PubTracker', 'Entered in PubTracker', 'Dimensions publications', 'Compliance %'],
        ...facilityRows.map(f => [f.facility, f.missing, f.entered, f.total, f.rate.toFixed(1)])],
      'pubtracker_compliance_by_facility.csv'));
    $('b02DownloadList').addEventListener('click', () => download(
      [['Dimensions Date', 'Fiscal Period', 'Facility', 'Title', 'Journal', 'In PubTracker', 'ORD Funded', 'VA Grant Codes',
        'ORD Portfolio', 'Funders', 'Grant Numbers', 'DOI', 'PMID', 'Publication ID'],
        ...listRows.map(({ r, facility }) => [r[R.DATE], r[R.FP], facility, r[R.TITLE], r[R.JOURNAL], r[R.FOUND] ? 'Yes' : 'No',
          r[R.ORD] ? 'Yes' : 'No', r[R.CODES], r[R.PORTFOLIO], r[R.FUNDERS], r[R.GRANTS], r[R.DOI], r[R.PMID], r[R.ID]])],
      view === 'entered' ? 'dimensions_in_pubtracker_by_facility.csv' : 'dimensions_not_in_pubtracker_by_facility.csv'));
    render();
  }

  document.addEventListener('DOMContentLoaded', init);
})();
