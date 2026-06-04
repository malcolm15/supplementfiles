#!/usr/bin/env python3
"""
Supplement brand normalization layer — SupplementSignal Phase 1.

Fetches top 1,000 brand strings from openFDA CAERS, normalizes into
canonical product entities, classifies, flags contamination, and outputs
an auditable CSV plus summary stats.

Usage:
    python3 normalize_brands.py > brands_normalized.csv
    python3 normalize_brands.py --stats-only
"""

import csv
import json
import re
import sys
import urllib.request
from collections import defaultdict
from typing import Optional

# ── API ──────────────────────────────────────────────────────────────────────

API_URL = (
    "https://api.fda.gov/food/event.json"
    "?search=products.industry_name.exact:"
    "%22Vit%2FMin%2FProt%2FUnconv+Diet%28Human%2FAnimal%29%22"
    "&count=products.name_brand.exact&limit=1000"
)

# ── Normalization patterns ────────────────────────────────────────────────────

_FORM_ALTS = "|".join([
    r"tablets?", r"capsules?", r"caplets?",
    r"soft\s*gels?", r"softgels?", r"gel\s*caps?", r"gelcaps?",
    r"gumm(?:y|ies)", r"chewables?", r"chews?",
    r"liquid", r"powder", r"drops?", r"lozenges?", r"sprays?",
    r"film[\s-]?coated", r"extended[\s-]?release",
    r"rapid[\s-]?release", r"time[\s-]?release", r"sustained[\s-]?release",
    r"\ber\b", r"\bsr\b",
    r"gel caps?",
])
FORM_SUFFIX_RE = re.compile(r"\s+(?:" + _FORM_ALTS + r")\s*$", re.IGNORECASE)
SIZE_RE = re.compile(
    r"\s+\d+\s*(?:ct|count|mg|mcg|iu|oz|g\b|ml|lb|lbs|gram[s]?|pack|pk)\s*$",
    re.IGNORECASE,
)
ADMIN_RE = re.compile(
    r"\s+no\s+(?:upc|preferred?\s*(?:name|brand)?)\s*$"
    r"|\s+\((?:no\s+pref|no\s+brand|nch)\)\s*$",
    re.IGNORECASE,
)

# ── Generic ingredient set (normalized/lowercased) ────────────────────────────
# These get routed to ingredient aggregation pages, not brand pages.

# Precomputed compressed-key index (no spaces, no hyphens) for fuzzy ingredient matching.
# Populated after GENERIC_INGREDIENTS is defined — catches coq10/co-q10/co q10/coq-10 etc.
_GENERIC_COMPRESSED: dict[str, str] = {}

GENERIC_INGREDIENTS = {
    # vitamins
    "vitamin a", "vitamin b", "vitamin b complex", "vitamin b-complex",
    "vitamin b1", "vitamin b2", "vitamin b3", "vitamin b5", "vitamin b6",
    "vitamin b7", "vitamin b9", "vitamin b12", "vitamin c", "vitamin d",
    "vitamin d2", "vitamin d3", "vitamin e", "vitamin k", "vitamin k2",
    "b complex", "b-complex", "b12", "b6", "d3", "d2", "k2",
    # multi-vitamin variants
    "multivitamin", "multivitamins", "multi vitamin", "multi-vitamin",
    "multi vitamins", "multi-vitamins", "vitamins", "multi", "multiminerals",
    # minerals
    "calcium", "magnesium", "zinc", "iron", "potassium", "selenium",
    "chromium", "copper", "manganese", "molybdenum", "iodine", "phosphorus",
    "boron", "vanadium",
    # fatty acids
    "fish oil", "omega 3", "omega-3", "omega 3 fatty acids", "omega 6",
    "omega-6", "dha", "epa", "krill oil", "cod liver oil", "flaxseed oil",
    "flaxseed", "evening primrose oil",
    # b-vitamins standalone
    "biotin", "folic acid", "folate", "niacin", "riboflavin", "thiamine",
    "pantothenic acid", "choline", "inositol",
    # common actives
    "coq10", "co-q10", "coenzyme q10", "ubiquinol", "ubiquinone",
    "melatonin", "probiotic", "probiotics", "prebiotic", "prebiotics",
    "turmeric", "curcumin", "ginger", "garlic", "echinacea",
    "ginkgo biloba", "ginkgo", "ginseng", "ashwagandha",
    "valerian", "valerian root", "milk thistle", "saw palmetto",
    "black cohosh", "maca", "maca root",
    "glucosamine", "chondroitin", "msm", "collagen",
    "protein", "whey protein", "whey", "casein", "creatine",
    "l-carnitine", "carnitine", "l-glutamine", "glutamine",
    "l-arginine", "arginine", "l-lysine", "lysine",
    "5-htp", "5 htp", "sam-e", "same",
    # fiber
    "fiber", "psyllium", "psyllium husk",
    # herbal
    "green tea", "green tea extract", "elderberry", "bilberry", "acai",
    "spirulina", "chlorella", "holy basil", "rhodiola", "eleuthero",
    "cinnamon", "berberine", "resveratrol", "quercetin",
    "alpha lipoic acid", "lipoic acid", "black seed oil",
    # antioxidants / carotenoids
    "lutein", "zeaxanthin", "lycopene", "beta carotene",
    # salts / forms (still generic even when reported as brand)
    "calcium carbonate", "calcium citrate", "calcium gluconate",
    "magnesium citrate", "magnesium glycinate", "magnesium oxide",
    "zinc gluconate", "zinc picolinate", "iron sulfate",
    "ferrous sulfate", "ferrous gluconate",
    "potassium chloride", "potassium gluconate", "chromium picolinate",
    # misc
    "colloidal silver", "silver", "activated charcoal", "charcoal",
    "electrolytes", "electrolyte", "amino acids", "amino acid",
    "apple cider vinegar", "acv",
    "hair skin nails", "hair vitamins",
    "prenatal", "prenatal vitamin", "prenatal vitamins",
    "postnatal", "postnatal vitamins",
    "multis", "chelated minerals", "multimineral",
    "vitamins", "d3",
}

# Build compressed index after set definition (used in classify_type)
_GENERIC_COMPRESSED = {re.sub(r"[\s-]+", "", k): k for k in GENERIC_INGREDIENTS}

# Terms that begin with an ingredient word but may still be generic
_INGREDIENT_STARTS = [
    "vitamin ", "calcium ", "magnesium ", "zinc ", "iron ", "potassium ",
    "omega ", "fish oil", "folic acid",
]
# Tokens that, following an ingredient word, still indicate generic
# (i.e., they describe a form/salt, not a brand)
_INGREDIENT_QUALIFIERS = {
    "ergocalciferol", "colecalciferol", "cholecalciferol", "ascorbic acid",
    "citrate", "gluconate", "sulfate", "picolinate", "glycinate", "oxide",
    "carbonate", "cyanocobalamin", "methylcobalamin", "tocopherol",
    "d-alpha-tocopherol", "dietary supplement", "supplement",
    "complex", "forte", "high potency", "extra strength", "natural",
    "3", "2",  # vitamin d3, d2
}


def classify_type(norm_key: str) -> str:
    if norm_key in GENERIC_INGREDIENTS:
        return "generic_ingredient"
    # Compressed check: coq10 / co-q10 / co q10 / coq-10 all compress to "coq10"
    compressed = re.sub(r"[\s-]+", "", norm_key)
    if compressed in _GENERIC_COMPRESSED:
        return "generic_ingredient"
    for prefix in _INGREDIENT_STARTS:
        if norm_key.startswith(prefix):
            remainder = norm_key[len(prefix):].strip().split()
            if not remainder:
                return "generic_ingredient"
            if set(remainder).issubset(_INGREDIENT_QUALIFIERS | {"and", "or", "with", "plus", "+", "-", "from"}):
                return "generic_ingredient"
    return "branded"


# ── Contamination rules ───────────────────────────────────────────────────────
# Checked against the RAW term (before normalization).
# action: "exclude" = drop entirely; "flag" = keep, mark for review

CONTAMINATION_RULES = [
    (re.compile(r"^exemption\s*4\b", re.I),          "privacy_exemption_code",          "exclude"),
    (re.compile(r"^wen\b",            re.I),          "cosmetic_product",                "exclude"),
    (re.compile(r"^shower\s+to\s+shower", re.I),      "cosmetic_product",                "exclude"),
    (re.compile(r"^devacurl\b",        re.I),          "cosmetic_product",                "exclude"),
    (re.compile(r"^monat\b",           re.I),          "cosmetic_product",                "exclude"),
    (re.compile(r"^kratom\b",          re.I),          "regulatory_gray_zone",            "flag"),
    (re.compile(r"^5[\s-]hour\s+energy", re.I),        "energy_drink",                    "flag"),
    (re.compile(r"^red\s+bull\b",      re.I),          "energy_drink",                    "flag"),
    (re.compile(r"^monster\b",         re.I),          "energy_drink",                    "flag"),
    (re.compile(r"^celsius\b",         re.I),          "energy_drink",                    "flag"),
]


def hyphen_merge_key(norm_key: str) -> str:
    """Secondary merge key: hyphens treated as spaces, for post-normalize collapse.
    Used to catch 'multi-vitamin'/'multi vitamin', '5-hour energy'/'5 hour energy', etc.
    Does NOT affect display names or primary keys — only determines which groups merge."""
    return re.sub(r"-", " ", norm_key)


def get_contamination(raw: str) -> tuple[Optional[str], Optional[str]]:
    for pat, label, action in CONTAMINATION_RULES:
        if pat.match(raw.strip()):
            return label, action
    return None, None


# ── Brand-family rules ────────────────────────────────────────────────────────
# Matched against the normalized key (lowercase). Most-specific first.
# Used ONLY for hub-page navigation grouping — never to sum counts.

BRAND_FAMILY_RULES = [
    (re.compile(r"^centrum\s+silver\b",         re.I), "Centrum Silver"),
    (re.compile(r"^centrum\b",                  re.I), "Centrum"),
    (re.compile(r"^preservision\s+areds\s+2\b", re.I), "PreserVision AREDS 2"),
    (re.compile(r"^preservision\b",             re.I), "PreserVision"),
    (re.compile(r"^citracal\b",                 re.I), "Citracal"),
    (re.compile(r"^hydroxycut\b",               re.I), "Hydroxycut"),
    (re.compile(r"^super\s+beta\b",             re.I), "Super Beta"),
    (re.compile(r"^one\s+a\s+day\b",            re.I), "One A Day"),
    (re.compile(r"^nature'?s?\s+bounty\b",      re.I), "Nature's Bounty"),
    (re.compile(r"^garden\s+of\s+life\b",       re.I), "Garden of Life"),
    (re.compile(r"^nature\s+made\b",            re.I), "Nature Made"),
    (re.compile(r"^solgar\b",                   re.I), "Solgar"),
    (re.compile(r"^now\s+foods\b",              re.I), "NOW Foods"),
    (re.compile(r"^nordic\s+naturals\b",        re.I), "Nordic Naturals"),
    (re.compile(r"^vitafusion\b",               re.I), "Vitafusion"),
    (re.compile(r"^culturelle\b",               re.I), "Culturelle"),
    (re.compile(r"^align\b",                    re.I), "Align"),
    (re.compile(r"^metamucil\b",                re.I), "Metamucil"),
    (re.compile(r"^benefiber\b",                re.I), "Benefiber"),
    (re.compile(r"^emergen-?c\b",               re.I), "Emergen-C"),
    (re.compile(r"^airborne\b",                 re.I), "Airborne"),
    (re.compile(r"^ester-?c\b",                 re.I), "Ester-C"),
    (re.compile(r"^zicam\b",                    re.I), "Zicam"),
    (re.compile(r"^all\s+day\s+energy\s+greens", re.I), "All Day Energy Greens"),
    (re.compile(r"^nutrafol\b",                 re.I), "Nutrafol"),
    (re.compile(r"^ritual\b",                   re.I), "Ritual"),
    (re.compile(r"^olly\b",                     re.I), "OLLY"),
    (re.compile(r"^thorne\b",                   re.I), "Thorne"),
    (re.compile(r"^pure\s+encapsulations\b",    re.I), "Pure Encapsulations"),
    (re.compile(r"^life\s+extension\b",         re.I), "Life Extension"),
    (re.compile(r"^new\s+chapter\b",            re.I), "New Chapter"),
    (re.compile(r"^jarrow\b",                   re.I), "Jarrow"),
    (re.compile(r"^swanson\b",                  re.I), "Swanson"),
    (re.compile(r"^natrol\b",                   re.I), "Natrol"),
    (re.compile(r"^spring\s+valley\b",          re.I), "Spring Valley"),
    (re.compile(r"^kirkland\b",                 re.I), "Kirkland"),
    (re.compile(r"^rainbow\s+light\b",          re.I), "Rainbow Light"),
    (re.compile(r"^country\s+life\b",           re.I), "Country Life"),
    (re.compile(r"^herbalife\b",                re.I), "Herbalife"),
    (re.compile(r"^isagenix\b",                 re.I), "Isagenix"),
    (re.compile(r"^xyngular\b",                 re.I), "Xyngular"),
    (re.compile(r"^arbonne\b",                  re.I), "Arbonne"),
    (re.compile(r"^plexus\b",                   re.I), "Plexus"),
    (re.compile(r"^usana\b",                    re.I), "USANA"),
    (re.compile(r"^nutrilite\b",                re.I), "Nutrilite"),
    (re.compile(r"^amway\b",                    re.I), "Amway"),
    (re.compile(r"^ag1\b",                      re.I), "AG1"),
    (re.compile(r"^athletic\s+greens\b",        re.I), "AG1"),  # same brand, renamed
    (re.compile(r"^super\s+greens\b",           re.I), "Super Greens"),
    (re.compile(r"^vital\s+proteins\b",         re.I), "Vital Proteins"),
    (re.compile(r"^garden\s+of\s+life\b",       re.I), "Garden of Life"),
    (re.compile(r"^primal\s+harvest\b",         re.I), "Primal Harvest"),
    (re.compile(r"^goli\b",                     re.I), "Goli"),
    (re.compile(r"^bloom\b",                    re.I), "Bloom"),
    (re.compile(r"^alani\b",                    re.I), "Alani"),
    (re.compile(r"^celsius\b",                  re.I), "Celsius"),
    (re.compile(r"^liquid\s+iv\b",              re.I), "Liquid IV"),
    (re.compile(r"^drip\s+drop\b",              re.I), "DripDrop"),
    (re.compile(r"^magnesium\s+glycinate\b",    re.I), ""),  # generic — no family
]


def get_brand_family(norm_key: str) -> Optional[str]:
    for pat, family in BRAND_FAMILY_RULES:
        if pat.match(norm_key) and family:
            return family
    return None


# ── Display name helper ───────────────────────────────────────────────────────

_KNOWN_CAPS = {
    "coq10": "CoQ10", "co-q10": "CoQ10",
    "areds": "AREDS", "areds2": "AREDS 2",
    "dha": "DHA", "epa": "EPA",
    "msm": "MSM", "sam-e": "SAM-e",
    "5-htp": "5-HTP",
    "b12": "B12", "b6": "B6", "b2": "B2", "b1": "B1",
    "d3": "D3", "d2": "D2", "k2": "K2",
    "omega-3": "Omega-3", "omega-6": "Omega-6",
    "acv": "ACV", "dhea": "DHEA",
    "er": "ER", "sr": "SR",
    "nac": "NAC", "gaba": "GABA",
    "ag1": "AG1",
    "usana": "USANA", "olly": "OLLY",
    "p3": "P3",
    "50+": "50+",  # preserve '50+' as-is
    "nch": "NCH",
}


def to_display_name(norm_key: str) -> str:
    # Python str.title() capitalises the letter after any non-alpha char, so
    # "women's" → "Women'S". Fix by capitalising only letters that follow a space
    # (or are at the start), leaving post-apostrophe letters alone.
    def _titlecase(s: str) -> str:
        if s in _KNOWN_CAPS:
            return _KNOWN_CAPS[s]
        result = []
        cap_next = True
        for ch in s:
            if ch == " ":
                result.append(ch)
                cap_next = True
            elif cap_next and ch.isalpha():
                result.append(ch.upper())
                cap_next = False
            else:
                result.append(ch)
        return "".join(result)

    return " ".join(_titlecase(w) for w in norm_key.split())


# ── Normalization core ────────────────────────────────────────────────────────

def normalize_key(term: str) -> str:
    t = term.lower().strip()
    t = re.sub(r"\s+", " ", t)

    # Strip trailing parentheticals iteratively (handles stacked)
    prev = None
    while prev != t:
        prev = t
        t = re.sub(r"\s*\([^()]*\)\s*$", "", t).strip()

    # Admin tokens
    t = ADMIN_RE.sub("", t).strip()

    # Size/dosage tokens (loop for stacked)
    prev = None
    while prev != t:
        prev = t
        t = SIZE_RE.sub("", t).strip()

    # Form qualifiers (loop for stacked, e.g. "rapid release caplets")
    prev = None
    while prev != t:
        prev = t
        t = FORM_SUFFIX_RE.sub("", t).strip()

    # Normalise en/em dashes to hyphen; collapse spaces around hyphens
    t = re.sub(r"[–—]", "-", t)
    t = re.sub(r"\s+-\s+", "-", t)
    t = re.sub(r"\s+-", "-", t)
    t = re.sub(r"-\s+", "-", t)
    # Normalise ampersands
    t = re.sub(r"\s*&\s*", " and ", t)
    # Curly apostrophes → straight
    t = t.replace("’", "’").replace("’", "’")

    return re.sub(r"\s+", " ", t).strip()


# ── Main pipeline ─────────────────────────────────────────────────────────────

def main():
    stats_only = "--stats-only" in sys.argv

    eprint = lambda *a, **kw: print(*a, file=sys.stderr, **kw)
    eprint("Fetching from openFDA…")

    with urllib.request.urlopen(API_URL) as resp:
        data = json.load(resp)
    raw_results = data["results"]
    eprint(f"  {len(raw_results)} raw brand strings received.")

    # ── Group by normalized key ──────────────────────────────────────────────
    groups: dict[str, dict] = defaultdict(lambda: {
        "total_reports": 0,
        "raw_pairs": [],          # [(raw_str, count), …]
        "cont_label": None,
        "cont_action": None,
    })

    raw_total = sum(r["count"] for r in raw_results)

    for r in raw_results:
        raw, count = r["term"], r["count"]
        norm = normalize_key(raw)
        g = groups[norm]
        g["total_reports"] += count
        g["raw_pairs"].append((raw, count))
        label, action = get_contamination(raw)
        if label and g["cont_label"] is None:
            g["cont_label"] = label
            g["cont_action"] = action

    eprint(f"  Collapsed to {len(groups)} normalized groups (pass 1: case + form suffixes).")

    # ── Pass 2: hyphen-merge ─────────────────────────────────────────────────
    # Groups whose keys differ only by hyphen-vs-space are merged.
    # The canonical key is chosen as the one with higher total_reports (ties: alphabetical).
    hmerge: dict[str, str] = {}  # hyphen_key → canonical norm_key
    for nk in groups:
        hk = hyphen_merge_key(nk)
        if hk not in hmerge:
            hmerge[hk] = nk
        else:
            existing = hmerge[hk]
            # pick canonical = higher count; on tie keep existing (stable)
            if groups[nk]["total_reports"] > groups[existing]["total_reports"]:
                hmerge[hk] = nk

    merged_groups: dict[str, dict] = defaultdict(lambda: {
        "total_reports": 0,
        "raw_pairs": [],
        "cont_label": None,
        "cont_action": None,
    })
    merge_log: list[str] = []
    for nk, g in groups.items():
        canonical = hmerge[hyphen_merge_key(nk)]
        merged_groups[canonical]["total_reports"] += g["total_reports"]
        merged_groups[canonical]["raw_pairs"].extend(g["raw_pairs"])
        if g["cont_label"] and merged_groups[canonical]["cont_label"] is None:
            merged_groups[canonical]["cont_label"] = g["cont_label"]
            merged_groups[canonical]["cont_action"] = g["cont_action"]
        if canonical != nk:
            merge_log.append(f"  hyphen-merge: '{nk}' → '{canonical}'")

    if merge_log:
        eprint(f"  Pass 2 hyphen-merges ({len(merge_log)}):")
        for m in merge_log:
            eprint(m)
    eprint(f"  After pass 2: {len(merged_groups)} groups.")

    groups = merged_groups

    eprint(f"  Raw total reports: {raw_total}")
    norm_total = sum(g["total_reports"] for g in groups.values())
    assert norm_total == raw_total, f"SANITY FAIL: report count mismatch {norm_total} vs {raw_total}"
    eprint(f"  Normalized total reports: {norm_total}  ✓ matches raw total")

    # ── Build rows ───────────────────────────────────────────────────────────
    rows = []
    for norm_key, g in groups.items():
        pairs_sorted = sorted(g["raw_pairs"], key=lambda x: -x[1])
        etype    = classify_type(norm_key)
        family   = get_brand_family(norm_key)
        cont_l   = g["cont_label"] or ""
        cont_a   = g["cont_action"] or ""
        display  = to_display_name(norm_key)
        raw_repr = " | ".join(f"{t} ({c})" for t, c in pairs_sorted)

        rows.append({
            "canonical_display_name": display,
            "normalized_key":         norm_key,
            "type":                   etype,
            "brand_family":           family or "",
            "total_reports":          g["total_reports"],
            "contamination_flag":     cont_l,
            "contamination_action":   cont_a,
            "n_raw_strings_merged":   len(pairs_sorted),
            "raw_strings_merged":     raw_repr,
        })

    rows.sort(key=lambda x: -x["total_reports"])

    # ── CSV output ───────────────────────────────────────────────────────────
    if not stats_only:
        fields = [
            "canonical_display_name", "normalized_key", "type", "brand_family",
            "total_reports", "contamination_flag", "contamination_action",
            "n_raw_strings_merged", "raw_strings_merged",
        ]
        writer = csv.DictWriter(sys.stdout, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    # ── Stats ────────────────────────────────────────────────────────────────
    sep = "─" * 70

    branded    = [r for r in rows if r["type"] == "branded"           and r["contamination_action"] != "exclude"]
    generic    = [r for r in rows if r["type"] == "generic_ingredient" and r["contamination_action"] != "exclude"]
    flagged    = [r for r in rows if r["contamination_action"] == "flag"]
    excluded   = [r for r in rows if r["contamination_action"] == "exclude"]

    def thresh(lst, n): return sum(1 for r in lst if r["total_reports"] >= n)

    print(sep)
    print("SUPPLEMENT SIGNAL — BRAND NORMALIZATION SUMMARY")
    print(sep)
    print(f"  Raw API strings:           {len(raw_results)}")
    print(f"  Normalized groups:         {len(rows)}")
    print(f"  Raw total reports:         {raw_total}")
    print(f"  Norm total reports:        {norm_total}  ✓")
    print()
    print("── BRANDED entities (excluding contamination) ──")
    print(f"  Total branded groups:      {len(branded)}")
    print(f"  ≥ 100 reports:             {thresh(branded, 100)}")
    print(f"  ≥  25 reports:             {thresh(branded, 25)}")
    print(f"  ≥  10 reports:             {thresh(branded, 10)}")
    print()
    print("── GENERIC INGREDIENT entities ──────────────────")
    print(f"  Total generic groups:      {len(generic)}")
    print(f"  ≥ 100 reports:             {thresh(generic, 100)}")
    print(f"  ≥  25 reports:             {thresh(generic, 25)}")
    print(f"  ≥  10 reports:             {thresh(generic, 10)}")
    print()
    print("── CONTAMINATION ────────────────────────────────")
    print(f"  Excluded:  {len(excluded)}")
    for r in excluded:
        print(f"    [{r['total_reports']:>5}]  {r['canonical_display_name']}  ({r['contamination_flag']})")
    print(f"  Flagged (keep, review):  {len(flagged)}")
    for r in flagged:
        print(f"    [{r['total_reports']:>5}]  {r['canonical_display_name']}  ({r['contamination_flag']})")
    print()

    # Brand families with ≥2 SKUs
    from collections import Counter
    family_members: dict[str, list] = defaultdict(list)
    for r in rows:
        if r["brand_family"] and r["contamination_action"] != "exclude":
            family_members[r["brand_family"]].append(r)

    multi_fam = {k: v for k, v in family_members.items() if len(v) >= 2}
    multi_fam_sorted = sorted(multi_fam.items(), key=lambda x: -sum(s["total_reports"] for s in x[1]))

    print(f"── BRAND FAMILY HUB CANDIDATES (≥ 2 SKUs) ──────")
    print(f"  {len(multi_fam)} families qualify\n")
    for fam, skus in multi_fam_sorted:
        total = sum(s["total_reports"] for s in skus)
        print(f"  {fam}  ({len(skus)} SKUs, {total} combined reports — nav use only, never sum)")
        for s in sorted(skus, key=lambda x: -x["total_reports"]):
            print(f"    [{s['total_reports']:>5}]  {s['canonical_display_name']}")
    print()

    # ── Sanity checks ────────────────────────────────────────────────────────
    print("── SANITY CHECKS ────────────────────────────────")
    failures = []

    # 1. Report count conservation
    if norm_total != raw_total:
        failures.append(f"FAIL: total report count drifted ({norm_total} ≠ {raw_total})")
    else:
        print(f"  ✓  Report count conserved across normalization ({norm_total})")

    # 2. No zero-count entities
    zero_count = [r for r in rows if r["total_reports"] <= 0]
    if zero_count:
        failures.append(f"FAIL: {len(zero_count)} entities with ≤0 reports")
    else:
        print(f"  ✓  No zero-report entities")

    # 3. Exemption 4 excluded
    exemption_in = [r for r in rows if "exemption" in r["normalized_key"] and r["contamination_action"] != "exclude"]
    if exemption_in:
        failures.append(f"FAIL: EXEMPTION 4 not excluded — {exemption_in}")
    else:
        print(f"  ✓  EXEMPTION 4 excluded (privacy code, not a brand)")

    # 4. No branded entity has a generic_ingredient type AND a brand_family
    #    (would indicate a misclassification — generic shouldn't get a brand hub)
    generic_with_family = [r for r in rows if r["type"] == "generic_ingredient" and r["brand_family"]]
    if generic_with_family:
        failures.append(f"WARN: {len(generic_with_family)} generic_ingredient entries have a brand_family set")
        for r in generic_with_family:
            print(f"    WARN: {r['canonical_display_name']} is generic_ingredient but family={r['brand_family']}")
    else:
        print(f"  ✓  No generic_ingredient entries incorrectly assigned a brand_family")

    # 5. DEATHS ≤ TOTAL REPORTS  (per-entity cross-tab is not available from the
    #    count endpoint — this check must run at ingestion time against individual
    #    records. Noted here as a pipeline gate.)
    print(f"  ⚠  Per-entity death ≤ reports check: DEFERRED to ingestion pipeline")
    print(f"      (Requires cross-tabulating outcomes per product — not available")
    print(f"       from the /count endpoint. Must be a gate in the ETL step.)")

    # 6. Largest merge groups — audit spot-check
    big_merges = sorted(rows, key=lambda x: -x["n_raw_strings_merged"])[:5]
    print(f"\n  Top 5 largest merges (audit these):")
    for r in big_merges:
        print(f"    [{r['total_reports']:>5}, {r['n_raw_strings_merged']} strings]  {r['canonical_display_name']}")
        print(f"       {r['raw_strings_merged'][:120]}{'…' if len(r['raw_strings_merged']) > 120 else ''}")

    if failures:
        print()
        for f in failures:
            print(f"  ✗  {f}")
    else:
        print(f"\n  All automated checks passed.")

    print(sep)


if __name__ == "__main__":
    main()
