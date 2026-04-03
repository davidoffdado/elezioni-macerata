import sys
import json
from pathlib import Path

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, Polygon, MultiPolygon
from shapely.ops import unary_union
from scipy.spatial import Voronoi


def voronoi_finite_polygons_2d(vor, radius=None):
    """
    Ricostruisce le regioni infinite del Voronoi in poligoni finiti.
    Adattato dal classico esempio di SciPy.
    """
    if vor.points.shape[1] != 2:
        raise ValueError("Richiesti punti 2D.")

    new_regions = []
    new_vertices = vor.vertices.tolist()

    center = vor.points.mean(axis=0)
    if radius is None:
        radius = np.ptp(vor.points, axis=0).max() * 2

    all_ridges = {}
    for (p1, p2), (v1, v2) in zip(vor.ridge_points, vor.ridge_vertices):
        all_ridges.setdefault(p1, []).append((p2, v1, v2))
        all_ridges.setdefault(p2, []).append((p1, v1, v2))

    for p1, region_index in enumerate(vor.point_region):
        vertices = vor.regions[region_index]

        if all(v >= 0 for v in vertices):
            new_regions.append(vertices)
            continue

        ridges = all_ridges[p1]
        new_region = [v for v in vertices if v >= 0]

        for p2, v1, v2 in ridges:
            if v2 < 0:
                v1, v2 = v2, v1
            if v1 >= 0:
                continue

            t = vor.points[p2] - vor.points[p1]
            t /= np.linalg.norm(t)

            n = np.array([-t[1], t[0]])
            midpoint = vor.points[[p1, p2]].mean(axis=0)
            direction = np.sign(np.dot(midpoint - center, n)) * n
            far_point = vor.vertices[v2] + direction * radius

            new_vertices.append(far_point.tolist())
            new_region.append(len(new_vertices) - 1)

        vs = np.asarray([new_vertices[v] for v in new_region])
        c = vs.mean(axis=0)
        angles = np.arctan2(vs[:, 1] - c[1], vs[:, 0] - c[0])
        new_region = [v for _, v in sorted(zip(angles, new_region))]

        new_regions.append(new_region)

    return new_regions, np.asarray(new_vertices)


def load_points_from_excel(xlsx_path):
    df = pd.read_excel(xlsx_path)

    required = ["sezione", "lat", "lon"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Mancano colonne obbligatorie: {missing}")

    for c in ["lat", "lon"]:
        df[c] = (
            df[c]
            .astype(str)
            .str.replace(",", ".", regex=False)
            .str.strip()
        )
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["lat", "lon"]).copy()

    gdf = gpd.GeoDataFrame(
        df,
        geometry=[Point(xy) for xy in zip(df["lon"], df["lat"])],
        crs="EPSG:4326",
    )
    return gdf


def load_boundary(boundary_path):
    boundary = gpd.read_file(boundary_path)

    if boundary.empty:
        raise ValueError("Il file del confine è vuoto.")

    if boundary.crs is None:
        boundary = boundary.set_crs("EPSG:4326")

    boundary = boundary.to_crs("EPSG:4326")
    geom = unary_union(boundary.geometry)

    if geom.is_empty:
        raise ValueError("Geometria del confine vuota.")

    return boundary, geom


def filter_points_inside_boundary(points_gdf, boundary_geom):
    inside_mask = points_gdf.geometry.apply(boundary_geom.covers)
    inside = points_gdf[inside_mask].copy()
    outside = points_gdf[~inside_mask].copy()
    return inside, outside


def make_voronoi(points_gdf, clip_geom):
    """
    Costruisce il Voronoi sui punti e lo clippa al poligono clip_geom.
    Gestisce punti duplicati assegnando loro la stessa cella.
    """
    work = points_gdf.copy()

    # Proiezione metrica per Voronoi più sensato
    work = work.to_crs("EPSG:32633")
    clip = gpd.GeoSeries([clip_geom], crs="EPSG:4326").to_crs("EPSG:32633").iloc[0]

    work["x"] = work.geometry.x
    work["y"] = work.geometry.y

    unique_pts = work[["x", "y"]].drop_duplicates().reset_index(drop=True)

    if len(unique_pts) < 2:
        raise ValueError("Servono almeno 2 punti distinti per il Voronoi.")

    coords = unique_pts[["x", "y"]].to_numpy()
    vor = Voronoi(coords)
    regions, vertices = voronoi_finite_polygons_2d(vor)

    cells = []
    for i, region in enumerate(regions):
        polygon = Polygon(vertices[region])
        if not polygon.is_valid:
            polygon = polygon.buffer(0)

        polygon = polygon.intersection(clip)
        cells.append(
            {
                "x": coords[i, 0],
                "y": coords[i, 1],
                "geometry": polygon,
            }
        )

    cells_gdf = gpd.GeoDataFrame(cells, crs="EPSG:32633")

    # Join su coordinate per ridare la cella anche ai duplicati
    out = work.merge(cells_gdf, on=["x", "y"], how="left", suffixes=("", "_cell"))
    out = gpd.GeoDataFrame(out.drop(columns="geometry"), geometry=out["geometry_cell"], crs="EPSG:32633")
    out = out.drop(columns=["geometry_cell", "x", "y"])

    return out


def dissolve_by_sezione(voronoi_gdf):
    dissolved = voronoi_gdf.dissolve(by="sezione", as_index=False)
    return dissolved


def main():
    if len(sys.argv) < 3:
        print("Uso: python voronoi.py final_data.xlsx macerata.geojson")
        sys.exit(1)

    xlsx_path = Path(sys.argv[1])
    boundary_path = Path(sys.argv[2])

    points = load_points_from_excel(xlsx_path)
    _, boundary_geom = load_boundary(boundary_path)

    points_inside, points_outside = filter_points_inside_boundary(points, boundary_geom)

    print(f"Punti totali:   {len(points)}")
    print(f"Punti dentro:   {len(points_inside)}")
    print(f"Punti fuori:    {len(points_outside)}")

    # salva punti fuori per controllo
    if len(points_outside) > 0:
        points_outside.to_file("punti_fuori_macerata.geojson", driver="GeoJSON")

    if len(points_inside) < 2:
        raise ValueError("Non ci sono abbastanza punti interni per costruire il Voronoi.")

    voronoi_points = make_voronoi(points_inside, boundary_geom)
    voronoi_sezioni = dissolve_by_sezione(voronoi_points)

    # torna in WGS84
    voronoi_points = voronoi_points.to_crs("EPSG:4326")
    voronoi_sezioni = voronoi_sezioni.to_crs("EPSG:4326")

    voronoi_points.to_file("voronoi_per_punto.geojson", driver="GeoJSON")
    voronoi_sezioni.to_file("voronoi_per_sezione.geojson", driver="GeoJSON")

    print("Creati:")
    print("- punti_fuori_macerata.geojson")
    print("- voronoi_per_punto.geojson")
    print("- voronoi_per_sezione.geojson")


if __name__ == "__main__":
    main()