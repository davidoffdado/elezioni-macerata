"""
Individua edifici la cui sezione è anomala rispetto ai vicini.
Per ogni edificio controlla i K vicini più prossimi: se la sezione
dell'edificio è diversa da quella della maggioranza dei vicini, lo segnala.

Output: outlier_sezioni.csv  (edifici sospetti con sezione assegnata e sezione dominante attorno)
"""

import geopandas as gpd
import pandas as pd
import numpy as np
from sklearn.neighbors import NearestNeighbors

FILE_GEOJSON = "edifici_colorabili_voti.geojson"
K_VICINI     = 10   # numero di vicini da considerare
SOGLIA       = 0.6  # frazione minima di vicini con sezione diversa per segnalare

# =========================
# LOAD
# =========================
gdf = gpd.read_file(FILE_GEOJSON).to_crs("EPSG:32633")  # proiezione metrica
gdf["sezione"] = gdf["sezione"].astype(str).str.strip()

# usa i centroidi come posizione
gdf["cx"] = gdf.geometry.centroid.x
gdf["cy"] = gdf.geometry.centroid.y

coords = gdf[["cx", "cy"]].to_numpy()

# =========================
# K-NEAREST NEIGHBORS
# =========================
nn = NearestNeighbors(n_neighbors=K_VICINI + 1, algorithm="ball_tree")
nn.fit(coords)
distances, indices = nn.kneighbors(coords)

# indices[:, 0] è l'edificio stesso, partiamo da 1
vicini_idx = indices[:, 1:]   # shape (n_edifici, K_VICINI)

# =========================
# INDIVIDUA OUTLIER
# =========================
risultati = []
sezioni = gdf["sezione"].to_numpy()

for i in range(len(gdf)):
    sez_i = sezioni[i]
    if pd.isna(sez_i) or sez_i == "nan":
        continue

    sez_vicini = sezioni[vicini_idx[i]]
    sez_vicini = sez_vicini[~pd.isna(sez_vicini)]

    if len(sez_vicini) == 0:
        continue

    # sezione dominante tra i vicini
    valori, conteggi = np.unique(sez_vicini, return_counts=True)
    sez_dominante = valori[np.argmax(conteggi)]
    frac_diversi = (sez_vicini != sez_i).sum() / len(sez_vicini)

    if frac_diversi >= SOGLIA and sez_i != sez_dominante:
        row = gdf.iloc[i]
        col_id = "@id" if "@id" in gdf.columns else "id"
        risultati.append({
            "id_edificio":    row.get(col_id, ""),
            "sezione":        sez_i,
            "sezione_vicini": sez_dominante,
            "frac_diversi":   round(frac_diversi, 2),
            "n_vicini":       len(sez_vicini),
            "nome":           row.get("name", ""),
            "indirizzo":      row.get("addr:street", ""),
            "civico":         row.get("addr:housenumber", ""),
        })

# =========================
# OUTPUT
# =========================
if risultati:
    df_out = pd.DataFrame(risultati).sort_values("frac_diversi", ascending=False)
    df_out.to_csv("outlier_sezioni.csv", index=False)
    print(f"Trovati {len(df_out)} edifici sospetti → outlier_sezioni.csv")
    print(df_out[["id_edificio", "sezione", "sezione_vicini", "frac_diversi", "nome", "indirizzo", "civico"]].to_string(index=False))
else:
    print("Nessun outlier trovato.")
