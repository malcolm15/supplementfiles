#!/usr/bin/env python3
"""
Parts 2, 3, 4: + fix re-fetch, cluster detection, anomaly investigation.

Usage:
    python3 refetch_plus_and_analysis.py [--skip-refetch]
"""

import csv, json, re, sys, time, urllib.request, urllib.parse
from collections import defaultdict
from datetime import datetime

CSV_PATH  = "/tmp/supplement_brands_v3.csv"
JSON_IN   = "/tmp/supplement_mvp_detail.json"
JSON_OUT  = "/tmp/supplement_mvp_detail_v2.json"
BASE_URL  = "https://api.fda.gov/food/event.json"
DELAY     = 1.7
SKIP_REFETCH = "--skip-refetch" in sys.argv

eprint = lambda *a, **kw: print(*a, file=sys.stderr, **kw)
call_n = [0]

# ── API ───────────────────────────────────────────────────────────────────────

def api_get(params: dict) -> dict:
    if call_n[0] > 0: time.sleep(DELAY)
    call_n[0] += 1
    qs = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    url = f"{BASE_URL}?{qs}"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=25) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            if e.code == 429: eprint("  429, waiting 15s…"); time.sleep(15); continue
            if e.code in (400, 404): return {}
            raise RuntimeError(f"HTTP {e.code}: {body[:200]}")
        except Exception:
            if attempt == 2: raise
            time.sleep(4)
    raise RuntimeError("retries exhausted")

def search_for(raw_brand: str) -> str:
    """Exact brand search with Lucene + escaped as \\+."""
    escaped = raw_brand.replace("+", r"\+")
    return f'products.name_brand.exact:"{escaped}"'

def get_total(raw_brand: str) -> int:
    d = api_get({"search": search_for(raw_brand), "limit": "1"})
    return d.get("meta", {}).get("results", {}).get("total", 0)

def get_count(raw_brand: str, field: str, limit: int = 100) -> list:
    d = api_get({"search": search_for(raw_brand), "count": field, "limit": str(limit)})
    return d.get("results", [])

def get_records(raw_brand: str, skip: int, limit: int) -> tuple:
    d = api_get({"search": search_for(raw_brand), "limit": str(limit), "skip": str(skip)})
    return d.get("meta", {}).get("results", {}).get("total", 0), d.get("results", [])

def agg(per: list) -> list:
    m = {}
    for results in per:
        for item in results:
            k = item["term"].lower()
            if k not in m: m[k] = {"term": item["term"], "count": 0}
            m[k]["count"] += item["count"]
            if item["term"] != item["term"].upper() and m[k]["term"] == m[k]["term"].upper():
                m[k]["term"] = item["term"]
    return sorted(m.values(), key=lambda x: -x["count"])

def parse_raw_strings(merged: str) -> list:
    result = []
    for part in merged.split(" | "):
        mo = re.match(r"^(.+)\s+\(\d+\)\s*$", part.strip())
        if mo: result.append(mo.group(1))
    return result

def bucket_ages(records: list) -> dict:
    ages = []
    for rec in records:
        c = rec.get("consumer", {}); raw = c.get("age"); unit = (c.get("age_unit") or "").lower()
        if raw is None: continue
        try: a = float(raw)
        except: continue
        if "month" in unit: a /= 12
        elif "week" in unit: a /= 52
        elif "day"  in unit: a /= 365
        if 0 <= a <= 130: ages.append(a)
    ages.sort(); n = len(ages)
    if not n:
        return {"under_18":0,"18_34":0,"35_49":0,"50_64":0,"65_79":0,"80_plus":0,
                "unknown":len(records),"median_age":None,"mean_age":None,"n_with_age":0}
    bands = {"under_18":0,"18_34":0,"35_49":0,"50_64":0,"65_79":0,"80_plus":0}
    for a in ages:
        if   a < 18: bands["under_18"] += 1
        elif a < 35: bands["18_34"]    += 1
        elif a < 50: bands["35_49"]    += 1
        elif a < 65: bands["50_64"]    += 1
        elif a < 80: bands["65_79"]    += 1
        else:        bands["80_plus"]  += 1
    bands["unknown"]    = len(records) - n
    bands["median_age"] = round(ages[n//2] if n%2 else (ages[n//2-1]+ages[n//2])/2, 1)
    bands["mean_age"]   = round(sum(ages)/n, 1)
    bands["n_with_age"] = n
    return bands

def parse_trend(per: list) -> dict:
    yearly = defaultdict(int)
    for results in per:
        for item in results:
            t = str(item["term"])
            if len(t) >= 4 and t[:4].isdigit(): yearly[t[:4]] += item["count"]
    yr = datetime.now().year
    return {str(y): yearly.get(str(y), 0) for y in range(2004, yr+1)}

# ── Load data ─────────────────────────────────────────────────────────────────

csv_rows = list(csv.DictReader(open(CSV_PATH)))
mvp_csv  = [r for r in csv_rows
            if r["type"] == "branded"
            and r.get("contamination_action","") != "exclude"
            and int(r["total_reports"]) >= 100]
mvp_csv.sort(key=lambda x: -int(x["total_reports"]))

data = json.load(open(JSON_IN))

# ── Identify products with + in raw strings ───────────────────────────────────

def raw_has_plus(merged: str) -> bool:
    return "+" in merged

plus_products = [r for r in mvp_csv if raw_has_plus(r["raw_strings_merged"])]
print(f"\nProducts with '+' in raw strings: {len(plus_products)}")
for r in plus_products:
    raw_list = parse_raw_strings(r["raw_strings_merged"])
    plus_raws = [s for s in raw_list if "+" in s]
    print(f"  {r['canonical_display_name']:<50}  ({len(plus_raws)} raw strings with +)")

if SKIP_REFETCH:
    print("\n[--skip-refetch] Skipping API calls. Using existing JSON.")
else:
    # ── Part 2: Re-fetch + products with escaped + ───────────────────────────────
    sep = "─" * 72
    print(f"\n{sep}")
    print("PART 2 — RE-FETCH WITH \\+ ESCAPING")
    print(sep)
    changes = []

    for product_row in plus_products:
        name     = product_row["canonical_display_name"]
        norm_key = product_row["normalized_key"]
        raw_list = parse_raw_strings(product_row["raw_strings_merged"])
        csv_total = int(product_row["total_reports"])

        eprint(f"\n  [{name}]  csv={csv_total}  raw_strings={len(raw_list)}")

        old_total = data.get(name, {}).get("total_reports", 0)

        # Totals per raw string
        totals = [get_total(rs) for rs in raw_list]
        new_total = sum(totals)

        if new_total == 0:
            eprint(f"    → 0 results, skipping")
            continue

        delta = new_total - old_total
        flag = " ⚠ CHANGED" if abs(delta) > 2 else " ✓ stable"
        print(f"  {name:<50}  old={old_total:>5}  new={new_total:>5}  Δ={delta:+d}{flag}")
        if abs(delta) > 2:
            changes.append({"product": name, "old": old_total, "new": new_total, "delta": delta})

        # Re-fetch full detail
        rxn_r  = [get_count(rs, "reactions.exact", 100)        for rs in raw_list]
        out_r  = [get_count(rs, "outcomes.exact", 50)          for rs in raw_list]
        gen_r  = [get_count(rs, "consumer.gender.exact", 10)   for rs in raw_list]
        trd_r  = [get_count(rs, "date_created.exact", 1000)    for rs in raw_list]

        # Age records (first raw string, up to 300)
        age_recs = []
        remaining = 300
        for rs in raw_list:
            if remaining <= 0: break
            want = min(remaining, 100)
            _, recs = get_records(rs, 0, want)
            age_recs.extend(recs); remaining -= len(recs)

        outcomes_m = {r["term"]: {"count": r["count"], "pct": round(r["count"]/new_total*100, 2)}
                      for r in agg(out_r)}
        death_count = outcomes_m.get("Death", {}).get("count", 0)
        gate_pass = death_count <= new_total
        eprint(f"    death gate: {death_count}/{new_total}  {'✓' if gate_pass else '✗ FAIL'}")

        gender_m = {r["term"]: r["count"] for r in agg(gen_r)}
        gender_m["Unknown/Not Reported"] = new_total - sum(gender_m.values())

        reactions_m = [{"term": r["term"], "count": r["count"],
                         "pct": round(r["count"]/new_total*100, 2)}
                        for r in agg(rxn_r)[:30]]

        data[name] = {
            "canonical_display_name": name,
            "normalized_key":   norm_key,
            "type": product_row["type"],
            "brand_family": product_row["brand_family"],
            "contamination_flag": product_row.get("contamination_flag",""),
            "total_reports":   new_total,
            "total_reports_csv": csv_total,
            "page_eligible": True,
            "raw_strings":   raw_list,
            "query_timestamp": datetime.utcnow().isoformat()+"Z",
            "reactions": {"top_reactions": reactions_m, "note": "case-normalised; + escaped"},
            "outcomes":  outcomes_m,
            "demographics": {"gender": gender_m, "age_bands": bucket_ages(age_recs),
                             "age_note": "up to 300 records"},
            "yearly_trend": parse_trend(trd_r),
            "sanity_checks": {"deaths": death_count, "total_reports": new_total,
                              "deaths_lte_total_reports": gate_pass}
        }

    # Add the newly-merged "Centrum Silver Womens 50+" as a redirect note
    # (it no longer exists as its own entity — merged into Women's 50+)
    if "Centrum Silver Womens 50+" in data:
        data["Centrum Silver Womens 50+"]["redirect_to"] = "Centrum Silver Women's 50+"
        data["Centrum Silver Womens 50+"]["query_note"] = (
            "Merged into 'Centrum Silver Women\\'s 50+' in v3 normalizer. "
            "Stub retained for redirect only."
        )

    print(f"\n  Changes flagged: {len(changes)}")
    for c in changes:
        print(f"    ⚠  {c['product']}: {c['old']} → {c['new']}  (Δ={c['delta']:+d})")
    if not changes:
        print("    None — + escaping did not meaningfully change any counts.")

# ── Part 3: Cluster detection ─────────────────────────────────────────────────

sep = "─" * 72
print(f"\n{sep}")
print("PART 3 — CLUSTER DETECTION (yearly distribution)")
print(sep)
print(f"{'Product':<50} {'Rpts':>5}  {'MaxYr':>6}  {'MaxPct':>7}  {'Flag'}")
print(sep)

flagged_clusters = []
for name in sorted(data, key=lambda n: -data[n].get("total_reports", 0)):
    d  = data[name]
    tr = d.get("total_reports", 0)
    yt = d.get("yearly_trend")
    if not yt or tr == 0: continue

    yearly = {yr: cnt for yr, cnt in yt.items() if cnt > 0}
    if not yearly: continue

    max_yr  = max(yearly, key=yearly.get)
    max_cnt = yearly[max_yr]
    max_pct = round(max_cnt / tr * 100, 1)

    # Concentration score: top-2-year pct
    top2 = sum(sorted(yearly.values(), reverse=True)[:2])
    top2_pct = round(top2 / tr * 100, 1)

    flag = ""
    if max_pct > 50:  flag += f"⚠ {max_pct:.0f}% in {max_yr}"
    elif max_pct > 35: flag += f"↑ {max_pct:.0f}% in {max_yr}"

    marker = "  ⚠" if max_pct > 50 else ("  ↑" if max_pct > 35 else "")
    print(f"  {name:<48} {tr:>5}  {max_yr:>6}  {max_pct:>6.1f}%{marker}")

    if max_pct > 50:
        flagged_clusters.append({
            "product": name, "total_reports": tr,
            "max_year": max_yr, "max_year_count": max_cnt, "max_year_pct": max_pct,
            "top2_years_pct": top2_pct,
            "yearly": {k: v for k, v in sorted(yearly.items())}
        })

print(sep)
print(f"\nProducts with >50% reports in a single year: {len(flagged_clusters)}")
for fc in flagged_clusters:
    print(f"\n  {fc['product']}  ({fc['total_reports']} reports)")
    print(f"  Max year: {fc['max_year']}  ({fc['max_year_count']} reports = {fc['max_year_pct']:.1f}%)")
    print(f"  Full trend: {fc['yearly']}")

# ── Part 4: Anomaly investigation ─────────────────────────────────────────────

sep = "─" * 72
print(f"\n{sep}")
print("PART 4 — ANOMALY INVESTIGATION (sample records)")
print(sep)

INVESTIGATE = {
    "All Day Energy Greens":       "ALL DAY ENERGY GREENS",
    "All Day Energy Greens Fruity":"ALL DAY ENERGY GREENS FRUITY",
    "Benefiber With Wheat Dextrin":None,  # pull raw strings from CSV
    "5 Hour Energy":               None,
}

def get_sample_records(brand: str, n: int = 20) -> list:
    d = api_get({"search": search_for(brand), "limit": str(n), "skip": "0"})
    return d.get("results", [])

for display_name, override_raw in INVESTIGATE.items():
    eprint(f"\n  Investigating: {display_name}")
    # Find raw strings
    if override_raw:
        raw_strings_to_use = [override_raw]
    else:
        row = next((r for r in mvp_csv if r["canonical_display_name"] == display_name), None)
        if not row: print(f"\n  {display_name}: not found in CSV"); continue
        raw_strings_to_use = parse_raw_strings(row["raw_strings_merged"])[:2]

    all_records = []
    for rs in raw_strings_to_use:
        recs = get_sample_records(rs, 20)
        all_records.extend(recs)
        if len(all_records) >= 20: break

    print(f"\n{'─'*40}")
    print(f"  {display_name.upper()} — {len(all_records)} sampled records")
    print(f"{'─'*40}")

    # Date distribution
    year_counts = defaultdict(int)
    for rec in all_records:
        dc = rec.get("date_created","")
        if len(dc) >= 4: year_counts[dc[:4]] += 1
    print(f"  Report years: {dict(sorted(year_counts.items()))}")

    # Outcome distribution
    outcome_counts = defaultdict(int)
    for rec in all_records:
        for o in rec.get("outcomes", []):
            outcome_counts[o] += 1
    print(f"  Outcomes in sample: {dict(sorted(outcome_counts.items(), key=lambda x:-x[1])[:8])}")

    # Report number patterns
    rpt_prefixes = defaultdict(int)
    for rec in all_records:
        rn = rec.get("report_number","")
        prefix = rn[:4] if rn else "?"
        rpt_prefixes[prefix] += 1
    print(f"  Report # prefixes: {dict(rpt_prefixes)}")

    # Consumer demographics
    genders = defaultdict(int)
    for rec in all_records:
        genders[rec.get("consumer",{}).get("gender","?") or "?"] += 1
    print(f"  Gender: {dict(genders)}")

    # Reaction diversity
    all_rxns = []
    for rec in all_records:
        all_rxns.extend(rec.get("reactions",[]))
    rxn_counts = defaultdict(int)
    for r in all_rxns:
        rxn_counts[r.lower()] += 1
    top_rxns = sorted(rxn_counts.items(), key=lambda x:-x[1])[:8]
    print(f"  Top reactions in sample: {dict(top_rxns)}")

    # Product role breakdown
    roles = defaultdict(int)
    for rec in all_records:
        for p in rec.get("products",[]):
            roles[p.get("role","?")] += 1
    print(f"  Product roles: {dict(roles)}")

    # Date range
    dates = sorted([r.get("date_created","") for r in all_records if r.get("date_created")])
    if dates: print(f"  Date range in sample: {dates[0]} → {dates[-1]}")

    # Flag identical reactions (template-filing signal)
    rxn_sets = [frozenset(r.get("reactions",[])) for r in all_records]
    if rxn_sets:
        most_common_rxn_set = max(set(rxn_sets), key=rxn_sets.count)
        freq = rxn_sets.count(most_common_rxn_set)
        if freq > 3:
            print(f"  ⚠  {freq}/{len(all_records)} records share identical reaction set: {sorted(most_common_rxn_set)[:5]}")

print(f"\n{sep}")

# ── Save JSON ─────────────────────────────────────────────────────────────────
with open(JSON_OUT, "w") as f:
    json.dump(data, f, indent=2)
print(f"\nJSON saved → {JSON_OUT}  ({len(data)} products)")
