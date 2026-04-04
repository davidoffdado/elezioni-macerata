/* =====================================================
   MACERATA ELEZIONI — main.js
   Carica GeoJSON dal repo + dati da Google Sheets CSV
   Supporta N candidati; l'utente sceglie il duello
   ===================================================== */

// ─── CONFIGURAZIONE ───────────────────────────────────
const PUBLISHED_ID = "2PACX-1vSXkyX7vkmpegphAnR6HxPimNMoLBtH3rixk7Lyn3jZPHWH468lUxpbXBZQVC3zr3HduLNMVgxDLcVs";
const GEOJSON_URL  = "geojson/edifici_colorabili_voti.geojson";

// Sostituisci i GID con i numeri che trovi nell'URL di ogni tab
const SHEET_GIDS = {
  meta:      "0",
  voti:      "1712458015",
  affluenza: "683200541",
};

const SHEETS = {
  meta:      sheetCsvUrl(SHEET_GIDS.meta),
  voti:      sheetCsvUrl(SHEET_GIDS.voti),
  affluenza: sheetCsvUrl(SHEET_GIDS.affluenza),
};

// ─── STATO ────────────────────────────────────────────
let candidates = [];   // [{id:"1", nome:"...", colore:"..."}, ...]
let selA = 0;          // indice in candidates per il lato A del duello
let selB = 1;          // indice in candidates per il lato B del duello
let selSingle = 0;     // indice in candidates per la modalità singolo
let currentMode = "duello";
let map, geojsonLayer;
let _geojson, _votiMap, _affluenzaMap;

// Highlight sezione
let _selectedSection = null;
let _hoveredSection  = null;
let _hoverTimeout    = null;
let _sezioneIndex    = {};   // sezione → [layer, ...]

// Tooltip globale unico
let _tooltip          = null;
let _tooltipPermanent = false;  // true se mostrato da click (mobile), false se da hover
let _layerJustClicked = false;  // blocca il map click immediatamente dopo un layer click

// ─── UTILS ────────────────────────────────────────────
function sheetCsvUrl(gid) {
  return `https://docs.google.com/spreadsheets/d/e/${PUBLISHED_ID}/pub?output=csv&gid=${gid}`;
}

async function fetchCsv(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Errore fetch: ${url}`);
  const text = await res.text();
  return parseCsv(text);
}

function parseCsv(text) {
  const lines = text.trim().split("\n");
  const headers = lines[0].split(",").map(h => h.replace(/^"|"$/g, "").trim());
  return lines.slice(1).map(line => {
    const cols = line.match(/(".*?"|[^,]+)(?=,|$)/g) || [];
    const row = {};
    headers.forEach((h, i) => {
      let val = (cols[i] || "").replace(/^"|"$/g, "").trim();
      // normalizza decimali italiani: "65,42" → "65.42"
      val = val.replace(/^(-?\d+),(\d+)$/, "$1.$2");
      row[h] = val;
    });
    return row;
  });
}

// Colori di fallback per candidati senza colore in meta
const PALETTE_DEFAULT = [
  "#c0392b","#2563a8","#27ae60","#e67e22","#8e44ad",
  "#16a085","#d35400","#2980b9","#c0392b","#7f8c8d",
];

function hexToRgb(hex) {
  const m = hex.replace("#","").match(/.{2}/g);
  return { r: parseInt(m[0],16), g: parseInt(m[1],16), b: parseInt(m[2],16) };
}

function lerp(t, colA, colB) {
  const a = hexToRgb(colA), b = hexToRgb(colB);
  return `rgb(${Math.round(a.r+(b.r-a.r)*t)},${Math.round(a.g+(b.g-a.g)*t)},${Math.round(a.b+(b.b-a.b)*t)})`;
}

function colorDuello(diff, maxAbs, colA, colB) {
  if (maxAbs === 0 || isNaN(diff)) return "#cccccc";
  const t = diff / maxAbs;
  if (t > 0) return lerp( t, "#f5f5f5", colA);
  if (t < 0) return lerp(-t, "#f5f5f5", colB);
  return "#f5f5f5";
}

function colorAffluenza(val) {
  if (val == null || isNaN(val)) return "#cccccc";
  const t = Math.max(0, Math.min(1, val));
  if (t < 0.5) return lerp(t * 2, "#d73027", "#fee08b");
  return lerp((t - 0.5) * 2, "#fee08b", "#1a9850");
}

// share: 0–1, quota del candidato sul totale voti della sezione
function colorSingolo(share, colore) {
  if (isNaN(share)) return "#cccccc";
  return lerp(Math.max(0, Math.min(1, share)), "#f5f5f5", colore);
}

// ─── PARSING META — candidati ─────────────────────────
function parseCandidates(metaRows) {
  const map = {};
  metaRows.forEach(r => { map[r.chiave] = r.valore; });

  const result = [];
  let i = 1;
  while (map[`candidato_${i}_nome`]) {
    result.push({
      id:     String(i),
      nome:   map[`candidato_${i}_nome`],
      colore: map[`candidato_${i}_colore`] || PALETTE_DEFAULT[(i-1) % PALETTE_DEFAULT.length],
    });
    i++;
  }
  return result;
}

// ─── MAPPA ────────────────────────────────────────────
function initMap() {
  map = L.map("map", { zoomControl: true });
  L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
    attribution: '&copy; <a href="https://carto.com/">CartoDB</a>',
    subdomains: "abcd", maxZoom: 19
  }).addTo(map);

  // Click su spazio vuoto: chiudi tutto — su mobile gestiamo la chiusura solo con × o stessa sezione
  map.on("click", () => {
    if (window.matchMedia("(max-width: 640px)").matches) return;
    if (!_layerJustClicked) closeInfoPanel();
  });

  // Pulsante × del panel
  document.getElementById("map-info-close")?.addEventListener("click", closeInfoPanel);
}

// ─── PANEL INFO SEZIONE ───────────────────────────────
function updateInfoPanel(sez) {
  const panel   = document.getElementById("map-info-panel");
  const content = document.getElementById("map-info-content");
  if (!panel || !content) return;

  const v       = _votiMap[sez]      || {};
  const a       = _affluenzaMap[sez] || {};
  const cA      = candidates[selA];
  const cB      = candidates[selB];
  const cSingle = candidates[selSingle];
  const aff     = a.affluenza ? parseFloat(a.affluenza).toFixed(1) + "%" : "—";

  let rows = "";
  if (currentMode === "duello" && cA && cB) {
    const vA     = parseFloat(v[`voti_${cA.id}`]) || 0;
    const vB     = parseFloat(v[`voti_${cB.id}`]) || 0;
    const totale = candidates.reduce((sum, c) => sum + (parseFloat(v[`voti_${c.id}`]) || 0), 0);
    const pA     = totale > 0 ? ((vA / totale) * 100).toFixed(1) + "%" : "—";
    const pB     = totale > 0 ? ((vB / totale) * 100).toFixed(1) + "%" : "—";
    rows += `<div class="info-panel-row"><span class="dot" style="background:${cA.colore}"></span><span class="label">${cA.nome}</span><span class="value" style="color:${cA.colore}">${pA}</span></div>`;
    rows += `<div class="info-panel-row"><span class="dot" style="background:${cB.colore}"></span><span class="label">${cB.nome}</span><span class="value" style="color:${cB.colore}">${pB}</span></div>`;
  } else if (currentMode === "singolo" && cSingle) {
    const vc     = parseFloat(v[`voti_${cSingle.id}`]) || 0;
    const totale = candidates.reduce((sum, c) => sum + (parseFloat(v[`voti_${c.id}`]) || 0), 0);
    const perc   = totale > 0 ? ((vc / totale) * 100).toFixed(1) + "%" : "—";
    rows += `<div class="info-panel-row"><span class="dot" style="background:${cSingle.colore}"></span><span class="label">${cSingle.nome}</span><span class="value" style="color:${cSingle.colore}">${perc}</span></div>`;
  }
  rows += `<div class="info-panel-row"><span class="label" style="color:var(--color-muted)">Affluenza</span><span class="value">${aff}</span></div>`;

  content.innerHTML = `<div class="info-panel-title">Sezione ${sez}</div>${rows}`;
  panel.style.display = "block";
  panel.classList.add("is-open");
}

function closeInfoPanel() {
  const panel = document.getElementById("map-info-panel");
  if (panel) { panel.classList.remove("is-open"); panel.style.display = "none"; }
  _tooltipPermanent = false;
  if (_tooltip) _tooltip.remove();
  if (_selectedSection) { unhighlightSection(_selectedSection); _selectedSection = null; }
}

// ─── HIGHLIGHT SEZIONE ────────────────────────────────
function highlightSection(sez) {
  (_sezioneIndex[sez] || []).forEach(l => {
    l.setStyle({ color: "#ffffff", weight: 3, fillOpacity: 0.95 });
    l.bringToFront();
  });
}

function unhighlightSection(sez) {
  (_sezioneIndex[sez] || []).forEach(l => geojsonLayer.resetStyle(l));
}

function toggleSection(sez) {
  if (_selectedSection === sez) {
    _selectedSection = null;
    unhighlightSection(sez);
  } else {
    if (_selectedSection) unhighlightSection(_selectedSection);
    _selectedSection = sez;
    highlightSection(sez);
  }
}

// ─── LAYER ────────────────────────────────────────────
function renderLayer() {
  if (!_geojson) return;
  if (geojsonLayer) geojsonLayer.remove();

  // reset stato highlight al cambio di layer
  _selectedSection = null;
  _hoveredSection  = null;
  clearTimeout(_hoverTimeout);
  _sezioneIndex = {};

  // ricrea tooltip globale e nascondi panel
  if (_tooltip) _tooltip.remove();
  _tooltip          = L.tooltip({ sticky: false, opacity: 0.92 });
  _tooltipPermanent = false;
  const _panel = document.getElementById("map-info-panel");
  if (_panel) { _panel.classList.remove("is-open"); _panel.style.display = "none"; }

  const cA      = candidates[selA];
  const cB      = candidates[selB];
  const cSingle = candidates[selSingle];

  // calcola max diff per normalizzazione
  let maxAbs = 0;
  if (currentMode === "duello" && cA && cB) {
    _geojson.features.forEach(f => {
      const v = _votiMap[String(f.properties.sezione)] || {};
      const diff = (parseFloat(v[`voti_${cA.id}`]) || 0) - (parseFloat(v[`voti_${cB.id}`]) || 0);
      maxAbs = Math.max(maxAbs, Math.abs(diff));
    });
  }

  geojsonLayer = L.geoJSON(_geojson, {
    style: feature => {
      const sez = String(feature.properties.sezione);
      const v   = _votiMap[sez] || {};
      let fillColor = "#cccccc";

      if (currentMode === "duello" && cA && cB) {
        const diff = (parseFloat(v[`voti_${cA.id}`]) || 0) - (parseFloat(v[`voti_${cB.id}`]) || 0);
        fillColor = colorDuello(diff, maxAbs, cA.colore, cB.colore);
      } else if (currentMode === "singolo" && cSingle) {
        const voti_c = parseFloat(v[`voti_${cSingle.id}`]) || 0;
        const totale = candidates.reduce((sum, c) => sum + (parseFloat(v[`voti_${c.id}`]) || 0), 0);
        fillColor = colorSingolo(totale > 0 ? voti_c / totale : 0, cSingle.colore);
      } else if (currentMode === "affluenza") {
        const a = _affluenzaMap[sez] || {};
        fillColor = colorAffluenza(parseFloat(a.affluenza) / 100);
      }

      return { fillColor, color: "#888", weight: 0.2, fillOpacity: 0.82 };
    },
    onEachFeature: (feature, layer) => {
      const sez = String(feature.properties.sezione);
      const v   = _votiMap[sez]      || {};
      const a   = _affluenzaMap[sez] || {};
      const aff = a.affluenza ? parseFloat(a.affluenza).toFixed(1) + "%" : "—";

      // Costruisce indice sezione → layers
      if (!_sezioneIndex[sez]) _sezioneIndex[sez] = [];
      _sezioneIndex[sez].push(layer);

      let votiHtml = "";
      if (currentMode === "duello" && cA && cB) {
        const vA     = parseFloat(v[`voti_${cA.id}`]) || 0;
        const vB     = parseFloat(v[`voti_${cB.id}`]) || 0;
        const totale = candidates.reduce((sum, c) => sum + (parseFloat(v[`voti_${c.id}`]) || 0), 0);
        const pA     = totale > 0 ? ((vA/totale)*100).toFixed(1) + "%" : "—";
        const pB     = totale > 0 ? ((vB/totale)*100).toFixed(1) + "%" : "—";
        votiHtml = `
          <span style="color:${cA.colore}">&#9632; ${cA.nome}: ${pA}</span><br>
          <span style="color:${cB.colore}">&#9632; ${cB.nome}: ${pB}</span><br>`;
      } else if (currentMode === "singolo" && cSingle) {
        const voti_c = parseFloat(v[`voti_${cSingle.id}`]) || 0;
        const totale = candidates.reduce((sum, c) => sum + (parseFloat(v[`voti_${c.id}`]) || 0), 0);
        const perc   = totale > 0 ? ((voti_c / totale) * 100).toFixed(1) + "%" : "—";
        votiHtml = `<span style="color:${cSingle.colore}">&#9632; ${cSingle.nome}: ${perc}</span><br>`;
      }

      const tooltipContent = () => `
        <strong>Sezione ${sez}</strong><br>
        ${votiHtml}
        Affluenza: ${aff}
      `;

      // ── Desktop: hover mostra/nasconde tooltip ──
      layer.on("mouseover", (e) => {
        if (_tooltipPermanent) return;
        _tooltip.setLatLng(e.latlng).setContent(tooltipContent()).addTo(map);
        clearTimeout(_hoverTimeout);
        if (_hoveredSection !== sez) {
          if (_hoveredSection && _hoveredSection !== _selectedSection) {
            unhighlightSection(_hoveredSection);
          }
          _hoveredSection = sez;
        }
        if (sez !== _selectedSection) highlightSection(sez);
      });

      layer.on("mousemove", (e) => {
        if (_tooltipPermanent) return;
        _tooltip.setLatLng(e.latlng);
      });

      layer.on("mouseout", () => {
        if (_tooltipPermanent) return;
        _tooltip.remove();
        _hoverTimeout = setTimeout(() => {
          if (_hoveredSection === sez && sez !== _selectedSection) {
            unhighlightSection(sez);
            _hoveredSection = null;
          }
        }, 80);
      });

      // ── Click/tap: panel info + tooltip fisso (desktop) ──
      layer.on("click", (e) => {
        L.DomEvent.stopPropagation(e);
        _layerJustClicked = true;
        setTimeout(() => { _layerJustClicked = false; }, 100);
        const wasSameSection = _selectedSection === sez;
        toggleSection(sez);
        if (wasSameSection) {
          _tooltipPermanent = false;
          _tooltip.remove();
          closeInfoPanel();
        } else {
          updateInfoPanel(sez);
          if (!L.Browser.touch) {
            _tooltipPermanent = true;
            _tooltip.setLatLng(e.latlng).setContent(tooltipContent()).addTo(map);
          }
        }
      });
    }
  }).addTo(map);

  map.fitBounds(geojsonLayer.getBounds(), { padding: [20, 20] });
  updateLegend();
}

// ─── LEGENDA ──────────────────────────────────────────
function updateLegend() {
  const cA      = candidates[selA];
  const cB      = candidates[selB];
  const cSingle = candidates[selSingle];

  // Duello
  const legA    = document.getElementById("leg-nome-a");
  const legB    = document.getElementById("leg-nome-b");
  const legGrad = document.querySelector("#legend-duello .legend-gradient");
  if (legA && cA) { legA.textContent = cA.nome; legA.style.color = cA.colore; }
  if (legB && cB) { legB.textContent = cB.nome; legB.style.color = cB.colore; }
  if (legGrad && cA && cB) {
    legGrad.style.background = `linear-gradient(to right, ${cB.colore}, #f5f5f5, ${cA.colore})`;
  }

  // Singolo
  const legSingolo     = document.getElementById("legend-singolo");
  const legSingoloGrad = document.querySelector("#legend-singolo .legend-gradient");
  const legSingoloNome = document.getElementById("leg-nome-single");
  if (legSingolo && cSingle) {
    if (legSingoloGrad) legSingoloGrad.style.background = `linear-gradient(to right, #f5f5f5, ${cSingle.colore})`;
    if (legSingoloNome) legSingoloNome.textContent = cSingle.nome;
  }

  const ld = document.getElementById("legend-duello");
  const ls = document.getElementById("legend-singolo");
  const la = document.getElementById("legend-affluenza");
  if (ld) ld.style.display = currentMode === "duello"    ? "flex" : "none";
  if (ls) ls.style.display = currentMode === "singolo"   ? "flex" : "none";
  if (la) la.style.display = currentMode === "affluenza" ? "flex" : "none";
}

// ─── STATISTICHE ──────────────────────────────────────
function updateStats() {
  const cA = candidates[selA];
  const cB = candidates[selB];

  let totA = 0, totB = 0, totTutti = 0, totAff = 0, countAff = 0;
  Object.values(_votiMap).forEach(v => {
    if (cA) totA += parseFloat(v[`voti_${cA.id}`]) || 0;
    if (cB) totB += parseFloat(v[`voti_${cB.id}`]) || 0;
    candidates.forEach(c => { totTutti += parseFloat(v[`voti_${c.id}`]) || 0; });
  });
  Object.values(_affluenzaMap).forEach(a => {
    const val = parseFloat(a.affluenza);
    if (!isNaN(val)) { totAff += val; countAff++; }
  });

  const pA  = totTutti > 0 ? ((totA/totTutti)*100).toFixed(1) + "%" : "—";
  const pB  = totTutti > 0 ? ((totB/totTutti)*100).toFixed(1) + "%" : "—";
  const avg = countAff > 0 ? (totAff/countAff).toFixed(1) + "%" : "—";

  const el = id => document.getElementById(id);
  if (el("stat-nome-a") && cA) {
    el("stat-nome-a").textContent = cA.nome;
    el("stat-nome-a").style.borderBottom = `3px solid ${cA.colore}`;
  }
  if (el("stat-nome-b") && cB) {
    el("stat-nome-b").textContent = cB.nome;
    el("stat-nome-b").style.borderBottom = `3px solid ${cB.colore}`;
  }
  if (el("stat-perc-a") && cA) {
    el("stat-perc-a").textContent = pA;
    el("stat-perc-a").style.color = cA.colore;
  }
  if (el("stat-perc-b") && cB) {
    el("stat-perc-b").textContent = pB;
    el("stat-perc-b").style.color = cB.colore;
  }
  if (el("stat-affluenza")) el("stat-affluenza").textContent = avg;
}

// ─── SELETTORE CANDIDATI ──────────────────────────────
function populateSelect(el, selectedIdx) {
  if (!el) return;
  el.innerHTML = "";
  candidates.forEach((c, i) => {
    const opt = document.createElement("option");
    opt.value = i;
    opt.textContent = c.nome;
    el.appendChild(opt);
  });
  el.value = selectedIdx;
}

function buildSelectors() {
  const selAEl      = document.getElementById("select-a");
  const selBEl      = document.getElementById("select-b");
  const selSingleEl = document.getElementById("select-single");

  populateSelect(selAEl,      selA);
  populateSelect(selBEl,      selB);
  populateSelect(selSingleEl, selSingle);

  selAEl?.addEventListener("change", () => {
    selA = parseInt(selAEl.value);
    if (selA === selB) { selB = selA === 0 ? 1 : 0; selBEl.value = selB; }
    renderLayer(); updateStats(); updateLegend();
  });

  selBEl?.addEventListener("change", () => {
    selB = parseInt(selBEl.value);
    if (selA === selB) { selA = selB === 0 ? 1 : 0; selAEl.value = selA; }
    renderLayer(); updateStats(); updateLegend();
  });

  selSingleEl?.addEventListener("change", () => {
    selSingle = parseInt(selSingleEl.value);
    renderLayer(); updateLegend();
  });
}

// ─── INIT ─────────────────────────────────────────────
async function init() {
  initMap();

  try {
    // Meta
    try {
      const metaRows = await fetchCsv(SHEETS.meta);
      candidates = parseCandidates(metaRows);
    } catch (e) {
      console.warn("Sheet 'meta' non disponibile, uso defaults.", e);
    }
    if (candidates.length < 2) {
      candidates = [
        { id: "1", nome: "Candidato 1", colore: PALETTE_DEFAULT[0] },
        { id: "2", nome: "Candidato 2", colore: PALETTE_DEFAULT[1] },
      ];
    }

    // Voti, affluenza e GeoJSON in parallelo
    const [votiRows, affluenzaRows, geojson] = await Promise.all([
      fetchCsv(SHEETS.voti),
      fetchCsv(SHEETS.affluenza),
      fetch(GEOJSON_URL).then(r => r.json()),
    ]);

    _votiMap = {};
    votiRows.forEach(r => { _votiMap[String(r.sezione)] = r; });

    _affluenzaMap = {};
    affluenzaRows.forEach(r => { _affluenzaMap[String(r.sezione)] = r; });

    _geojson = geojson;

    buildSelectors();
    renderLayer();
    updateStats();

    // Pulsanti modalità
    document.querySelectorAll("[data-mode]").forEach(btn => {
      btn.addEventListener("click", () => {
        currentMode = btn.dataset.mode;
        document.querySelectorAll("[data-mode]").forEach(b => b.className = "map-btn");
        btn.classList.add("active");

        // Mostra il selettore pertinente alla modalità attiva
        const selDuello  = document.getElementById("duello-selector");
        const selSingolo = document.getElementById("singolo-selector");
        if (selDuello)  selDuello.style.display  = currentMode === "duello"  ? "flex" : "none";
        if (selSingolo) selSingolo.style.display = currentMode === "singolo" ? "flex" : "none";

        renderLayer();
        updateLegend();
      });
    });

    // Stato iniziale pulsanti
    document.querySelector('[data-mode="duello"]')?.classList.add("active");

  } catch (err) {
    console.error("Errore nel caricamento dati:", err);
    const errEl = document.getElementById("map-error");
    if (errEl) errEl.style.display = "block";
  }
}

document.addEventListener("DOMContentLoaded", init);
