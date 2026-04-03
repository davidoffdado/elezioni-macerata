"""
Esegue la pipeline completa in sequenza:
  1. voronoi.py          — crea voronoi_per_sezione.geojson
  2. creazione_file_voti.py  — crea edifici_colorabili_voti.geojson
  3. creazione_mappa_voti.py — crea mappa_affluenza_e_duello.html

Uso:
  python pipeline.py

Input richiesti nella stessa cartella:
  - final_data.xlsx          (coordinate seggi: colonne sezione, lat, lon)
  - macerata.geojson         (confine comunale)
  - edifici.geojson          (edifici OSM)
  - voti_per_sezione.xlsx    (risultati di voto per sezione)
  - affluenza_per_sezione.xlsx (affluenza per sezione)
"""

import subprocess
import sys
from pathlib import Path

CARTELLA = Path(__file__).parent

STEPS = [
    {
        "nome": "1. Voronoi",
        "cmd": [sys.executable, "voronoi.py", "final_data.xlsx", "macerata.geojson"],
    },
    {
        "nome": "2. Join voti → edifici",
        "cmd": [sys.executable, "creazione_file_voti.py"],
    },
    {
        "nome": "3. Generazione mappa",
        "cmd": [sys.executable, "creazione_mappa_voti.py"],
    },
]

for step in STEPS:
    print(f"\n{'='*50}")
    print(f"  {step['nome']}")
    print(f"{'='*50}")
    subprocess.run(step["cmd"], check=True, cwd=CARTELLA)

print("\nPipeline completata. Output: mappa_affluenza_e_duello.html")
