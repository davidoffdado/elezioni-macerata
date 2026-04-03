import pandas as pd
import geopandas as gpd

# =========================
# CONFIG — solo percorsi
# =========================
FILE_SEZIONI    = "voronoi_per_sezione.geojson"
FILE_EDIFICI    = "edifici.geojson"
FILE_VOTI       = "voti_per_sezione.xlsx"
FILE_AFFLUENZA  = "affluenza_per_sezione.xlsx"
FILE_OUTPUT     = "edifici_colorabili_voti.geojson"

# Correzioni manuali (opzionale): CSV con colonne  id_edificio, sezione_corretta
# Crea il file se vuoi correggere singoli edifici sbagliati dal Voronoi.
# L'id_edificio corrisponde alla colonna "@id" del GeoJSON (es. "way/123456789").
FILE_CORREZIONI = "correzioni_sezioni.csv"   # lascia così; viene ignorato se il file non esiste

# =========================
# LOAD
# =========================
sezioni  = gpd.read_file(FILE_SEZIONI)
edifici  = gpd.read_file(FILE_EDIFICI)
voti     = pd.read_excel(FILE_VOTI)
aff      = pd.read_excel(FILE_AFFLUENZA)

# normalizza nomi colonne
for df in [sezioni, edifici, voti, aff]:
    df.columns = df.columns.str.strip().str.lower()

print("Colonne voti lette:      ", voti.columns.tolist())
print("Colonne affluenza lette: ", aff.columns.tolist())

# =========================
# PULIZIA DATI
# =========================
for df, chiave in [(voti, "sezione"), (aff, "sezione")]:
    df[chiave] = df[chiave].astype(str).str.strip()
sezioni["sezione"] = sezioni["sezione"].astype(str).str.strip()

# converti virgola → punto nei numeri
colonne_non_str_voti = [c for c in voti.columns if c not in ("sezione", "seggio")]
for col in colonne_non_str_voti:
    voti[col] = pd.to_numeric(
        voti[col].astype(str).str.replace(",", ".", regex=False).str.strip(),
        errors="coerce"
    )

colonne_non_str_aff = [c for c in aff.columns if c != "sezione"]
for col in colonne_non_str_aff:
    aff[col] = pd.to_numeric(
        aff[col].astype(str).str.replace(",", ".", regex=False).str.strip(),
        errors="coerce"
    )

# tieni solo le colonne affluenza + sezione
campi_aff = ["sezione"] + [c for c in aff.columns if c.startswith("affluenza")]
aff = aff[campi_aff].copy()

# =========================
# MERGE TABELLARE
# =========================
sezioni_all = sezioni.merge(voti, on="sezione", how="left")
sezioni_all = sezioni_all.merge(aff, on="sezione", how="left")
print("Colonne finali dopo i merge:", sezioni_all.columns.tolist())

# =========================
# JOIN SPAZIALE SUGLI EDIFICI
# =========================
edifici = edifici.to_crs(sezioni_all.crs)
campi = [c for c in sezioni_all.columns if c != "geometry"]

# join tramite centroidi degli edifici
edifici_centroidi = edifici.copy()
edifici_centroidi["geometry"] = edifici.geometry.centroid

join = gpd.sjoin(
    edifici_centroidi,
    sezioni_all[campi + ["geometry"]],
    how="left",
    predicate="within"
)

edifici_join = edifici.copy()
for col in join.columns:
    if col != "geometry":
        edifici_join[col] = join[col].values

if "index_right" in edifici_join.columns:
    edifici_join = edifici_join.drop(columns=["index_right"])

print(f"Edifici totali: {len(edifici)} | dopo join: {len(edifici_join)}")

# =========================
# CORREZIONI MANUALI (opzionale)
# =========================
from pathlib import Path
if Path(FILE_CORREZIONI).exists():
    correzioni = pd.read_csv(FILE_CORREZIONI, dtype=str)
    correzioni.columns = correzioni.columns.str.strip().str.lower()
    correzioni["id_edificio"]    = correzioni["id_edificio"].str.strip()
    correzioni["sezione_corretta"] = correzioni["sezione_corretta"].str.strip()

    # mappa id → sezione corretta
    mappa = dict(zip(correzioni["id_edificio"], correzioni["sezione_corretta"]))

    col_id = "@id" if "@id" in edifici_join.columns else "id"
    n_corretti = 0
    for idx, row in edifici_join.iterrows():
        eid = str(row.get(col_id, ""))
        if eid in mappa:
            vecchia = edifici_join.at[idx, "sezione"]
            nuova   = mappa[eid]
            edifici_join.at[idx, "sezione"] = nuova
            # ricopiare i dati voto/affluenza della sezione corretta
            dati_nuovi = sezioni_all[sezioni_all["sezione"] == nuova]
            if not dati_nuovi.empty:
                for col in [c for c in dati_nuovi.columns if c not in ("sezione", "geometry")]:
                    edifici_join.at[idx, col] = dati_nuovi.iloc[0][col]
            n_corretti += 1
            print(f"  Corretto: {eid}  {vecchia} → {nuova}")

    print(f"Correzioni applicate: {n_corretti}")
else:
    print(f"Nessun file correzioni trovato ({FILE_CORREZIONI}) — skip.")

# =========================
# SALVA
# =========================
edifici_join.to_file(FILE_OUTPUT, driver="GeoJSON")
print(f"Creato: {FILE_OUTPUT}")
