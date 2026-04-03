import folium
import geopandas as gpd
import pandas as pd
import branca.colormap as cm

# =========================
# CONFIG — solo percorsi
# =========================
FILE_GEOJSON = "edifici_colorabili_voti.geojson"

# =========================
# LOAD
# =========================
gdf = gpd.read_file(FILE_GEOJSON).to_crs(4326)

for col in gdf.columns:
    if pd.api.types.is_datetime64_any_dtype(gdf[col]):
        gdf[col] = gdf[col].astype(str)

# =========================
# RILEVAMENTO AUTOMATICO COLONNE
# =========================
colonne_candidati = sorted([c for c in gdf.columns if c.startswith("candidato")])
colonne_affluenza = sorted([c for c in gdf.columns if c.startswith("affluenza")])

if not colonne_candidati:
    raise ValueError("Nessuna colonna 'candidato*' trovata nel GeoJSON.")
if not colonne_affluenza:
    raise ValueError("Nessuna colonna 'affluenza*' trovata nel GeoJSON.")

for col in colonne_candidati + colonne_affluenza:
    gdf[col] = pd.to_numeric(gdf[col], errors="coerce")

print(f"Candidati rilevati:        {colonne_candidati}")
print(f"Colonne affluenza rilevate: {colonne_affluenza}")

# =========================
# DUELLO: top 2 candidati per voti totali
# =========================
totali = {c: gdf[c].sum() for c in colonne_candidati}
top2 = sorted(totali, key=totali.get, reverse=True)[:2]
CANDIDATO_A, CANDIDATO_B = top2[0], top2[1]
print(f"Duello: {CANDIDATO_A} vs {CANDIDATO_B}")

gdf["duello_diff"] = gdf[CANDIDATO_A] - gdf[CANDIDATO_B]

# Affluenza principale: preferisci "affluenza" pura (risultato finale), altrimenti l'ultima
CAMPO_AFFLUENZA_PRINCIPALE = "affluenza" if "affluenza" in colonne_affluenza else colonne_affluenza[-1]

# =========================
# MAPPA BASE
# =========================
m = folium.Map(location=[43.30, 13.45], zoom_start=13, tiles="CartoDB positron")
bounds = gdf.total_bounds
m.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])

# =========================
# COLORMAPS
# =========================
colormap_aff_principale = cm.LinearColormap(
    colors=["#d73027", "#fee08b", "#1a9850"],
    vmin=0, vmax=1,
    caption=f"Affluenza ({CAMPO_AFFLUENZA_PRINCIPALE})"
)

abs_max = max(abs(gdf["duello_diff"].min()), abs(gdf["duello_diff"].max()))
colormap_duello = cm.LinearColormap(
    colors=["#2166ff", "#9ec9ff", "#ffb3b3", "#ff1f1f"],
    vmin=-abs_max, vmax=abs_max,
    caption=f"Differenza {CANDIDATO_A} – {CANDIDATO_B}"
)

# =========================
# COLORI PER SEZIONE
# =========================
gdf["sezione"] = gdf["sezione"].astype(str)
sezioni_uniche = sorted(gdf["sezione"].dropna().unique().tolist())

palette = [
    "#e41a1c", "#377eb8", "#4daf4a", "#984ea3", "#ff7f00",
    "#ffff33", "#a65628", "#f781bf", "#999999", "#66c2a5",
    "#fc8d62", "#8da0cb", "#e78ac3", "#a6d854", "#ffd92f",
    "#e5c494", "#b3b3b3", "#1b9e77", "#d95f02", "#7570b3",
    "#e7298a", "#66a61e", "#e6ab02", "#a6761d", "#666666",
    "#8dd3c7", "#fb8072", "#80b1d3", "#fdb462", "#b3de69",
    "#fccde5", "#bc80bd", "#ccebc5", "#ffed6f", "#6a3d9a",
    "#b15928", "#17becf", "#aec7e8", "#ff9896", "#98df8a",
    "#c5b0d5", "#c49c94", "#f7b6d2", "#c7c7c7"
]
sezione_to_color = {sez: palette[i % len(palette)] for i, sez in enumerate(sezioni_uniche)}

# =========================
# POPUP / TOOLTIP DINAMICI
# =========================
popup_fields = ["sezione", "seggio"] + colonne_candidati + colonne_affluenza
popup_aliases = [f"{c}: " for c in popup_fields]

# =========================
# STYLE FUNCTIONS
# =========================
def style_sezione(feature):
    sez = str(feature["properties"].get("sezione") or "")
    return {
        "fillColor": sezione_to_color.get(sez, "#cccccc"),
        "color": "#777777", "weight": 0.15, "fillOpacity": 0.75,
    }

def make_style_affluenza(campo, colormap):
    def style(feature):
        val = feature["properties"].get(campo)
        try:
            color = colormap(float(val))
        except (TypeError, ValueError):
            color = "#cccccc"
        return {"fillColor": color, "color": "#777777", "weight": 0.15, "fillOpacity": 0.75}
    return style

def style_duello(feature):
    val = feature["properties"].get("duello_diff")
    try:
        color = colormap_duello(float(val))
    except (TypeError, ValueError):
        color = "#cccccc"
    return {"fillColor": color, "color": "#777777", "weight": 0.15, "fillOpacity": 0.75}

# =========================
# LAYERS
# =========================

# Layer sezione
folium.GeoJson(
    gdf,
    name="Sezione",
    style_function=style_sezione,
    tooltip=folium.GeoJsonTooltip(fields=["sezione", "seggio"]),
    popup=folium.GeoJsonPopup(
        fields=["sezione", "seggio"],
        aliases=["Sezione: ", "Seggio: "],
        localize=True, labels=True, sticky=False
    ),
    show=False
).add_to(m)

# Layer affluenza (uno per ogni colonna trovata)
for campo_aff in colonne_affluenza:
    is_principale = (campo_aff == CAMPO_AFFLUENZA_PRINCIPALE)
    colormap = cm.LinearColormap(
        colors=["#d73027", "#fee08b", "#1a9850"],
        vmin=0, vmax=1,
        caption=f"Affluenza ({campo_aff})"
    )
    folium.GeoJson(
        gdf,
        name=f"Affluenza ({campo_aff})",
        style_function=make_style_affluenza(campo_aff, colormap),
        tooltip=folium.GeoJsonTooltip(fields=["sezione", "seggio", campo_aff]),
        popup=folium.GeoJsonPopup(
            fields=popup_fields,
            aliases=popup_aliases,
            localize=True, labels=True, sticky=False
        ),
        show=is_principale
    ).add_to(m)
    colormap.add_to(m)

# Layer duello
folium.GeoJson(
    gdf,
    name=f"Duello {CANDIDATO_A} vs {CANDIDATO_B}",
    style_function=style_duello,
    tooltip=folium.GeoJsonTooltip(fields=["sezione", "seggio", CANDIDATO_A, CANDIDATO_B]),
    popup=folium.GeoJsonPopup(
        fields=popup_fields + ["duello_diff"],
        aliases=popup_aliases + [f"diff {CANDIDATO_A}–{CANDIDATO_B}: "],
        localize=True, labels=True, sticky=False
    ),
    show=False
).add_to(m)
colormap_duello.add_to(m)

folium.LayerControl(collapsed=False).add_to(m)

m.save("mappa_affluenza_e_duello.html")
print("Creato: mappa_affluenza_e_duello.html")
