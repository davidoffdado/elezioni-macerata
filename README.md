# Elezioni Macerata

Portale di analisi geografica dei risultati elettorali delle elezioni comunali di Macerata, con mappa interattiva a livello di edificio.

**Sito:** [davidoffdado.github.io/elezioni-macerata](https://davidoffdado.github.io/elezioni-macerata/)

---

## Cosa mostra

- **Mappa per edificio** — ogni edificio è colorato in base al risultato della propria sezione elettorale. Modalità: duello tra due candidati, candidato singolo, affluenza
- **Analisi per sezione** — grafici e tabella con voti e affluenza per ciascuna sezione
- **Analisi per candidato** — risultato complessivo ordinato per voti e ranking delle sezioni migliori/peggiori per ciascun candidato

---

## Struttura del progetto

```
docs/               → sito web (servito da GitHub Pages)
  index.html        → mappa interattiva
  analisi.html      → analisi per sezione
  analisi-candidato.html → analisi per candidato
  metodologia.html  → descrizione del processo
  dati.html         → fonti e download
  assets/
    style.css
    main.js         → logica mappa (Leaflet + fetch Google Sheets)
  geojson/
    edifici_colorabili_voti.geojson  → edifici OSM con sezione assegnata
    voronoi_per_sezione.geojson      → poligoni di Voronoi per sezione

claude/             → pipeline Python per generare i GeoJSON
  voronoi.py        → crea i poligoni di Voronoi dai seggi geocodificati
  creazione_file_voti.py  → join edifici ↔ sezioni
  creazione_mappa_voti.py → genera mappa Folium (output locale)
  pipeline.py       → esegue i tre script in sequenza
  final_data.xlsx   → coordinate seggi geocodificati (input pipeline)

dati/               → dati grezzi e geocodifica
  geocoder.py       → geocodifica indirizzi via Nominatim
  indirizzo-seggi.xlsx  → viario elettorale originale
  indirizzi_geocodificati.xlsx → output geocoder
```

---

## Flusso dati

```
Viario elettorale (Comune)
        ↓ geocoder.py
Coordinate seggi (final_data.xlsx)
        ↓ voronoi.py
Poligoni di Voronoi per sezione
        ↓ creazione_file_voti.py
Edifici OSM + sezione assegnata (GeoJSON)
        ↓ commit su GitHub
Sito web (GitHub Pages)
        ↑
Google Sheets (voti + affluenza, aggiornamento manuale)
```

Il sito legge i dati elettorali **in tempo reale** da Google Sheets via CSV pubblico. Per aggiornare voti o affluenza è sufficiente modificare il foglio — nessun rebuild necessario.

I GeoJSON (edifici, Voronoi) cambiano solo se cambiano i seggi o si rigenera la pipeline; in quel caso occorre rieseguire `pipeline.py` e fare un nuovo commit.

---

## Aggiornare i dati elettorali

1. Apri il [Google Sheet](https://docs.google.com/spreadsheets/d/1cKxbqWYE_aMCNVyr3I1rBObcTmHIcNnJcSeMZxmCrkY/edit)
2. Modifica le tab `voti` e/o `affluenza`
3. Il sito si aggiorna al prossimo caricamento della pagina

Struttura del foglio:

| Tab | Colonne |
|-----|---------|
| `meta` | `chiave`, `valore` — nomi e colori dei candidati |
| `voti` | `sezione`, `voti_1`, `voti_2`, ... |
| `affluenza` | `sezione`, `affluenza` (valore 0–100) |

---

## Rieseguire la pipeline Python

```bash
cd claude/
pip install geopandas shapely pandas openpyxl
python pipeline.py
```

Output: `edifici_colorabili_voti.geojson` e `voronoi_per_sezione.geojson` nella stessa cartella.  
Copiare i file aggiornati in `docs/geojson/` e fare commit.

---

## Tecnologie

- **Mappa:** [Leaflet.js](https://leafletjs.com/) + tile CartoDB Positron
- **Grafici:** [Chart.js](https://www.chartjs.org/)
- **Dati:** Google Sheets (CSV pubblico, no API key)
- **Hosting:** GitHub Pages (sito statico, zero backend)
- **Pipeline:** Python — geopandas, shapely, pandas, folium

---

## Licenza

Codice: MIT  
Dati elettorali: pubblico dominio  
Dati geografici (OSM): ODbL
