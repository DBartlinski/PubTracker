'use strict';

// ============================================================
// 1. CONSTANTS
// ============================================================
const EXCLUDED_DOC_TYPES = new Set(['conference abstract', 'correction erratum']);

// ============================================================
// 2. STATE
// ============================================================
let vamcRef          = [];   // rows from vamc_reference.csv
let ptRaw            = null; // { text, result } after PT upload
let dimRawText       = null; // raw CSV text after Dimensions upload
let availableQuarters = [];  // [{fy, q, label}] detected from PubTracker
let selectedQuarters  = [];  // [{fy, q, label}] chosen by user
let resultRows        = [];  // final compliance table rows

// ============================================================
// 3. VA FISCAL YEAR UTILITIES
// ============================================================

/** Parse a date string safely, always using noon-UTC to avoid timezone edge cases. */
function parseDate(str) {
  if (!str) return null;
  const s = str.toString().trim();
  
  // Try YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS format
  const datePart = s.split(/[ T]/)[0]; // "2026-03-31" from "2026-03-31 17:41:56"
  if (/^\d{4}-\d{2}-\d{2}$/.test(datePart))
    return new Date(datePart + 'T12:00:00Z');
  if (/^\d{4}-\d{2}$/.test(datePart))
    return new Date(datePart + '-15T12:00:00Z');
  if (/^\d{4}$/.test(datePart))
    return new Date(datePart + '-07-01T12:00:00Z');
  
  // Try MM/DD/YYYY format (common in US exports)
  if (/^\d{1,2}\/\d{1,2}\/\d{4}$/.test(datePart)) {
    const [m, d, y] = datePart.split('/');
    return new Date(Date.UTC(parseInt(y, 10), parseInt(m, 10) - 1, parseInt(d, 10), 12, 0, 0));
  }
  
  // Try DD/MM/YYYY format
  if (/^\d{2}\/\d{2}\/\d{4}$/.test(datePart)) {
    const parts = datePart.split('/');
    const m = parseInt(parts[1], 10);
    const d = parseInt(parts[0], 10);
    const y = parseInt(parts[2], 10);
    if (m >= 1 && m <= 12 && d >= 1 && d <= 31) {
      return new Date(Date.UTC(y, m - 1, d, 12, 0, 0));
    }
  }
  
  return null;
}

function getFYQuarter(date) {
  const m = date.getUTCMonth() + 1; // 1–12
  const y = date.getUTCFullYear();
  if (m >= 10) return { fy: y + 1, q: 1 };
  if (m <= 3)  return { fy: y,     q: 2 };
  if (m <= 6)  return { fy: y,     q: 3 };
  return             { fy: y,     q: 4 };
}

function quarterKey(fy, q) { return `${fy}-${q}`; }

function getQuarterLabel(fy, q) {
  return `FY${String(fy).slice(2)} Q${q}`;
}

/**
 * Return inclusive UTC start/end dates for a VA fiscal quarter.
 * End dates are set to 23:59:59 UTC so full-day comparisons work correctly.
 */
function getQuarterDateRange(fy, q) {
  const e = 23, m59 = 59, s59 = 59;
  if (q === 1) return {
    start: new Date(Date.UTC(fy - 1, 9,  1)),
    end:   new Date(Date.UTC(fy - 1, 11, 31, e, m59, s59)),
  };
  if (q === 2) return {
    start: new Date(Date.UTC(fy, 0, 1)),
    end:   new Date(Date.UTC(fy, 2,  31, e, m59, s59)),
  };
  if (q === 3) return {
    start: new Date(Date.UTC(fy, 3, 1)),
    end:   new Date(Date.UTC(fy, 5,  30, e, m59, s59)),
  };
  return {
    start: new Date(Date.UTC(fy, 6, 1)),
    end:   new Date(Date.UTC(fy, 8,  30, e, m59, s59)),
  };
}

// ============================================================
// 4. VAMC REFERENCE LOADING
// ============================================================
async function loadVamcRef() {
  const resp = await fetch('./vamc_reference.csv');
  if (!resp.ok) throw new Error(`Could not load vamc_reference.csv (${resp.status})`);
  const text = await resp.text();
  const parsed = Papa.parse(text, { header: true, skipEmptyLines: true });
  const seen = new Set();
  vamcRef = parsed.data.filter(row => {
    if (seen.has(row.vamc_display)) return false;
    seen.add(row.vamc_display);
    return true;
  });
}

// ============================================================
// 5. PUBTRACKER PROCESSING
// ============================================================
function parsePubTracker(csvText, includePresentation = false) {
  const parsed = Papa.parse(csvText.trimStart(), {  // trimStart removes BOM artifact
    header: true,
    skipEmptyLines: true,
    transformHeader: h => h.trim(),
  });

  const fields = parsed.meta.fields || [];

  // Find the submission-type column (handles the source typo "Submittion Type")
  const typeCol = fields.find(f =>
    f.toLowerCase().includes('submission') || f.toLowerCase().includes('submittion')
  );
  if (!typeCol) throw new Error('Could not find submission type column in PubTracker file. Expected "Submittion Type" or "Submission Type".');

  const allowed = new Set(['publication']);
  if (includePresentation) allowed.add('presentation');

  const excluded = {};
  const kept = [];
  parsed.data.forEach(row => {
    const t = (row[typeCol] || '').trim().toLowerCase();
    if (allowed.has(t)) {
      kept.push(row);
    } else {
      excluded[t] = (excluded[t] || 0) + 1;
    }
  });

  // Group counts by fiscal quarter and station number
  const counts = {};          // quarterKey -> { stationNo -> count }
  const quarterMeta = new Map(); // quarterKey -> {fy, q, label}

  kept.forEach(row => {
    const d = parseDate(row['Date Created']);
    if (!d) return;
    const { fy, q } = getFYQuarter(d);
    const key = quarterKey(fy, q);
    if (!counts[key]) {
      counts[key] = {};
      quarterMeta.set(key, { fy, q, label: getQuarterLabel(fy, q) });
    }
    const station = (row['POC Medical Center Number'] || '').toString().trim();
    if (station) counts[key][station] = (counts[key][station] || 0) + 1;
  });

  const quartersFound = Array.from(quarterMeta.values())
    .sort((a, b) => a.fy !== b.fy ? a.fy - b.fy : a.q - b.q);

  return { counts, quartersFound, excluded, totalKept: kept.length };
}

// ============================================================
// 6. DIMENSIONS PROCESSING
// ============================================================
function parseDimensions(csvText, startDate = null, endDate = null) {
  // Strip UTF-8 BOM if present
  if (csvText.charCodeAt(0) === 0xFEFF) csvText = csvText.slice(1);

  // Locate the real header row (contains Rank + Publication ID + DOI)
  const lines = csvText.split('\n');
  let headerIdx = -1;
  for (let i = 0; i < Math.min(lines.length, 20); i++) {
    const l = lines[i];
    if (l.includes('Rank') && l.includes('Publication ID') && l.includes('DOI')) {
      headerIdx = i;
      break;
    }
  }
  const dataText = headerIdx >= 0 ? lines.slice(headerIdx).join('\n') : csvText;

  const parsed = Papa.parse(dataText, {
    header: true,
    skipEmptyLines: true,
    transformHeader: h => h.trim(),
  });

  const fields = parsed.meta.fields || [];

  // Required column: Research Organizations – standardized
  const orgCol = fields.find(f =>
    f.toLowerCase().includes('research organizations') && f.toLowerCase().includes('standardized')
  );
  if (!orgCol) throw new Error(
    "Could not find 'Research Organizations - standardized' column in Dimensions file. " +
    "Ensure the file is a standard Dimensions XLSX/CSV export."
  );

  const pubIdCol = fields.includes('Publication ID') ? 'Publication ID' : fields[1];

  // Publication date column (primary, not online/print variants)
  const pubDateCol = fields.find(f =>
    f.toLowerCase().includes('publication date') &&
    !f.toLowerCase().includes('online') &&
    !f.toLowerCase().includes('print')
  );

  // Remove excluded document types
  let rows = parsed.data.filter(row =>
    !EXCLUDED_DOC_TYPES.has((row['Document Type'] || '').trim().toLowerCase())
  );

  // Collect overall date stats (before filtering)
  const allDates = rows
    .map(row => pubDateCol ? parseDate(row[pubDateCol]) : null)
    .filter(Boolean);
  const totalCount = rows.length;
  const minDate = allDates.length ? new Date(Math.min(...allDates)) : null;
  const maxDate = allDates.length ? new Date(Math.max(...allDates)) : null;

  // Apply quarter date filter if requested
  if (startDate && endDate) {
    rows = rows.filter(row => {
      if (!pubDateCol) return true;
      const d = parseDate(row[pubDateCol]);
      if (!d) return true;   // keep rows with no parseable date
      return d >= startDate && d <= endDate;
    });
  }

  const pubList = rows.map(row => {
    const pubId  = (row[pubIdCol] || '').toString();
    const orgsRaw = (row[orgCol]  || '').toString();
    const orgs = orgsRaw === 'nan' ? [] :
      orgsRaw.split(';').map(o => o.trim()).filter(Boolean);
    return { pubId, orgs };
  });

  return {
    pubList,
    dateInfo: { minDate, maxDate, totalCount, filteredCount: pubList.length },
  };
}

// ============================================================
// 7. VAMC MATCHING & COMPLIANCE CALCULATION
// ============================================================

/** Parse a station-number string that may contain comma/semicolon-separated codes. */
function parseStationNumbers(stationStr, altStr) {
  const result = new Set();
  [stationStr, altStr].forEach(s => {
    if (!s || s.trim() === '' || s.trim().toLowerCase() === 'nan') return;
    s.split(/[,;]/).forEach(p => { const t = p.trim(); if (t) result.add(t); });
  });
  return result;
}

/**
 * Extract clean search terms from a VAMC display name.
 * Splits on ';', strips "(Not in VA Dimensions)" and trailing location parentheticals.
 */
function getSearchTerms(vamcDisplay) {
  if (!vamcDisplay) return [];
  return vamcDisplay.split(';').map(part => {
    let s = part.trim();
    s = s.replace(/\s*\(Not in VA Dimensions\)\s*/gi, '');
    s = s.replace(/\s+\([^()]+\)\s*$/, '').trim();
    return s;
  }).filter(Boolean);
}

function countPubTrackerForVamc(stationStr, altStr, quarterCounts) {
  let total = 0;
  parseStationNumbers(stationStr, altStr).forEach(s => {
    total += quarterCounts[s] || 0;
  });
  return total;
}

function countDimensionsForVamc(vamcDisplay, notInDim, pubList) {
  if (notInDim) return { count: 0, matchedIds: [] };

  const terms = getSearchTerms(vamcDisplay).map(t => t.toLowerCase());
  if (!terms.length) return { count: 0, matchedIds: [] };

  const matchedIds = [];
  pubList.forEach(({ pubId, orgs }) => {
    const orgsLower = orgs.map(o => o.toLowerCase());
    const matched = terms.some(term =>
      orgsLower.some(org => org.includes(term) || term.includes(org))
    );
    if (matched) matchedIds.push(pubId);
  });
  return { count: matchedIds.length, matchedIds };
}

function calculateCompliance(ptCounts, dimPubList, quarters) {
  const rows = [];

  vamcRef.forEach(ref => {
    const vamcDisplay = ref.vamc_display || '';
    const stationNo   = (ref.station_no     || '').trim();
    const altStation  = (ref.alt_station_nos || '').trim();
    const vaFunded    = (ref.va_funded       || '').trim();
    const notInDim    = (ref.not_in_dimensions || '').trim().toLowerCase() === 'true';

    const row = {
      vamc:      vamcDisplay,
      stationNo: stationNo,
      vaFunded:  vaFunded === 'nan' ? '' : vaFunded,
    };

    // Dimensions count is the same pool for all quarters in this run
    const { count: dimCount, matchedIds } =
      countDimensionsForVamc(vamcDisplay, notInDim, dimPubList);

    quarters.forEach(({ fy, q, label }) => {
      const key    = quarterKey(fy, q);
      const qCounts = ptCounts[key] || {};
      const ptCount = countPubTrackerForVamc(stationNo, altStation, qCounts);

      let pct;
      if (notInDim)                          pct = '100%';
      else if (ptCount === 0 && dimCount === 0) pct = '100%';
      else if (dimCount === 0)                pct = '';
      else pct = `${Math.round(ptCount / dimCount * 100)}%`;

      row[`${label}_pt`]       = ptCount;
      row[`${label}_dim`]      = dimCount;
      row[`${label}_pct`]      = pct;
      row[`${label}_notInDim`] = notInDim;
    });

    rows.push(row);
  });

  // TOTAL row
  const totalRow = { vamc: 'TOTAL', stationNo: '', vaFunded: '' };
  quarters.forEach(({ label }) => {
    const ptSum  = rows.reduce((s, r) => s + (r[`${label}_pt`]  || 0), 0);
    const dimSum = rows.reduce((s, r) => s + (r[`${label}_dim`] || 0), 0);
    totalRow[`${label}_pt`]       = ptSum;
    totalRow[`${label}_dim`]      = dimSum;
    totalRow[`${label}_pct`]      = dimSum > 0 ? `${Math.round(ptSum / dimSum * 100)}%` : '';
    totalRow[`${label}_notInDim`] = false;
  });
  rows.push(totalRow);

  return rows;
}

// ============================================================
// 8. TABLE RENDERING
// ============================================================
function pctCssClass(pct, notInDim, ptCount, dimCount) {
  if (notInDim || (ptCount === 0 && dimCount === 0)) return 'table-secondary';
  if (!pct) return 'pct-undefined';  // PT > 0 but Dimensions = 0
  const val = parseInt(pct, 10);
  if (isNaN(val)) return '';
  if (val >= 100)  return 'pct-positive';  // Compliant (>=100%) - green
  return 'pct-negative';  // Non-compliant (<100%) - red
}

function escHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function renderTable(rows, quarters) {
  // Header
  let th = `<thead><tr>
    <th>VAMC</th><th>Station No.</th><th>VA Funded</th>`;
  quarters.forEach(({ label }) => {
    th += `<th class="text-end">${label}<br>PubTracker</th>`;
    th += `<th class="text-end">${label}<br>Dimensions</th>`;
    th += `<th class="text-end">${label}<br>% Entered</th>`;
  });
  th += '</tr></thead>';

  // Body
  let tb = '<tbody>';
  rows.forEach(row => {
    const isTotal = row.vamc === 'TOTAL';
    tb += `<tr class="${isTotal ? 'fw-bold table-light' : ''}">`;
    tb += `<td>${escHtml(row.vamc)}</td>`;
    tb += `<td>${escHtml(row.stationNo)}</td>`;
    tb += `<td class="text-center">${escHtml(row.vaFunded)}</td>`;
    quarters.forEach(({ label }) => {
      const pt     = row[`${label}_pt`]  ?? '';
      const dim    = row[`${label}_dim`] ?? '';
      const pct    = row[`${label}_pct`] ?? '';
      const notIn  = row[`${label}_notInDim`];
      const cls    = pctCssClass(pct, notIn, pt, dim);
      const pctVal = pct && !notIn && !(pt === 0 && dim === 0) ? parseInt(pct, 10) : null;
      const pctDisplay = pctVal !== null ? (pctVal >= 100 ? '+' : '-') + pct : pct;
      tb += `<td class="text-end">${pt}</td>`;
      tb += `<td class="text-end">${dim}</td>`;
      tb += `<td class="text-end ${cls}">${pctDisplay}</td>`;
    });
    tb += '</tr>';
  });
  tb += '</tbody>';

  document.getElementById('resultsTable').innerHTML =
    `<table class="table table-sm table-bordered table-hover mb-0">${th}${tb}</table>`;
}

// ============================================================
// 9. OUTPUT GENERATION
// ============================================================
function generateCSV(rows, quarters) {
  const headers = ['VAMC', 'Station No.', 'VA Funded'];
  quarters.forEach(({ label }) => {
    headers.push(`${label} PubTracker Count`);
    headers.push(`${label} Dimensions Count`);
    headers.push(`${label} % Entered`);
  });

  const csvRows = [headers];
  rows.forEach(row => {
    const r = [row.vamc, row.stationNo, row.vaFunded];
    quarters.forEach(({ label }) => {
      r.push(row[`${label}_pt`]  ?? '');
      r.push(row[`${label}_dim`] ?? '');
      const pct = row[`${label}_pct`] ?? '';
      const notIn = row[`${label}_notInDim`];
      const pt = row[`${label}_pt`] ?? 0;
      const dim = row[`${label}_dim`] ?? 0;
      const pctVal = pct && !notIn && !(pt === 0 && dim === 0) ? parseInt(pct, 10) : null;
      const pctDisplay = pctVal !== null ? (pctVal >= 100 ? '+' : '-') + pct : pct;
      r.push(pctDisplay);
    });
    csvRows.push(r);
  });

  return csvRows.map(r =>
    r.map(v => {
      const s = String(v);
      return /[,"\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    }).join(',')
  ).join('\r\n');
}

function generateReport(rows, quarters) {
  const sep  = '='.repeat(70);
  const dash = '-'.repeat(40);
  const lines = [sep, 'PUBTRACKER COMPLIANCE REPORT', sep];
  const dataRows = rows.filter(r => r.vamc !== 'TOTAL');
  const totalRow = rows.find(r => r.vamc === 'TOTAL');

  quarters.forEach(({ label }) => {
    lines.push('', `${label} SUMMARY`, dash);

    if (totalRow) {
      const totalPct = totalRow[`${label}_pct`] || '';
      const totalPtVal = totalRow[`${label}_pt`] || 0;
      const totalDimVal = totalRow[`${label}_dim`] || 0;
      const totalPctNum = totalPct && !(totalPtVal === 0 && totalDimVal === 0) ? parseInt(totalPct, 10) : null;
      const totalPctDisplay = totalPctNum !== null ? (totalPctNum >= 100 ? '+' : '-') + totalPct : totalPct;
      lines.push(`  Total PubTracker submissions : ${totalRow[`${label}_pt`]}`);
      lines.push(`  Total Dimensions publications: ${totalRow[`${label}_dim`]}`);
      lines.push(`  Overall % Entered            : ${totalPctDisplay}`);
    }

    // Top 10 by PubTracker count
    lines.push('\nTop 10 VAMCs by PubTracker submissions:');
    [...dataRows]
      .sort((a, b) => (b[`${label}_pt`] || 0) - (a[`${label}_pt`] || 0))
      .slice(0, 10)
      .forEach(row => {
        const name = row.vamc.slice(0, 52).padEnd(52);
        const pt   = String(row[`${label}_pt`] || 0).padStart(5);
        const dim  = String(row[`${label}_dim`] || 0).padStart(5);
        const pctRaw = row[`${label}_pct`] || '';
        const notIn = row[`${label}_notInDim`];
        const ptVal = row[`${label}_pt`] || 0;
        const dimVal = row[`${label}_dim`] || 0;
        const pctNum = pctRaw && !notIn && !(ptVal === 0 && dimVal === 0) ? parseInt(pctRaw, 10) : null;
        const pctDisplay = pctNum !== null ? (pctNum >= 100 ? '+' : '-') + pctRaw : pctRaw;
        const pct  = String(pctDisplay).padStart(7);
        lines.push(`  ${name} PT:${pt}  DIM:${dim}  ${pct}`);
      });

    // VAMCs with zero PT submissions but Dimensions data
    const zeroPT = dataRows.filter(r =>
      (r[`${label}_pt`] || 0) === 0 && (r[`${label}_dim`] || 0) > 0
    );
    if (zeroPT.length) {
      lines.push('\nVAMCs with 0 PubTracker submissions but Dimensions data exists:');
      zeroPT.forEach(r =>
        lines.push(`  ${r.vamc.slice(0, 60)}  (DIM: ${r[`${label}_dim`]})`)
      );
    }

    // Data quality: PT > 1.5× Dimensions
    const high = dataRows.filter(r =>
      (r[`${label}_pt`] || 0) > (r[`${label}_dim`] || 0) * 1.5 && (r[`${label}_dim`] || 0) > 0
    );
    if (high.length) {
      lines.push('\nData quality – PubTracker > 1.5× Dimensions (review recommended):');
      high.forEach(r =>
        lines.push(`  ${r.vamc.slice(0, 52)}  PT:${r[`${label}_pt`]}  DIM:${r[`${label}_dim`]}  ${r[`${label}_pct`]}`)
      );
    }
  });

  lines.push('', sep);
  return lines.join('\n');
}

// ============================================================
// 10. DOWNLOAD HELPER
// ============================================================
function downloadText(content, filename, mime = 'text/plain') {
  const blob = new Blob([content], { type: mime });
  const url  = URL.createObjectURL(blob);
  const a    = Object.assign(document.createElement('a'), { href: url, download: filename });
  a.click();
  URL.revokeObjectURL(url);
}

// ============================================================
// 11. UI HELPERS
// ============================================================
function setStatus(msg, type = 'info') {
  const el = document.getElementById('statusMsg');
  el.className = `alert alert-${type} mb-3`;
  el.textContent = msg;
  el.classList.remove('d-none');
}

function hideStatus() {
  document.getElementById('statusMsg').classList.add('d-none');
}

function checkReadyToGenerate() {
  document.getElementById('generateBtn').disabled =
    !(ptRaw && dimRawText && availableQuarters.length);
}

function renderQuarterSelector(quarters) {
  const container = document.getElementById('quarterSelector');
  if (!quarters.length) { container.classList.add('d-none'); return; }

  document.getElementById('quarterChecks').innerHTML = quarters.map(({ fy, q, label }) =>
    `<div class="form-check form-check-inline">
       <input class="form-check-input quarter-check" type="checkbox"
              id="q_${fy}_${q}" value="${fy}-${q}" checked />
       <label class="form-check-label fw-semibold" for="q_${fy}_${q}">${label}</label>
     </div>`
  ).join('');

  container.classList.remove('d-none');
}

function getSelectedQuarters() {
  return Array.from(document.querySelectorAll('.quarter-check:checked')).map(cb => {
    const [fy, q] = cb.value.split('-').map(Number);
    return { fy, q, label: getQuarterLabel(fy, q) };
  });
}

function renderMetrics(rows, quarters) {
  const totalRow = rows.find(r => r.vamc === 'TOTAL');
  if (!totalRow) return;
  document.getElementById('metricsRow').innerHTML = quarters.map(({ label }) => `
    <div class="col-sm-6 col-lg-4">
      <div class="card border-primary shadow-sm">
        <div class="card-header bg-primary text-white text-center fw-bold py-1">${escHtml(label)}</div>
        <div class="card-body p-2">
          <div class="row g-0 text-center">
            <div class="col-4">
              <div class="small text-muted">PubTracker</div>
              <div class="fs-5 fw-bold">${totalRow[`${label}_pt`]}</div>
            </div>
            <div class="col-4 border-start border-end">
              <div class="small text-muted">Dimensions</div>
              <div class="fs-5 fw-bold">${totalRow[`${label}_dim`]}</div>
            </div>
            <div class="col-4">
              <div class="small text-muted">% Entered</div>
              <div class="fs-5 fw-bold">${totalRow[`${label}_pct`] || '—'}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  `).join('');
}

// ============================================================
// 12. MAIN GENERATE HANDLER
// ============================================================
function runGenerate() {
  selectedQuarters = getSelectedQuarters();
  if (!selectedQuarters.length) {
    setStatus('Please select at least one quarter.', 'warning');
    return;
  }

  setStatus('Processing — please wait…', 'info');

  // Use setTimeout to allow the browser to render the status message first
  setTimeout(() => {
    try {
      const incPres = document.getElementById('inclPresentation').checked;

      // Re-parse PubTracker (handles checkbox toggle)
      const ptResult = parsePubTracker(ptRaw.text, incPres);

      // Filter ptCounts to selected quarters only
      const ptCounts = {};
      selectedQuarters.forEach(({ fy, q }) => {
        const key = quarterKey(fy, q);
        if (ptResult.counts[key]) ptCounts[key] = ptResult.counts[key];
      });

      // Derive Dimensions date range from selected quarters
      const ranges   = selectedQuarters.map(({ fy, q }) => getQuarterDateRange(fy, q));
      const dimStart = new Date(Math.min(...ranges.map(r => r.start)));
      const dimEnd   = new Date(Math.max(...ranges.map(r => r.end)));

      const { pubList, dateInfo } = parseDimensions(dimRawText, dimStart, dimEnd);

      // Calculate
      resultRows = calculateCompliance(ptCounts, pubList, selectedQuarters);

      // Render
      renderMetrics(resultRows, selectedQuarters);
      renderTable(resultRows, selectedQuarters);

      // Dimensions info banner
      const dimInfoEl = document.getElementById('dimDateInfo');
      let dimMsg = `Dimensions: <strong>${dateInfo.filteredCount}</strong> of <strong>${dateInfo.totalCount}</strong> records used after date filtering`;
      if (dateInfo.minDate && dateInfo.maxDate) {
        dimMsg += ` · file date range: ${dateInfo.minDate.toLocaleDateString()} – ${dateInfo.maxDate.toLocaleDateString()}`;
      }
      dimInfoEl.innerHTML = dimMsg;
      dimInfoEl.classList.remove('d-none');

      document.getElementById('resultsSection').classList.remove('d-none');
      document.getElementById('downloadButtons').classList.remove('d-none');
      hideStatus();

      document.getElementById('resultsSection').scrollIntoView({ behavior: 'smooth' });

    } catch (err) {
      setStatus(`Error: ${err.message}`, 'danger');
      console.error(err);
    }
  }, 50);
}

// ============================================================
// 13. INIT & EVENT WIRING
// ============================================================
document.addEventListener('DOMContentLoaded', async () => {

  // Add CSS for partial-match % color (not a Bootstrap built-in)
  const style = document.createElement('style');
  style.textContent = `
    .pct-partial { background-color: #d4edda !important; }
    .pct-undefined { background-color: #fff3cd !important; }
  `;
  document.head.appendChild(style);

  // Load VAMC reference
  try {
    await loadVamcRef();
  } catch (e) {
    setStatus(`Failed to load VAMC reference data: ${e.message}. If running locally, use run_web.bat instead of opening the HTML file directly.`, 'danger');
    return;
  }

  // ── PubTracker upload ──────────────────────────────────────────────────
  document.getElementById('ptFile').addEventListener('change', async e => {
    const file = e.target.files[0];
    if (!file) return;
    const text = await file.text();
    try {
      const incPres = document.getElementById('inclPresentation').checked;
      const result  = parsePubTracker(text, incPres);
      ptRaw = { text, result };
      availableQuarters = result.quartersFound;
      renderQuarterSelector(availableQuarters);

      const excParts = Object.entries(result.excluded)
        .map(([k, v]) => `${v} "${k}"`).join(', ');
      const excNote = excParts
        ? ` <span class="text-warning">(excluded: ${escHtml(excParts)})</span>` : '';

      document.getElementById('ptStatus').innerHTML =
        `<span class="text-success fw-semibold">✓ ${escHtml(file.name)}</span> — ` +
        `<strong>${result.totalKept}</strong> publication${result.totalKept !== 1 ? 's' : ''} · ` +
        `${availableQuarters.map(q => q.label).join(', ')} detected` + excNote;

      checkReadyToGenerate();
    } catch (err) {
      document.getElementById('ptStatus').innerHTML =
        `<span class="text-danger">⚠ ${escHtml(err.message)}</span>`;
    }
  });

  // ── Dimensions upload ──────────────────────────────────────────────────
  document.getElementById('dimFile').addEventListener('change', async e => {
    const file = e.target.files[0];
    if (!file) return;
    dimRawText = await file.text();
    document.getElementById('dimStatus').innerHTML =
      `<span class="text-success fw-semibold">✓ ${escHtml(file.name)}</span> — ready`;
    checkReadyToGenerate();
  });

  // ── Generate ───────────────────────────────────────────────────────────
  document.getElementById('generateBtn').addEventListener('click', runGenerate);

  // ── Downloads ──────────────────────────────────────────────────────────
  document.getElementById('downloadCSV').addEventListener('click', () => {
    if (!resultRows.length) return;
    const stem = selectedQuarters.map(q => q.label.replace(' ', '')).join('_');
    downloadText(generateCSV(resultRows, selectedQuarters),
      `pubtracker_compliance_${stem}.csv`, 'text/csv;charset=utf-8;');
  });

  document.getElementById('downloadReport').addEventListener('click', () => {
    if (!resultRows.length) return;
    const stem = selectedQuarters.map(q => q.label.replace(' ', '')).join('_');
    downloadText(generateReport(resultRows, selectedQuarters),
      `compliance_report_${stem}.txt`);
  });
});
