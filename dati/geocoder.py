import time
import pandas as pd
from geopy.geocoders import Nominatim
from geopy.extra.rate_limiter import RateLimiter
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable, GeocoderServiceError

# =========================
# CONFIG
# =========================
INPUT_FILE = "viario-elettorale-work.xlsx"
OUTPUT_FILE = "indirizzi_geocodificati_multi.xlsx"
CHECKPOINT_FILE = "indirizzi_geocodificati_checkpoint.xlsx"
SHEET_NAME = 0
CITY_SUFFIX = "Macerata, MC, Italia"

# timeout più alto
GEOCODER_TIMEOUT = 15

# Nominatim + user agent obbligatorio
geolocator = Nominatim(
    user_agent="geocoding_macerata_multi_2026",
    timeout=GEOCODER_TIMEOUT
)

# Ritmo prudente
geocode = RateLimiter(
    geolocator.geocode,
    min_delay_seconds=1.2,
    max_retries=2,
    error_wait_seconds=5.0,
    swallow_exceptions=False
)

# =========================
# HELPERS
# =========================
def is_all(value) -> bool:
    if pd.isna(value):
        return True
    return str(value).strip().lower() == "all"

def clean_str(value) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()

def to_int_or_none(value):
    try:
        return int(float(str(value).strip()))
    except Exception:
        return None

def build_sample_numbers(from_civico, to_civico):
    if is_all(from_civico) and is_all(to_civico):
        return []

    f = to_int_or_none(from_civico)
    t = to_int_or_none(to_civico)

    if f is None or t is None:
        return []

    start = min(f, t)
    end = max(f, t)

    if start == end:
        return [start]

    step = 2 if start % 2 == end % 2 else 1

    all_nums = list(range(start, end + 1, step))

    if len(all_nums) <= 5:
        return all_nums

    idxs = [0, 1, len(all_nums)//2, len(all_nums)-2, len(all_nums)-1]
    result = []
    seen = set()

    for i in idxs:
        n = all_nums[i]
        if n not in seen:
            seen.add(n)
            result.append(n)

    return result

def build_queries_for_row(row):
    street = clean_str(row["indirizzo_clean"])
    from_civico = row["from_civico"]
    to_civico = row["to_civico"]

    if is_all(from_civico) and is_all(to_civico):
        return [{
            "row_id": row["row_id"],
            "indirizzo_clean": street,
            "from_civico": from_civico,
            "to_civico": to_civico,
            "sample_type": "street_only",
            "sample_civico": None,
            "query_geocode": f"{street}, {CITY_SUFFIX}"
        }]

    sample_numbers = build_sample_numbers(from_civico, to_civico)

    if not sample_numbers:
        civico = clean_str(from_civico)
        if civico and civico.lower() != "all":
            return [{
                "row_id": row["row_id"],
                "indirizzo_clean": street,
                "from_civico": from_civico,
                "to_civico": to_civico,
                "sample_type": "fallback_from",
                "sample_civico": civico,
                "query_geocode": f"{street} {civico}, {CITY_SUFFIX}"
            }]
        return [{
            "row_id": row["row_id"],
            "indirizzo_clean": street,
            "from_civico": from_civico,
            "to_civico": to_civico,
            "sample_type": "street_only_fallback",
            "sample_civico": None,
            "query_geocode": f"{street}, {CITY_SUFFIX}"
        }]

    rows = []
    for i, n in enumerate(sample_numbers):
        if i == 0:
            sample_type = "from"
        elif i == len(sample_numbers) - 1:
            sample_type = "to"
        else:
            sample_type = "intermediate"

        rows.append({
            "row_id": row["row_id"],
            "indirizzo_clean": street,
            "from_civico": from_civico,
            "to_civico": to_civico,
            "sample_type": sample_type,
            "sample_civico": n,
            "query_geocode": f"{street} {n}, {CITY_SUFFIX}"
        })

    return rows

def safe_geocode(query: str):
    """
    Gestione robusta dei timeout e degli errori temporanei.
    """
    try:
        location = geocode(
            query,
            exactly_one=True,
            addressdetails=True,
            timeout=GEOCODER_TIMEOUT
        )

        if location is None:
            return {
                "latitudine": None,
                "longitudine": None,
                "indirizzo_trovato": None,
                "status": "not_found"
            }

        return {
            "latitudine": location.latitude,
            "longitudine": location.longitude,
            "indirizzo_trovato": location.address,
            "status": "ok"
        }

    except GeocoderTimedOut:
        return {
            "latitudine": None,
            "longitudine": None,
            "indirizzo_trovato": None,
            "status": "timeout"
        }

    except GeocoderUnavailable:
        return {
            "latitudine": None,
            "longitudine": None,
            "indirizzo_trovato": None,
            "status": "unavailable"
        }

    except GeocoderServiceError as e:
        return {
            "latitudine": None,
            "longitudine": None,
            "indirizzo_trovato": None,
            "status": f"service_error: {e}"
        }

    except Exception as e:
        return {
            "latitudine": None,
            "longitudine": None,
            "indirizzo_trovato": None,
            "status": f"error: {e}"
        }

# =========================
# LOAD
# =========================
if INPUT_FILE.lower().endswith(".csv"):
    df = pd.read_csv(INPUT_FILE)
else:
    df = pd.read_excel(INPUT_FILE, sheet_name=SHEET_NAME)

required_cols = {"indirizzo_clean", "from_civico", "to_civico"}
missing = required_cols - set(df.columns)
if missing:
    raise ValueError(f"Mancano queste colonne: {missing}")

df = df.copy()
df["indirizzo_clean"] = df["indirizzo_clean"].astype(str).str.strip()
df = df[df["indirizzo_clean"].str.strip() != ""].reset_index(drop=True)
df["row_id"] = df.index + 1

# =========================
# EXPAND
# =========================
expanded_rows = []
for _, row in df.iterrows():
    expanded_rows.extend(build_queries_for_row(row))

expanded_df = pd.DataFrame(expanded_rows)

# =========================
# CACHE SU QUERY UNICHE
# =========================
unique_queries = expanded_df["query_geocode"].dropna().unique().tolist()
cache_results = []

for i, q in enumerate(unique_queries, start=1):
    result = safe_geocode(q)
    cache_results.append({"query_geocode": q, **result})

    # checkpoint ogni 25 query
    if i % 25 == 0:
        checkpoint_df = pd.DataFrame(cache_results)
        checkpoint_df.to_excel(CHECKPOINT_FILE, index=False)
        print(f"Checkpoint salvato: {i}/{len(unique_queries)}")

cache_df = pd.DataFrame(cache_results)

# =========================
# MERGE FINALE
# =========================
final_df = expanded_df.merge(cache_df, on="query_geocode", how="left")

# =========================
# SAVE
# =========================
final_df.to_excel(OUTPUT_FILE, index=False)

print(f"File finale salvato: {OUTPUT_FILE}")
print(final_df.head(20).to_string(index=False))