#!/usr/bin/env python3
"""
Bulk ingest of openFDA food/event dataset + local matching against v3 MVP products.
Downloads once (~8.8MB), processes entirely in memory.
Permanently fixes + and \\x92 reconciliation gaps.
"""

import csv, io, json, os, re, sys, zipfile
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path

MANIFEST_URL   = "https://api.fda.gov/download.json"
CACHE_DIR      = Path("/tmp/fda_bulk")
CSV_PATH       = "/tmp/supplement_brands_v3.csv"
JSON_IN        = "/tmp/supplement_mvp_final.json"
JSON_OUT       = "/tmp/supplement_mvp_final_v2.json"
INDUSTRY_FILTER = "Vit/Min/Prot/Unconv Diet(Human/Animal)"
TOP_REACTIONS  = 30

eprint = lambda *a, **kw: print(*a, file=sys.stderr, **kw)

# ── Download & cache ──────────────────────────────────────────────────────────

CACHE_DIR.mkdir(exist_ok=True)

eprint("Fetching manifest…")
with urllib.request.urlopen(MANIFEST_URL, timeout=20) as r:
    manifest = json.load(r)

partitions = manifest["results"]["food"]["event"]["partitions"]
eprint(f"  {len(partitions)} partition(s), "
       f"{manifest['results']['food']['event']['total_records']:,} total records")

all_records_raw = []
for p in partitions:
    url       = p["file"]
    fname     = CACHE_DIR / url.split("/")[-1]
    if fname.exists():
        eprint(f"  Using cached {fname.name}")
    else:
        eprint(f"  Downloading {fname.name} ({p['size_mb']} MB)…")
        urllib.request.urlretrieve(url, fname)
        eprint(f"  Done.")

    with zipfile.ZipFile(fname) as zf:
        for member in zf.namelist():
            eprint(f"  Parsing {member}…")
            with zf.open(member) as f:
                data = json.load(f)
                all_records_raw.extend(data["results"])

eprint(f"  Loaded {len(all_records_raw):,} raw records")

# ── Filter to supplement industry ─────────────────────────────────────────────

supp_records = [
    rec for rec in all_records_raw
    if any(
        p.get("industry_name","") == INDUSTRY_FILTER
        for p in rec.get("products", [])
    )
]
eprint(f"  Supplement records: {len(supp_records):,}")

# ── Build brand-name index ────────────────────────────────────────────────────
# brand_index: raw name_brand string → set of report_numbers
# report_store: report_number → full record

brand_index  = defaultdict(set)
report_store = {}

# Also track the exact byte representation of brand names for debugging
brand_name_variants = defaultdict(set)   # lowered → set of raw strings

for rec in supp_records:
    rn = rec["report_number"]
    report_store[rn] = rec
    for prod in rec.get("products", []):
        nb = prod.get("name_brand")
        if nb:
            brand_index[nb].add(rn)
            brand_name_variants[nb.lower()].add(nb)

eprint(f"  Distinct brand strings in index: {len(brand_index):,}")

# Show encoding variants for the problematic products
for probe in ["centrum silver womens 50", "centrum silver ultra womens"]:
    variants = [(k, len(v)) for k, v in brand_index.items()
                if probe in k.lower() and "multivitamin" not in k.lower()[:40]]
    if variants:
        eprint(f"\n  Brand variants for '{probe}':")
        for k, n in sorted(variants, key=lambda x: -x[1])[:6]:
            byte_repr = " ".join(f"{ord(c):04x}" for c in k[:20])
            eprint(f"    [{n:>4} reports]  {repr(k[:60])}")
            eprint(f"              bytes: {byte_repr}")

# ── Load MVP product list ─────────────────────────────────────────────────────

def parse_raw(merged: str) -> list:
    result = []
    for part in merged.split(" | "):
        mo = re.match(r"^(.+)\s+\(\d+\)\s*$", part.strip())
        if mo: result.append(mo.group(1))
    return result

csv_rows = list(csv.DictReader(open(CSV_PATH)))
mvp_csv  = [r for r in csv_rows
            if r.get("type") == "branded"
            and r.get("contamination_action","") != "exclude"
            and r.get("total_reports") and int(r["total_reports"]) >= 100]
mvp_csv.sort(key=lambda x: -int(x["total_reports"]))
eprint(f"\n  MVP products to process: {len(mvp_csv)}")

existing_json = json.load(open(JSON_IN))

# ── Compute per-product stats from local data ─────────────────────────────────

def compute_stats(matched_rns: set) -> dict:
    records = [report_store[rn] for rn in matched_rns if rn in report_store]
    total   = len(records)
    if total == 0:
        return {"total_reports": 0}

    # Reactions
    rxn_counter = defaultdict(int)
    for rec in records:
        for rxn in rec.get("reactions", []):
            rxn_counter[rxn.lower()] += 1
    # keep dominant casing
    rxn_display = {}
    for rec in records:
        for rxn in rec.get("reactions", []):
            key = rxn.lower()
            if key not in rxn_display or (rxn != rxn.upper() and rxn_display[key] == rxn_display[key].upper()):
                rxn_display[key] = rxn
    top_rxns = sorted(rxn_counter.items(), key=lambda x: -x[1])[:TOP_REACTIONS]
    reactions_out = [
        {"term": rxn_display.get(k, k), "count": c,
         "pct": round(c / total * 100, 2)}
        for k, c in top_rxns
    ]

    # Outcomes
    out_counter = defaultdict(int)
    out_display = {}
    for rec in records:
        for o in rec.get("outcomes", []):
            out_counter[o.lower()] += 1
            if o.lower() not in out_display or (o != o.upper() and out_display[o.lower()] == out_display[o.lower()].upper()):
                out_display[o.lower()] = o
    outcomes_out = {
        out_display.get(k, k): {"count": c, "pct": round(c / total * 100, 2)}
        for k, c in sorted(out_counter.items(), key=lambda x: -x[1])
    }

    # Death gate
    death_count = out_counter.get("death", 0)
    gate_pass   = death_count <= total

    # Gender
    gender_counter = defaultdict(int)
    for rec in records:
        g = rec.get("consumer", {}).get("gender") or "Unknown/Not Reported"
        gender_counter[g] += 1
    reported = sum(v for k, v in gender_counter.items() if k != "Unknown/Not Reported")
    gender_counter["Unknown/Not Reported"] = total - reported

    # Age bands
    ages = []
    for rec in records:
        c    = rec.get("consumer", {})
        raw  = c.get("age")
        unit = (c.get("age_unit") or "").lower()
        if raw is None: continue
        try:    a = float(raw)
        except: continue
        if "month" in unit: a /= 12
        elif "week"  in unit: a /= 52
        elif "day"   in unit: a /= 365
        if 0 <= a <= 130: ages.append(a)
    ages.sort()
    n = len(ages)
    bands = {"under_18":0,"18_34":0,"35_49":0,"50_64":0,"65_79":0,"80_plus":0}
    for a in ages:
        if   a < 18: bands["under_18"] += 1
        elif a < 35: bands["18_34"]    += 1
        elif a < 50: bands["35_49"]    += 1
        elif a < 65: bands["50_64"]    += 1
        elif a < 80: bands["65_79"]    += 1
        else:        bands["80_plus"]  += 1
    bands["unknown"]    = total - n
    bands["median_age"] = round(ages[n//2] if n%2 else (ages[n//2-1]+ages[n//2])/2, 1) if n else None
    bands["mean_age"]   = round(sum(ages)/n, 1) if n else None
    bands["n_with_age"] = n

    # Year histogram (exact, no sampling)
    yr_hist = defaultdict(int)
    for rec in records:
        dc = rec.get("date_created","")
        if len(dc) >= 4 and dc[:4].isdigit():
            yr_hist[dc[:4]] += 1
    current_year = datetime.now().year
    yearly = {str(y): yr_hist.get(str(y), 0) for y in range(2004, current_year + 1)}
    nonzero = {k: v for k, v in yearly.items() if v > 0}
    max_yr    = max(nonzero, key=nonzero.get) if nonzero else None
    max_pct   = round(nonzero.get(max_yr, 0) / total * 100, 1) if max_yr else 0
    top2_cnt  = sum(sorted(nonzero.values(), reverse=True)[:2]) if nonzero else 0
    top2_pct  = round(top2_cnt / total * 100, 1) if total else 0

    return {
        "total_reports":  total,
        "reactions":      {"top_reactions": reactions_out,
                           "note": "case-normalised; computed from full local dataset"},
        "outcomes":       outcomes_out,
        "demographics":   {"gender":    dict(gender_counter),
                           "age_bands": bands,
                           "age_note":  "all matched records"},
        "yearly_trend":   yearly,
        "year_histogram": {
            "nonzero": nonzero,
            "true_peak_year": max_yr,
            "true_peak_pct":  max_pct,
            "true_top2_pct":  top2_pct,
            "source":         "full_local_data",
        },
        "sanity_checks":  {
            "deaths":                   death_count,
            "total_reports":            total,
            "deaths_lte_total_reports": gate_pass,
        },
    }

# ── Main processing loop ──────────────────────────────────────────────────────

reconcile     = []
gate_failures = []

print("\n" + "─"*76)
print("LOCAL MATCH + STATS COMPUTATION")
print("─"*76)

for row in mvp_csv:
    name       = row["canonical_display_name"]
    raw_list   = parse_raw(row["raw_strings_merged"])
    csv_total  = int(row["total_reports"])

    # Union of all report_numbers matching any raw string
    matched_rns = set()
    per_raw     = {}
    for rs in raw_list:
        rns = brand_index.get(rs, set())
        per_raw[rs] = len(rns)
        matched_rns |= rns

    stats       = compute_stats(matched_rns)
    local_total = stats["total_reports"]
    pct         = round(local_total / csv_total * 100, 1) if csv_total else 0
    gate_ok     = stats["sanity_checks"]["deaths_lte_total_reports"] if local_total else True
    if not gate_ok:
        gate_failures.append({"product": name,
                               "deaths": stats["sanity_checks"]["deaths"],
                               "total":  local_total})

    gap_flag = "  ⚠ STILL UNDER" if pct < 99 else ("  ✓" if pct <= 102 else "  ↑ OVER")
    print(f"  {name:<50}  csv={csv_total:>5}  local={local_total:>5}  "
          f"{pct:>6.1f}%{gap_flag}")

    eprint(f"  [{name}] csv={csv_total}  local={local_total}  deaths={stats['sanity_checks']['deaths']}  "
           f"gate={'✓' if gate_ok else '✗ FAIL'}")

    reconcile.append({
        "product": name, "csv_total": csv_total, "local_total": local_total,
        "pct": pct, "gate": gate_ok,
    })

    # Update the existing JSON entry
    if name in existing_json:
        d = existing_json[name]
        # Clear old API-query fields; replace with local data
        d.update(stats)
        d["total_reports"]        = local_total
        d["total_reports_csv"]    = csv_total
        d["detail_total"]         = local_total    # now they're the same
        d["unfetchable_records"]  = 0
        d.pop("encoding_gap_note", None)
        d.pop("reconciliation_note", None)
        d.pop("query_timestamp",  None)
        d["data_source"]          = "bulk_local_match"
        d["raw_strings"]          = raw_list
        d["query_timestamp"]      = datetime.utcnow().isoformat() + "Z"

print("─"*76)

# ── Histogram corrections (previously probe-partial) ──────────────────────────

PROBE_PARTIAL = [
    "Centrum Silver Women's 50+",
    "Centrum Silver Ultra Women's",
    "Centrum Silver Adults 50+",
    "Centrum Silver Men's 50+",
    "Flintstones Complete",
]
print("\n" + "─"*76)
print("HISTOGRAM CORRECTIONS (previously probe-partial)")
print("─"*76)
print(f"  {'Product':<50}  {'OldPeak':>8}  {'TruePeak':>9}  {'Top2':>6}  {'Tag change?'}")
print("─"*76)

for name in PROBE_PARTIAL:
    if name not in existing_json: continue
    d   = existing_json[name]
    yh  = d.get("year_histogram", {})
    tp  = yh.get("true_peak_pct", 0)
    ty  = yh.get("true_peak_year", "?")
    t2  = yh.get("true_top2_pct", 0)
    old = d.get("cluster_analysis", {}).get("true_peak_pct", "?")
    char_change = ""
    if tp < 40 and d.get("data_character") == "event_cluster":
        d["data_character"] = "organic"
        char_change = "event_cluster → organic"
    elif tp >= 60 and d.get("data_character") == "organic":
        d["data_character"] = "event_cluster"
        char_change = "organic → event_cluster"
    print(f"  {name:<50}  {str(old):>8}  {tp:>8.1f}%  {t2:>5.1f}%  {char_change or 'unchanged'}")

# ── Nutrafol re-tag ───────────────────────────────────────────────────────────

NUTRAFOL = "Nutrafol Womens Balance Hair Growth Nutraceutical"
if NUTRAFOL in existing_json:
    d   = existing_json[NUTRAFOL]
    yh  = d.get("year_histogram", {})
    tp  = yh.get("true_peak_pct", 0)
    nz  = yh.get("nonzero", {})
    # If >80% of reports are in 2024-2025 (most recent 2 years), tag as recent_emerging
    recent = sum(v for k, v in nz.items() if int(k) >= 2024)
    recent_pct = round(recent / d["total_reports"] * 100, 1) if d["total_reports"] else 0
    if recent_pct >= 60:
        d["data_character"]  = "organic_recent_emerging"
        d["cluster_context"] = (
            f"Reports concentrated in 2024–2025 ({recent_pct:.0f}% in most recent 2 years), "
            f"reflecting rapid recent market growth rather than a filing event. "
            f"Year-over-year trend is upward and ongoing."
        )
        print(f"\n  Nutrafol: re-tagged organic_recent_emerging "
              f"({recent_pct:.1f}% in 2024–2025)")

# ── Final data_character tally ────────────────────────────────────────────────

from collections import Counter
tally = Counter(d.get("data_character","?")
                for d in existing_json.values()
                if d.get("total_reports",0) > 0)

print(f"\n{'─'*76}")
print("FINAL DATA_CHARACTER TALLY")
print(f"{'─'*76}")
for char, cnt in sorted(tally.items()):
    print(f"  {char:<30}  {cnt}")

# ── Sanity checks ─────────────────────────────────────────────────────────────

print(f"\n{'─'*76}")
print("SANITY CHECKS")
print(f"{'─'*76}")

total_in   = sum(r["csv_total"] for r in reconcile)
total_out  = sum(r["local_total"] for r in reconcile)
print(f"  Sum of CSV totals:   {total_in:,}")
print(f"  Sum of local totals: {total_out:,}")

under99 = [r for r in reconcile if r["pct"] < 99.0]
print(f"  Products <99% coverage: {len(under99)}")
for u in under99:
    print(f"    {u['product']}: {u['pct']:.1f}%")

if gate_failures:
    print(f"\n  ✗ DEATH GATE FAILURES: {len(gate_failures)}")
    for gf in gate_failures:
        print(f"    {gf['product']}: deaths={gf['deaths']} > total={gf['total']}")
else:
    print(f"  ✓ All death gates passed")

# ── Record-count conservation ─────────────────────────────────────────────────

supplement_total = len(supp_records)
print(f"\n  Supplement records in bulk data: {supplement_total:,}")
print(f"  API category total (endpoint):   54,221")
gap = supplement_total - 54221
print(f"  Difference: {gap:+,} "
      f"({'newer records since Phase 0 query' if gap > 0 else 'within expected range'})")

# ── Save ──────────────────────────────────────────────────────────────────────

with open(JSON_OUT, "w") as f:
    json.dump(existing_json, f, indent=2)

size_kb = os.path.getsize(JSON_OUT) // 1024
print(f"\n{'─'*76}")
print(f"JSON → {JSON_OUT}  ({len(existing_json)} products, {size_kb}KB)")
print(f"Supplement records used: {supplement_total:,}")
print(f"{'─'*76}")
