#!/usr/bin/env python3
"""
Part 2: Fetch per-product detail for MVP branded products (≥100 reports).

Key design: queries each raw brand string separately and aggregates in Python.
This avoids Lucene OR-query escaping issues with '+', apostrophes, etc., and
makes every API call auditable. Slight over-count risk if a single FDA report
lists two merged raw strings as distinct products — logged in output notes.

Usage:
    python3 fetch_mvp_products.py [--dry-run]
"""

import csv, json, re, sys, time, urllib.request, urllib.parse
from collections import defaultdict
from datetime import datetime

CSV_PATH = "/tmp/supplement_brands_v2.csv"
OUT_PATH = "/tmp/supplement_mvp_detail.json"
BASE_URL = "https://api.fda.gov/food/event.json"
DELAY    = 1.6          # seconds between calls (keyless = 40 req/min)
MAX_AGE_RECORDS = 300   # records fetched per product for age stats
TOP_REACTIONS   = 30

DRY_RUN = "--dry-run" in sys.argv
eprint  = lambda *a, **kw: print(*a, file=sys.stderr, **kw)
call_n  = [0]

# ── API ───────────────────────────────────────────────────────────────────────

def api_get(params: dict) -> dict:
    if call_n[0] > 0:
        time.sleep(DELAY)
    call_n[0] += 1
    qs  = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    url = f"{BASE_URL}?{qs}"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=25) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            if e.code == 429:
                eprint("    429 rate-limited, waiting 15s…"); time.sleep(15); continue
            if e.code in (404, 400):
                return {}          # nothing found or bad query — treat as empty
            raise RuntimeError(f"HTTP {e.code}: {body[:200]}")
        except Exception as ex:
            if attempt == 2: raise
            time.sleep(4)
    raise RuntimeError("All retries exhausted")

def search_for(raw_brand: str) -> str:
    """Build exact search string for a single raw brand name."""
    return f'products.name_brand.exact:"{raw_brand}"'

# ── Aggregators ───────────────────────────────────────────────────────────────

def get_total(raw_brand: str) -> int:
    data = api_get({"search": search_for(raw_brand), "limit": "1"})
    return data.get("meta", {}).get("results", {}).get("total", 0)

def get_count_field(raw_brand: str, field: str, limit: int = 100) -> list[dict]:
    data = api_get({"search": search_for(raw_brand), "count": field, "limit": str(limit)})
    return data.get("results", [])

def get_records(raw_brand: str, skip: int, limit: int) -> tuple[int, list[dict]]:
    data = api_get({"search": search_for(raw_brand), "limit": str(limit), "skip": str(skip)})
    total = data.get("meta", {}).get("results", {}).get("total", 0)
    return total, data.get("results", [])

def aggregate_counts(per_string_results: list[list[dict]]) -> list[dict]:
    """Merge list-of-count-lists by term, combining case variants."""
    merged: dict[str, dict] = {}
    for results in per_string_results:
        for item in results:
            key = item["term"].lower()
            if key not in merged:
                merged[key] = {"term": item["term"], "count": 0}
            merged[key]["count"] += item["count"]
            # prefer mixed-case over all-caps for display
            if item["term"] != item["term"].upper() and merged[key]["term"] == merged[key]["term"].upper():
                merged[key]["term"] = item["term"]
    return sorted(merged.values(), key=lambda x: -x["count"])

def parse_raw_strings(raw_strings_merged: str) -> list[str]:
    result = []
    for part in raw_strings_merged.split(" | "):
        m = re.match(r"^(.+)\s+\(\d+\)\s*$", part.strip())
        if m:
            result.append(m.group(1))
    return result

def bucket_ages(records: list[dict]) -> dict:
    ages = []
    for rec in records:
        c = rec.get("consumer", {})
        raw = c.get("age")
        unit = (c.get("age_unit") or "").lower()
        if raw is None: continue
        try: a = float(raw)
        except: continue
        if "month" in unit: a /= 12
        elif "week"  in unit: a /= 52
        elif "day"   in unit: a /= 365
        if 0 <= a <= 130: ages.append(a)
    if not ages:
        return {"under_18":0,"18_34":0,"35_49":0,"50_64":0,"65_79":0,"80_plus":0,
                "unknown":len(records),"median_age":None,"mean_age":None,"n_with_age":0}
    ages.sort()
    n = len(ages)
    median = ages[n//2] if n%2 else (ages[n//2-1]+ages[n//2])/2
    bands = {"under_18":0,"18_34":0,"35_49":0,"50_64":0,"65_79":0,"80_plus":0}
    for a in ages:
        if   a < 18: bands["under_18"] += 1
        elif a < 35: bands["18_34"]    += 1
        elif a < 50: bands["35_49"]    += 1
        elif a < 65: bands["50_64"]    += 1
        elif a < 80: bands["65_79"]    += 1
        else:        bands["80_plus"]  += 1
    bands["unknown"]    = len(records) - n
    bands["median_age"] = round(median, 1)
    bands["mean_age"]   = round(sum(ages)/n, 1)
    bands["n_with_age"] = n
    return bands

def parse_trend(count_results_per_string: list[list[dict]]) -> dict[str, int]:
    yearly: dict[str, int] = defaultdict(int)
    for results in count_results_per_string:
        for item in results:
            t = str(item["term"])
            if len(t) >= 4 and t[:4].isdigit():
                yearly[t[:4]] += item["count"]
    year = datetime.now().year
    return {str(y): yearly.get(str(y), 0) for y in range(2004, year+1)}

# ── Load products ─────────────────────────────────────────────────────────────

rows = list(csv.DictReader(open(CSV_PATH)))
mvp  = [r for r in rows
        if r["type"] == "branded"
        and r["contamination_action"] != "exclude"
        and int(r["total_reports"]) >= 100]
mvp.sort(key=lambda x: -int(x["total_reports"]))

print(f"MVP products to fetch: {len(mvp)}")
total_calls = sum(
    len(parse_raw_strings(r["raw_strings_merged"])) * 5  # reactions,outcomes,gender,trend,age-records
    + min(int(r["total_reports"]), MAX_AGE_RECORDS) // 100  # extra pages
    for r in mvp
)
print(f"Estimated API calls: ~{total_calls}  (~{int(total_calls * DELAY / 60)} min)")

if DRY_RUN:
    for i, r in enumerate(mvp, 1):
        rs = parse_raw_strings(r["raw_strings_merged"])
        print(f"  {i:>2}. {r['canonical_display_name'][:50]:<52} [{int(r['total_reports']):>5}]  {len(rs)} raw")
    print("\n[dry-run] Done."); sys.exit(0)

# ── Main fetch loop ───────────────────────────────────────────────────────────

output  = {}
failed  = []

for idx, product in enumerate(mvp):
    name     = product["canonical_display_name"]
    norm_key = product["normalized_key"]
    csv_total = int(product["total_reports"])
    raw_list = parse_raw_strings(product["raw_strings_merged"])

    eprint(f"\n[{idx+1}/{len(mvp)}] {name}  ({csv_total} reports, {len(raw_list)} raw strings)")

    try:
        # ── Total reports (one search/limit=1 per raw string) ────────────────
        eprint("  → total")
        total_per_string = [get_total(rs) for rs in raw_list]
        total_reports = sum(total_per_string)
        if total_reports == 0:
            raise ValueError(f"API returned 0 total reports (expected ~{csv_total})")
        eprint(f"     {total_per_string} → {total_reports}")

        # ── Reactions ────────────────────────────────────────────────────────
        eprint("  → reactions")
        rxn_raw = [get_count_field(rs, "reactions.exact", 100) for rs in raw_list]
        reactions_merged = aggregate_counts(rxn_raw)[:TOP_REACTIONS]
        reactions_out = [
            {"term": r["term"], "count": r["count"],
             "pct": round(r["count"]/total_reports*100, 2)}
            for r in reactions_merged
        ]

        # ── Outcomes ─────────────────────────────────────────────────────────
        eprint("  → outcomes")
        out_raw = [get_count_field(rs, "outcomes.exact", 50) for rs in raw_list]
        outcomes_merged = aggregate_counts(out_raw)
        outcomes_out = {
            r["term"]: {"count": r["count"], "pct": round(r["count"]/total_reports*100, 2)}
            for r in outcomes_merged
        }

        # ── HARD GATE: deaths ≤ total_reports ────────────────────────────────
        death_count = outcomes_out.get("Death", outcomes_out.get("death", {})).get("count", 0)
        if death_count > total_reports:
            eprint(f"  ✗ HARD GATE FAIL: deaths={death_count} > total_reports={total_reports}")
            failed.append({"product": name, "deaths": death_count,
                           "total_reports": total_reports,
                           "reason": f"deaths({death_count}) > total_reports({total_reports})"})
            continue
        eprint(f"  ✓ death gate: {death_count} / {total_reports}")

        # ── Gender ───────────────────────────────────────────────────────────
        eprint("  → gender")
        gen_raw = [get_count_field(rs, "consumer.gender.exact", 10) for rs in raw_list]
        gender_merged = aggregate_counts(gen_raw)
        gender_out = {r["term"]: r["count"] for r in gender_merged}
        gender_out["Unknown/Not Reported"] = total_reports - sum(gender_out.values())

        # ── Yearly trend ─────────────────────────────────────────────────────
        eprint("  → trend")
        trend_raw = [get_count_field(rs, "date_created.exact", 1000) for rs in raw_list]
        yearly_trend = parse_trend(trend_raw)

        # ── Age demographics (fetch records) ─────────────────────────────────
        eprint("  → age records")
        age_records = []
        remaining = MAX_AGE_RECORDS
        for rs in raw_list:
            if remaining <= 0: break
            want = min(remaining, total_per_string[raw_list.index(rs)])
            pages = (want + 99) // 100
            for pg in range(pages):
                skip  = pg * 100
                limit = min(100, want - skip)
                if limit <= 0: break
                _, recs = get_records(rs, skip, limit)
                age_records.extend(recs)
                remaining -= len(recs)
        age_demo = bucket_ages(age_records)

        # ── Assemble ─────────────────────────────────────────────────────────
        output[name] = {
            "canonical_display_name": name,
            "normalized_key":   norm_key,
            "type":             product["type"],
            "brand_family":     product["brand_family"],
            "contamination_flag": product["contamination_flag"],
            "total_reports":    total_reports,
            "total_reports_csv": csv_total,
            "page_eligible":    True,
            "raw_strings":      raw_list,
            "query_timestamp":  datetime.utcnow().isoformat() + "Z",
            "reactions": {
                "top_reactions": reactions_out,
                "note": "Top 30; case-normalised across raw string variants"
            },
            "outcomes": outcomes_out,
            "demographics": {
                "gender":    gender_out,
                "age_bands": age_demo,
                "age_note":  f"Up to {MAX_AGE_RECORDS} records sampled for age"
            },
            "yearly_trend": yearly_trend,
            "sanity_checks": {
                "deaths": death_count,
                "total_reports": total_reports,
                "deaths_lte_total_reports": death_count <= total_reports,
                "note": "Multi-raw-string products may slightly over-count if a single "
                        "FDA report lists two merged variants as distinct products"
            }
        }
        eprint(f"  ✓ assembled")

    except Exception as ex:
        import traceback
        eprint(f"  ✗ ERROR: {ex}")
        eprint(traceback.format_exc())
        failed.append({"product": name, "reason": str(ex)})

# ── Write JSON ────────────────────────────────────────────────────────────────
with open(OUT_PATH, "w") as f:
    json.dump(output, f, indent=2)
eprint(f"\nWrote {len(output)} products → {OUT_PATH}")

# ── Summary table ─────────────────────────────────────────────────────────────
sep = "─" * 82
print(f"\n{sep}")
print(f"MVP PRODUCT DETAIL — SUMMARY ({len(output)} products, {call_n[0]} API calls)")
print(sep)
print(f"{'#':<3} {'Product':<46} {'Rpts':>5} {'Deaths':>7} {'Hosp':>6} {'ER':>5} {'LifeTh':>7} {'Rxns':>5}")
print(sep)
sorted_out = sorted(output.items(), key=lambda x: -x[1]["total_reports"])
for i, (name, d) in enumerate(sorted_out, 1):
    tr    = d["total_reports"]
    oc    = d["outcomes"]
    def oc_count(k): return oc.get(k, {}).get("count", 0)
    deaths = oc_count("Death")
    hosp   = oc_count("Hospitalization")
    er     = oc_count("Visited Emergency Room")
    lt     = oc_count("Life Threatening")
    nr     = len(d["reactions"]["top_reactions"])
    flags  = ("⚠DEATH>TOTAL " if deaths > tr else "") + ("⚠HOSP>TOTAL" if hosp > tr else "")
    print(f"{i:<3} {name[:45]:<46} {tr:>5} {deaths:>7} {hosp:>6} {er:>5} {lt:>7} {nr:>5}  {flags}")
print(sep)

if failed:
    print(f"\nHARD GATE FAILURES / ERRORS ({len(failed)}):")
    for f in failed:
        print(f"  ✗  {f['product']}: {f['reason']}")
    print("No data emitted for these products.")
else:
    print(f"\n✓ All {len(output)} products passed the death ≤ total_reports gate.")
print(sep)
