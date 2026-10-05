'use strict';

// Dimensions-PubTracker compliance section. Data comes from data/pubtracker_gap.json
// (built by build_static_dashboard_data.py): Dimensions FY26 records with their best PubTracker
// title-match score, so any slider threshold can be applied here without PubTracker titles.
(function () {
  const REC = { ID: 0, DATE: 1, TITLE: 2, JOURNAL: 3, DOI: 4, PMID: 5, FACS: 6, SCORE: 7 };
  let payload = null;
  let facilityRows = [];
  let selectedFacility = null;
  const $ = id => document.getElementById(id);

  function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function download(rows, filename) {
    const csv = rows.map(r => r.map(v => `"${String(v ?? '').replace(/"/g, '""')}"`).join(',')).join('\n');
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  function currentView() {
    const label = $('ptgapPeriod').value;
    const period = payload.periods[label];
    const threshold = Number($('ptgapThreshold').value);
    const records = payload.records.filter(r => r[REC.DATE] >= period.start && r[REC.DATE] <= period.end);
    const isFound = r => r[REC.SCORE] >= threshold;
    return { label, period, threshold, records, isFound };
  }

  function render() {
    const { period, threshold, records, isFound } = currentView();
    $('ptgapThresholdValue').textContent = `${threshold}%`;

    const found = records.filter(isFound);
    const exact = found.filter(r => r[REC.SCORE] === 100).length;
    const rate = records.length ? (100 * found.length / records.length).toFixed(1) : '0.0';
    const card = (label, value) => `<div class="col-6 col-md"><div class="card text-center h-100"><div class="card-body py-2">
      <div class="small text-muted">${label}</div><div class="fs-4 fw-semibold">${value}</div></div></div></div>`;
    $('ptgapMetrics').innerHTML = [
      card('Dimensions records', records.length.toLocaleString()),
      card('Found in PubTracker', found.length.toLocaleString()),
      card('Exact / fuzzy', `${exact.toLocaleString()} / ${(found.length - exact).toLocaleString()}`),
      card('Missing from PubTracker', (records.length - found.length).toLocaleString()),
      card('Overall submission rate', `${rate}%`),
    ].join('');
    $('ptgapNote').textContent =
      `All ${payload.pubtrackerRows.toLocaleString()} PubTracker publication submissions are compared with the Dimensions records ` +
      `dated ${period.start} to ${period.end}. The Dimensions publication date decides the period.`;

    const stats = new Map();
    records.forEach(r => {
      const names = r[REC.FACS].length ? r[REC.FACS].map(i => payload.facilities[i]) : [payload.unattributedLabel];
      names.forEach(name => {
        if (!stats.has(name)) stats.set(name, { facility: name, total: 0, found: 0, missing: [] });
        const s = stats.get(name);
        s.total += 1;
        if (isFound(r)) s.found += 1; else s.missing.push(r);
      });
    });
    facilityRows = Array.from(stats.values())
      .map(s => ({ ...s, rate: 100 * s.found / s.total }))
      .sort((a, b) => b.missing.length - a.missing.length || b.total - a.total);

    $('ptgapBody').innerHTML = facilityRows.map((f, i) => `<tr data-idx="${i}" style="cursor:pointer">
      <td>${esc(f.facility)}</td><td>${f.total}</td><td>${f.found}</td><td>${f.missing.length}</td><td>${f.rate.toFixed(1)}%</td></tr>`).join('');
    $('ptgapBody').querySelectorAll('tr').forEach(tr => {
      tr.addEventListener('click', () => showDetail(facilityRows[Number(tr.dataset.idx)]));
    });

    const stillSelected = selectedFacility && facilityRows.find(f => f.facility === selectedFacility);
    if (stillSelected) showDetail(stillSelected, false); else $('ptgapDetail').classList.add('d-none');
  }

  function recordLinks(r) {
    return [
      r[REC.DOI] ? ['DOI', `https://doi.org/${r[REC.DOI]}`] : null,
      r[REC.PMID] ? ['PubMed', `https://pubmed.ncbi.nlm.nih.gov/${r[REC.PMID]}/`] : null,
      ['Dimensions', `https://va.dimensions.ai/details/publication/${r[REC.ID]}`],
    ].filter(Boolean);
  }

  function showDetail(facility, scroll = true) {
    selectedFacility = facility.facility;
    $('ptgapDetailTitle').textContent =
      `${facility.facility}: ${facility.missing.length.toLocaleString()} Dimensions records not found in PubTracker`;
    $('ptgapDetailBody').innerHTML = facility.missing.map(r => {
      const links = recordLinks(r).map(([name, url]) => `<a href="${esc(url)}" target="_blank" rel="noopener">${name}</a>`).join(' &middot; ');
      return `<tr><td>${esc(r[REC.TITLE])}</td><td>${esc(r[REC.DATE])}</td><td>${esc(r[REC.JOURNAL])}</td><td>${links}</td></tr>`;
    }).join('') || '<tr><td colspan="4" class="text-muted">No missing records.</td></tr>';
    $('ptgapDetail').classList.remove('d-none');
    if (scroll) $('ptgapDetail').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  async function init() {
    let data = null;
    try {
      const resp = await fetch(`./data/pubtracker_gap.json?v=${Date.now()}`, { cache: 'no-store' });
      data = resp.ok ? await resp.json() : null;
    } catch (e) {
      data = null;
    }
    if (!data) {
      $('ptgapMetrics').innerHTML = '<div class="col-12 small text-muted">PubTracker comparison data is not available.</div>';
      return;
    }
    payload = data;
    $('ptgapPeriod').innerHTML = Object.keys(payload.periods).map(k => `<option>${esc(k)}</option>`).join('');
    const slider = $('ptgapThreshold');
    slider.min = payload.minThreshold;
    slider.max = 100;
    slider.value = payload.defaultThreshold;
    $('ptgapPeriod').addEventListener('change', render);
    slider.addEventListener('input', render);
    $('btnDownloadPtgapCsv').addEventListener('click', () => download(
      [['Facility', 'Dimensions records', 'In PubTracker', 'Missing', 'Submission rate %'],
        ...facilityRows.map(f => [f.facility, f.total, f.found, f.missing.length, f.rate.toFixed(1)])],
      'dimensions_pubtracker_facility_rates.csv'));
    $('btnDownloadPtgapMissingCsv').addEventListener('click', () => {
      const facility = facilityRows.find(f => f.facility === selectedFacility);
      if (!facility) return;
      download(
        [['Title', 'Date', 'Journal', 'Publication ID', 'DOI', 'PMID'],
          ...facility.missing.map(r => [r[REC.TITLE], r[REC.DATE], r[REC.JOURNAL], r[REC.ID], r[REC.DOI], r[REC.PMID]])],
        'dimensions_missing_from_pubtracker.csv');
    });
    render();
  }

  document.addEventListener('DOMContentLoaded', init);
})();
