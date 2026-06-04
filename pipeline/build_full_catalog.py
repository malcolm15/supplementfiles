#!/usr/bin/env python3
"""
Full-catalog pipeline — SupplementFiles.
Builds supplement_full_catalog.json (~268 branded products with ≥10 reports,
pages generated only for ≥25-report tier).

Architecture: entirely local — reads cached bulk ZIP, no live API queries.
Inputs:
  /tmp/fda_bulk/food-event-0001-of-0001.json.zip  (cached bulk CAERS data)
  /tmp/supplement_brands_v3.csv                    (normalized brand list from v2 pipeline)
Output:
  data/supplement_full_catalog.json                (keyed by canonical_display_name)

QA gates applied per product:
  - deaths ≤ total_reports (fails loudly)
  - count↔detail reconciliation logged (local match ≥95% of CSV count = pass)
  - true year histogram from full bulk data (no sampling bias)
  - cluster detection → data_character tagging
  - held flag for single-event artifacts (peak_pct ≥ 75%)
"""

import csv, json, re, sys, zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

BULK_CACHE   = Path("/tmp/fda_bulk")
CSV_PATH     = "/tmp/supplement_brands_v3.csv"
OUT_PATH     = Path(__file__).parent.parent / "data" / "supplement_full_catalog.json"
MIN_REPORTS  = 25          # standalone page threshold
TOP_REACTIONS = 30         # reactions to store per product
INDUSTRY_FILTER_OPTIONS = {
    "Vit/Min/Prot/Unconv Diet(Human/Animal)",
    "Vit/Min/Prot/Unconv Diet (Human/Animal)",
}
CURRENT_YEAR = datetime.now().year
TIMESTAMP    = datetime.utcnow().isoformat() + "Z"

eprint = lambda *a, **kw: print(*a, file=sys.stderr, **kw)
hr = lambda: print("─" * 76)

# ── Cluster context strings (editorially grounded, carried from MVP pipeline) ─

KNOWN_CLUSTER_CONTEXT = {
    "Hydroxycut": (
        "Reports concentrated in 2009, coinciding with FDA warning letters and "
        "the hepatotoxicity-linked market withdrawal that year."
    ),
    "Hydroxycut Regular": (
        "Reports concentrated in 2010–2011, during the post-recall period following "
        "Hydroxycut's 2009 market withdrawal and reformulation."
    ),
    "Hydroxycut Hardcore": (
        "Reports concentrated in 2010–2011, coinciding with the Hydroxycut recall "
        "and reformulation period."
    ),
    "Benefiber With Wheat Dextrin": (
        "Reports concentrated in 2013 with sequential report numbers, indicating "
        "a single batch filing rather than organic consumer reports."
    ),
    "Benefiber W Wheat Dextrin": (
        "Reports concentrated in 2013 with sequential report numbers, indicating "
        "a single batch filing event."
    ),
    "Super Beta Virility Boost": (
        "Reports concentrated in 2017–2018, likely reflecting launch-period adverse "
        "event collection for a new product line."
    ),
    "Triple Action Virility": (
        "Reports concentrated in 2015–2016 for this men's supplement product."
    ),
    "Super Beta Prostate P3 Advanced": (
        "Reports concentrated in 2018–2019, reflecting the initial reporting period "
        "following product launch."
    ),
    "All Day Energy Greens": (
        "Reports concentrated in 2016, consistent with a structured "
        "healthcare-provider reporting event; not organic consumer filing."
    ),
    "All Day Energy Greens Fruity": (
        "Reports concentrated in 2016, consistent with a structured "
        "healthcare-provider reporting event; not organic consumer filing."
    ),
    "Nutrafol Womens Balance Hair Growth Nutraceutical": (
        "Reports concentrated in 2024–2025, reflecting rapid recent market growth "
        "of the hair growth supplement category rather than a filing event."
    ),
}

KNOWN_ORGANIC_CONTEXT = {
    "5 Hour Energy": (
        "Reports spread across 2009–2025 with no single dominant year. Diverse "
        "reporter demographics and medically specific reactions (cardiac, hepatic) "
        "consistent with genuine organic consumer adverse event reporting."
    ),
    "Kratom": (
        "Reports span 2016–2025 with sustained recent filing. Ongoing regulatory "
        "activity (FDA import alerts, state bans) drives continued reporting."
    ),
}

# ─────────────────────────────────────────────────────────────────────────────
# 1. Load and parse CSV
# ─────────────────────────────────────────────────────────────────────────────

def parse_raw_strings(merged: str) -> list:
    """Parse 'RAW_STRING (COUNT) | RAW_STRING (COUNT)' into list of raw strings."""
    results = []
    for part in merged.split(" | "):
        mo = re.match(r"^(.+)\s+\(\d+\)\s*$", part.strip())
        if mo:
            results.append(mo.group(1))
    return results

print("Loading CSV…")
csv_rows = list(csv.DictReader(open(CSV_PATH)))

# All branded non-excluded products with ≥10 reports (we'll split on 25 later)
catalog_rows = [
    r for r in csv_rows
    if r.get("type") == "branded"
    and r.get("contamination_action", "") != "exclude"
    and int(r.get("total_reports", 0)) >= 10
]
catalog_rows.sort(key=lambda x: -int(x["total_reports"]))

print(f"  Branded non-excluded ≥10 reports: {len(catalog_rows)}")
print(f"  Of which ≥25 reports (page tier): {sum(1 for r in catalog_rows if int(r['total_reports']) >= 25)}")

# ─────────────────────────────────────────────────────────────────────────────
# 2. Load bulk CAERS data
# ─────────────────────────────────────────────────────────────────────────────

print("\nLoading bulk CAERS data…")
all_records_raw = []
for zip_path in sorted(BULK_CACHE.glob("*.zip")):
    eprint(f"  Reading {zip_path.name}…")
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            with zf.open(member) as f:
                data = json.load(f)
                all_records_raw.extend(data["results"])

print(f"  Total raw records: {len(all_records_raw):,}")

# Filter to supplement industry
supp_records = [
    rec for rec in all_records_raw
    if any(
        p.get("industry_name", "") in INDUSTRY_FILTER_OPTIONS
        for p in rec.get("products", [])
    )
]
print(f"  Supplement records: {len(supp_records):,}")

# Build brand index: exact raw string → set of report_numbers
# Also store report_number → full record
brand_index  = defaultdict(set)
report_store = {}

for rec in supp_records:
    rn = rec.get("report_number", "")
    if not rn:
        continue
    report_store[rn] = rec
    for prod in rec.get("products", []):
        nb = prod.get("name_brand", "")
        if nb:
            brand_index[nb].add(rn)

print(f"  Distinct raw brand strings: {len(brand_index):,}")

# ─────────────────────────────────────────────────────────────────────────────
# 3. Compute per-product stats
# ─────────────────────────────────────────────────────────────────────────────

def compute_stats(matched_rns: set) -> dict:
    records = [report_store[rn] for rn in matched_rns if rn in report_store]
    total   = len(records)
    if total == 0:
        return {"total_reports": 0}

    # Reactions — case-normalise
    rxn_counter = defaultdict(int)
    rxn_display = {}
    for rec in records:
        for rxn in rec.get("reactions", []):
            key = rxn.lower()
            rxn_counter[key] += 1
            if key not in rxn_display or (
                rxn != rxn.upper() and rxn_display.get(key, "") == rxn_display.get(key, "").upper()
            ):
                rxn_display[key] = rxn
    top_rxns = sorted(rxn_counter.items(), key=lambda x: -x[1])[:TOP_REACTIONS]
    reactions_out = [
        {"term": rxn_display.get(k, k), "count": c, "pct": round(c / total * 100, 2)}
        for k, c in top_rxns
    ]

    # Outcomes — case-normalise
    out_counter = defaultdict(int)
    out_display = {}
    for rec in records:
        for o in rec.get("outcomes", []):
            key = o.lower()
            out_counter[key] += 1
            if key not in out_display or (
                o != o.upper() and out_display.get(key, "") == out_display.get(key, "").upper()
            ):
                out_display[key] = o
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
        g = (rec.get("consumer") or {}).get("gender") or "Unknown/Not Reported"
        gender_counter[g] += 1
    reported = sum(v for k, v in gender_counter.items() if k != "Unknown/Not Reported")
    gender_counter["Unknown/Not Reported"] = total - reported

    # Age bands
    ages = []
    for rec in records:
        c    = rec.get("consumer") or {}
        raw  = c.get("age")
        unit = (c.get("age_unit") or "").lower()
        if raw is None:
            continue
        try:
            a = float(raw)
        except (ValueError, TypeError):
            continue
        if "month" in unit:
            a /= 12
        elif "week" in unit:
            a /= 52
        elif "day" in unit:
            a /= 365
        if 0 <= a <= 130:
            ages.append(a)
    ages.sort()
    n = len(ages)
    bands = {"under_18": 0, "18_34": 0, "35_49": 0, "50_64": 0, "65_79": 0, "80_plus": 0}
    for a in ages:
        if   a < 18:  bands["under_18"] += 1
        elif a < 35:  bands["18_34"]    += 1
        elif a < 50:  bands["35_49"]    += 1
        elif a < 65:  bands["50_64"]    += 1
        elif a < 80:  bands["65_79"]    += 1
        else:         bands["80_plus"]  += 1
    bands["unknown"]    = total - n
    bands["median_age"] = (
        round(ages[n // 2] if n % 2 else (ages[n // 2 - 1] + ages[n // 2]) / 2, 1)
        if n else None
    )
    bands["mean_age"]   = round(sum(ages) / n, 1) if n else None
    bands["n_with_age"] = n

    # True year histogram — computed from full local data, no probe bias
    yr_hist = defaultdict(int)
    for rec in records:
        dc = (rec.get("date_created") or "")
        if len(dc) >= 4 and dc[:4].isdigit():
            yr_hist[dc[:4]] += 1
    yearly   = {str(y): yr_hist.get(str(y), 0) for y in range(2004, CURRENT_YEAR + 1)}
    nonzero  = {k: v for k, v in yearly.items() if v > 0}
    max_yr   = max(nonzero, key=nonzero.get) if nonzero else None
    max_pct  = round(nonzero.get(max_yr, 0) / total * 100, 1) if max_yr else 0.0
    top2_cnt = sum(sorted(nonzero.values(), reverse=True)[:2]) if nonzero else 0
    top2_pct = round(top2_cnt / total * 100, 1) if total else 0.0

    return {
        "total_reports":  total,
        "reactions":      {"top_reactions": reactions_out, "note": "case-normalised; computed from full local dataset"},
        "outcomes":       outcomes_out,
        "demographics":   {
            "gender":    dict(gender_counter),
            "age_bands": bands,
            "age_note":  "all matched records",
        },
        "yearly_trend":   yearly,
        "year_histogram": {
            "nonzero":       nonzero,
            "true_peak_year": max_yr,
            "true_peak_pct":  max_pct,
            "true_top2_pct":  top2_pct,
            "source":         "full_local_data",
        },
        "sanity_checks": {
            "deaths":                   death_count,
            "total_reports":            total,
            "deaths_lte_total_reports": gate_pass,
        },
    }

# ─────────────────────────────────────────────────────────────────────────────
# 4. Tag data_character and generate cluster_context
# ─────────────────────────────────────────────────────────────────────────────

def tag_data_character(name: str, stats: dict) -> tuple:
    """Returns (data_character, cluster_context)."""
    yh       = stats.get("year_histogram", {})
    peak_pct = yh.get("true_peak_pct", 0.0)
    top2_pct = yh.get("true_top2_pct", 0.0)
    peak_yr  = yh.get("true_peak_year")
    nonzero  = yh.get("nonzero", {})
    total    = stats.get("total_reports", 0)

    # Recent-emerging: <40% peak AND ≥60% of reports in last 2 years
    recent_yrs  = {k: v for k, v in nonzero.items() if int(k) >= CURRENT_YEAR - 1}
    recent_pct  = round(sum(recent_yrs.values()) / total * 100, 1) if total else 0.0

    # Held: extreme single-event concentration
    if peak_pct >= 75.0 and top2_pct >= 88.0:
        context = (
            f"Reports extremely concentrated in {peak_yr} ({peak_pct:.0f}% of total), "
            "suggesting a single filing event rather than organic consumer reporting. "
            "Held pending editorial review."
        )
        return "held", context

    # Known cluster/organic overrides from MVP editorial
    if name in KNOWN_CLUSTER_CONTEXT:
        if peak_pct >= 35.0:
            return "event_cluster", KNOWN_CLUSTER_CONTEXT[name]
        # If peak dropped below threshold via true histogram, demote to organic
        return "organic", (
            KNOWN_ORGANIC_CONTEXT.get(name) or
            f"Reports distributed across multiple years consistent with organic consumer reporting."
        )

    if name in KNOWN_ORGANIC_CONTEXT:
        return "organic", KNOWN_ORGANIC_CONTEXT[name]

    # Cluster detection
    if peak_pct >= 35.0:
        yrs_with_data = sorted(k for k, v in nonzero.items() if v > 0)
        first_yr = yrs_with_data[0] if yrs_with_data else peak_yr
        last_yr  = yrs_with_data[-1] if yrs_with_data else peak_yr
        span     = f"{first_yr}–{last_yr}" if first_yr != last_yr else first_yr

        if peak_pct >= 60.0:
            context = (
                f"Reports heavily concentrated in {peak_yr} ({peak_pct:.0f}% of total). "
                "High concentration may reflect a recall, enforcement action, batch filing, "
                "or litigation-driven reporting rather than ongoing consumer use."
            )
        else:
            context = (
                f"Reports concentrated in {peak_yr} ({peak_pct:.0f}% of total, "
                f"spanning {span}), suggesting a reporting event during that period "
                "rather than evenly distributed consumer use."
            )
        return "event_cluster", context

    # Organic recent-emerging
    if recent_pct >= 60.0 and peak_pct < 40.0:
        recent_yr_list = sorted(recent_yrs.keys())
        yr_range = f"{recent_yr_list[0]}–{recent_yr_list[-1]}" if len(recent_yr_list) > 1 else recent_yr_list[0]
        context = (
            f"Reports concentrated in {yr_range} ({recent_pct:.0f}% of total), "
            "suggesting a recently growing or newly prominent product rather than "
            "a historical filing event."
        )
        return "organic_recent_emerging", context

    # Default: organic
    yrs_with_data = sorted(k for k, v in nonzero.items() if v > 0)
    first_yr = yrs_with_data[0] if yrs_with_data else "N/A"
    last_yr  = yrs_with_data[-1] if yrs_with_data else "N/A"
    context  = (
        f"Reports distributed across {first_yr}–{last_yr} "
        "consistent with organic consumer reporting."
    )
    return "organic", context

# ─────────────────────────────────────────────────────────────────────────────
# 5. Main processing loop
# ─────────────────────────────────────────────────────────────────────────────

hr()
print("PROCESSING ALL BRANDED ≥10-REPORT PRODUCTS")
hr()
print(f"  {'Product':<52} {'CSV':>5} {'Local':>6} {'Cov%':>6} {'Deaths':>7} {'Gate':>5} {'Char'}")
hr()

catalog_out   = {}
reconcile     = []
gate_failures = []
held_list     = []
flag_list     = []   # event_cluster / organic_recent_emerging for review

for row in catalog_rows:
    name       = row["canonical_display_name"]
    csv_total  = int(row["total_reports"])
    raw_list   = parse_raw_strings(row.get("raw_strings_merged", ""))
    brand_fam  = row.get("brand_family", "") or None
    cont_flag  = row.get("contamination_flag", "") or ""

    # Match raw strings against bulk brand_index
    matched_rns = set()
    for rs in raw_list:
        matched_rns |= brand_index.get(rs, set())

    stats       = compute_stats(matched_rns)
    local_total = stats["total_reports"]
    pct         = round(local_total / csv_total * 100, 1) if csv_total else 0.0

    gate_ok     = stats["sanity_checks"]["deaths_lte_total_reports"] if local_total else True
    deaths      = stats["sanity_checks"]["deaths"] if local_total else 0

    if not gate_ok:
        gate_failures.append({"product": name, "deaths": deaths, "total": local_total})

    # data_character tagging
    char, context = tag_data_character(name, stats)

    page_eligible = (
        csv_total >= MIN_REPORTS
        and char != "held"
    )

    cov_flag = "✓" if pct >= 99.0 else ("⚠" if pct >= 90.0 else "✗")
    print(f"  {name:<52} {csv_total:>5} {local_total:>6} {pct:>5.1f}%{cov_flag} {deaths:>7} "
          f"{'✓' if gate_ok else '✗ FAIL':>5} {char}")

    reconcile.append({
        "product": name, "csv_total": csv_total, "local_total": local_total,
        "pct": pct, "gate": gate_ok,
    })

    if char == "held":
        held_list.append({"product": name, "total": local_total, "reason": context})
    elif char in ("event_cluster", "organic_recent_emerging"):
        flag_list.append({"product": name, "total": local_total, "char": char, "context": context})

    # Build output record
    catalog_out[name] = {
        "canonical_display_name": name,
        "normalized_key":         row.get("normalized_key", ""),
        "type":                   "branded",
        "brand_family":           brand_fam,
        "contamination_flag":     cont_flag,
        "total_reports":          local_total,
        "total_reports_csv":      csv_total,
        "page_eligible":          page_eligible,
        "raw_strings":            raw_list,
        "data_character":         char,
        "cluster_context":        context,
        **{k: v for k, v in stats.items() if k != "total_reports"},
        "data_source":            "bulk_local_match",
        "query_timestamp":        TIMESTAMP,
    }

hr()

# ─────────────────────────────────────────────────────────────────────────────
# 6. Sanity check summary
# ─────────────────────────────────────────────────────────────────────────────

hr()
print("SANITY CHECKS")
hr()

page_eligible_n = sum(1 for v in catalog_out.values() if v.get("page_eligible"))
print(f"  Products processed:      {len(catalog_out)}")
print(f"  Page-eligible (≥25, not held): {page_eligible_n}")
print(f"  Held for review:         {len(held_list)}")

under95 = [r for r in reconcile if r["pct"] < 95.0]
print(f"\n  Count↔detail reconciliation:")
print(f"    ≥99% coverage:  {sum(1 for r in reconcile if r['pct'] >= 99.0)}")
print(f"    95–99%:         {sum(1 for r in reconcile if 95.0 <= r['pct'] < 99.0)}")
print(f"    <95% (flagged): {len(under95)}")
for u in under95:
    print(f"      {u['product']}: {u['pct']:.1f}% (csv={u['csv_total']}, local={u['local_total']})")

if gate_failures:
    print(f"\n  ✗ DEATH GATE FAILURES — BLOCKING: {len(gate_failures)}")
    for gf in gate_failures:
        print(f"    {gf['product']}: deaths={gf['deaths']} > total={gf['total']}")
    sys.exit(1)   # fail loudly
else:
    print(f"\n  ✓ All death gates passed")

# data_character tally
from collections import Counter
tally = Counter(v["data_character"] for v in catalog_out.values())
print(f"\n  data_character tally:")
for char, cnt in sorted(tally.items()):
    print(f"    {char:<30} {cnt}")

hr()
print("HELD FOR REVIEW (not published)")
hr()
for h in held_list:
    print(f"  {h['product']} ({h['total']} reports)")
    print(f"    {h['reason'][:100]}")

hr()
print("EVENT_CLUSTER / RECENT_EMERGING — cluster context applied")
hr()
for f in flag_list:
    print(f"  [{f['char']}] {f['product']} ({f['total']} reports)")
    print(f"    {f['context'][:120]}")

# ─────────────────────────────────────────────────────────────────────────────
# 7. Write output
# ─────────────────────────────────────────────────────────────────────────────

OUT_PATH.parent.mkdir(exist_ok=True)
with open(OUT_PATH, "w") as f:
    json.dump(catalog_out, f, indent=2)

size_kb = OUT_PATH.stat().st_size // 1024
hr()
print(f"Output: {OUT_PATH}")
print(f"  {len(catalog_out)} products, {size_kb} KB")
print(f"  {page_eligible_n} page-eligible, {len(held_list)} held")
hr()
