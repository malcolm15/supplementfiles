#!/usr/bin/env python3
"""
Supplement brand normalization layer v2 — SupplementSignal.
Changes from v1:
  - outer stabilization loop in normalize_key (fixes form-suffix-then-paren edge cases)
  - category-label noise stripping (multiminerals/multivitamins as standalone tokens)
  - 'plus' → '+' normalization after digit
  - Pass 3: garble-merge within brand families
  - Updated contamination: kratom + 5-hour energy KEPT (branded); monster/red bull EXCLUDED
  - page_eligible column (total_reports >= 10)
"""

import csv, json, re, sys, urllib.request
from collections import defaultdict
from typing import Optional

API_URL = (
    "https://api.fda.gov/food/event.json"
    "?search=products.industry_name.exact:"
    "%22Vit%2FMin%2FProt%2FUnconv+Diet%28Human%2FAnimal%29%22"
    "&count=products.name_brand.exact&limit=1000"
)

# ── Stripping patterns ────────────────────────────────────────────────────────

_FORM_ALTS = "|".join([
    r"tablets?", r"capsules?", r"caplets?",
    r"soft\s*gels?", r"softgels?", r"gel\s*caps?", r"gelcaps?",
    r"gumm(?:y|ies)", r"chewables?", r"chews?",
    r"liquid", r"powder", r"drops?", r"lozenges?", r"sprays?",
    r"film[\s-]?coated", r"extended[\s-]?release",
    r"rapid[\s-]?release", r"time[\s-]?release", r"sustained[\s-]?release",
    r"\ber\b", r"\bsr\b",
])
FORM_SUFFIX_RE  = re.compile(r"\s+(?:" + _FORM_ALTS + r")\s*$", re.I)
SIZE_RE         = re.compile(r"\s+\d+\s*(?:ct|count|mg|mcg|iu|oz|g\b|ml|lb|lbs|gram[s]?|pack|pk)\s*$", re.I)
ADMIN_RE        = re.compile(r"\s+no\s+(?:upc|preferred?\s*(?:name|brand)?)\s*$|\s+\((?:no\s+pref|no\s+brand|nch)\)\s*$", re.I)
# Ingredient-category labels that reporters append as noise (standalone, not in parens)
CATEGORY_NOISE_RE = re.compile(r"\s+(?:multimineral[s]?|multivitamin[s]?)\s*$", re.I)
PAREN_RE        = re.compile(r"\s*\([^()]*\)\s*$")

# ── Generic ingredient set ────────────────────────────────────────────────────

GENERIC_INGREDIENTS = {
    "vitamin a","vitamin b","vitamin b complex","vitamin b-complex",
    "vitamin b1","vitamin b2","vitamin b3","vitamin b5","vitamin b6",
    "vitamin b7","vitamin b9","vitamin b12","vitamin c","vitamin d",
    "vitamin d2","vitamin d3","vitamin e","vitamin k","vitamin k2",
    "b complex","b-complex","b12","b6","d3","d2","k2",
    "multivitamin","multivitamins","multi vitamin","multi-vitamin",
    "multi vitamins","multi-vitamins","vitamins","multi","multiminerals",
    "calcium","magnesium","zinc","iron","potassium","selenium",
    "chromium","copper","manganese","molybdenum","iodine","phosphorus","boron",
    "fish oil","omega 3","omega-3","omega 3 fatty acids","omega 6","omega-6",
    "dha","epa","krill oil","cod liver oil","flaxseed oil","flaxseed",
    "evening primrose oil",
    "biotin","folic acid","folate","niacin","riboflavin","thiamine",
    "pantothenic acid","choline","inositol",
    "coq10","co-q10","coenzyme q10","ubiquinol","ubiquinone",
    "melatonin","probiotic","probiotics","prebiotic","prebiotics",
    "turmeric","curcumin","ginger","garlic","echinacea",
    "ginkgo biloba","ginkgo","ginseng","ashwagandha",
    "valerian","valerian root","milk thistle","saw palmetto","black cohosh",
    "maca","maca root",
    "glucosamine","chondroitin","msm","collagen",
    "protein","whey protein","whey","casein","creatine",
    "l-carnitine","carnitine","l-glutamine","glutamine",
    "l-arginine","arginine","l-lysine","lysine",
    "5-htp","5 htp","sam-e","same",
    "fiber","psyllium","psyllium husk",
    "green tea","green tea extract","elderberry","bilberry","acai",
    "spirulina","chlorella","holy basil","rhodiola","eleuthero",
    "cinnamon","berberine","resveratrol","quercetin",
    "alpha lipoic acid","lipoic acid","black seed oil",
    "lutein","zeaxanthin","lycopene","beta carotene",
    "calcium carbonate","calcium citrate","calcium gluconate",
    "magnesium citrate","magnesium glycinate","magnesium oxide",
    "zinc gluconate","zinc picolinate","iron sulfate",
    "ferrous sulfate","ferrous gluconate",
    "potassium chloride","potassium gluconate","chromium picolinate",
    "colloidal silver","silver","activated charcoal","charcoal",
    "electrolytes","electrolyte","amino acids","amino acid",
    "apple cider vinegar","acv",
    "hair skin nails","hair vitamins",
    "prenatal","prenatal vitamin","prenatal vitamins",
    "postnatal","postnatal vitamins",
    "multis","chelated minerals","multimineral",
    "vitamins","d3",
}
_GENERIC_COMPRESSED = {re.sub(r"[\s-]+","",k): k for k in GENERIC_INGREDIENTS}

_INGREDIENT_STARTS = [
    "vitamin ","calcium ","magnesium ","zinc ","iron ","potassium ",
    "omega ","fish oil","folic acid",
]
_INGREDIENT_QUALIFIERS = {
    "ergocalciferol","colecalciferol","cholecalciferol","ascorbic acid",
    "citrate","gluconate","sulfate","picolinate","glycinate","oxide",
    "carbonate","cyanocobalamin","methylcobalamin","tocopherol",
    "dietary supplement","supplement","complex","forte",
    "high potency","extra strength","natural","3","2",
}

def classify_type(norm_key: str) -> str:
    if norm_key in GENERIC_INGREDIENTS: return "generic_ingredient"
    compressed = re.sub(r"[\s-]+","",norm_key)
    if compressed in _GENERIC_COMPRESSED: return "generic_ingredient"
    for prefix in _INGREDIENT_STARTS:
        if norm_key.startswith(prefix):
            remainder = norm_key[len(prefix):].strip().split()
            if not remainder: return "generic_ingredient"
            if set(remainder).issubset(_INGREDIENT_QUALIFIERS|{"and","or","with","plus","+","-","from"}):
                return "generic_ingredient"
    return "branded"

# ── Contamination ─────────────────────────────────────────────────────────────
# Actions: "exclude" = drop; "flag" = keep but mark; blank = clean branded

CONTAMINATION_RULES = [
    (re.compile(r"^exemption\s*4\b",        re.I), "privacy_exemption_code",     "exclude"),
    (re.compile(r"^wen\b",                  re.I), "cosmetic_product",            "exclude"),
    (re.compile(r"^shower\s+to\s+shower",   re.I), "cosmetic_product",            "exclude"),
    (re.compile(r"^devacurl\b",             re.I), "cosmetic_product",            "exclude"),
    (re.compile(r"^monat\b",               re.I), "cosmetic_product",            "exclude"),
    (re.compile(r"^monster\b",             re.I), "conventional_beverage",       "exclude"),
    (re.compile(r"^red\s+bull\b",          re.I), "conventional_beverage",       "exclude"),
    # Kept by editorial decision — reclassified as branded
    (re.compile(r"^kratom\b",              re.I), "regulatory_gray_zone_kept",   "keep"),
    (re.compile(r"^5[\s-]hour\s+energy",   re.I), "energy_drink_kept",           "keep"),
]

def get_contamination(raw: str) -> tuple[Optional[str], Optional[str]]:
    for pat, label, action in CONTAMINATION_RULES:
        if pat.match(raw.strip()):
            return label, action
    return None, None

# ── Brand family rules ────────────────────────────────────────────────────────

BRAND_FAMILY_RULES = [
    (re.compile(r"^centrum\s+silver\b",          re.I), "Centrum Silver"),
    (re.compile(r"^centrum\b",                   re.I), "Centrum"),
    (re.compile(r"^preservision\s+areds\s+2\b",  re.I), "PreserVision AREDS 2"),
    (re.compile(r"^preservision\b",              re.I), "PreserVision"),
    (re.compile(r"^citracal\b",                  re.I), "Citracal"),
    (re.compile(r"^hydroxycut\b",                re.I), "Hydroxycut"),
    (re.compile(r"^super\s+beta\b",              re.I), "Super Beta"),
    (re.compile(r"^one\s+a\s+day\b",             re.I), "One A Day"),
    (re.compile(r"^nature'?s?\s+bounty\b",       re.I), "Nature's Bounty"),
    (re.compile(r"^garden\s+of\s+life\b",        re.I), "Garden of Life"),
    (re.compile(r"^nature\s+made\b",             re.I), "Nature Made"),
    (re.compile(r"^benefiber\b",                 re.I), "Benefiber"),
    (re.compile(r"^emergen-?c\b",                re.I), "Emergen-C"),
    (re.compile(r"^ester-?c\b",                  re.I), "Ester-C"),
    (re.compile(r"^airborne\b",                  re.I), "Airborne"),
    (re.compile(r"^zicam\b",                     re.I), "Zicam"),
    (re.compile(r"^all\s+day\s+energy\s+greens", re.I), "All Day Energy Greens"),
    (re.compile(r"^nutrafol\b",                  re.I), "Nutrafol"),
    (re.compile(r"^herbalife\b",                 re.I), "Herbalife"),
    (re.compile(r"^plexus\b",                    re.I), "Plexus"),
    (re.compile(r"^arbonne\b",                   re.I), "Arbonne"),
    (re.compile(r"^isagenix\b",                  re.I), "Isagenix"),
    (re.compile(r"^xyngular\b",                  re.I), "Xyngular"),
    (re.compile(r"^usana\b",                     re.I), "USANA"),
    (re.compile(r"^nutrilite\b",                 re.I), "Nutrilite"),
    (re.compile(r"^amway\b",                     re.I), "Amway"),
    (re.compile(r"^ag1\b",                       re.I), "AG1"),
    (re.compile(r"^athletic\s+greens\b",         re.I), "AG1"),
    (re.compile(r"^vital\s+proteins\b",          re.I), "Vital Proteins"),
    (re.compile(r"^olly\b",                      re.I), "OLLY"),
    (re.compile(r"^thorne\b",                    re.I), "Thorne"),
    (re.compile(r"^ritual\b",                    re.I), "Ritual"),
    (re.compile(r"^new\s+chapter\b",             re.I), "New Chapter"),
    (re.compile(r"^solgar\b",                    re.I), "Solgar"),
    (re.compile(r"^natrol\b",                    re.I), "Natrol"),
    (re.compile(r"^spring\s+valley\b",           re.I), "Spring Valley"),
    (re.compile(r"^kirkland\b",                  re.I), "Kirkland"),
    (re.compile(r"^nordic\s+naturals\b",         re.I), "Nordic Naturals"),
    (re.compile(r"^vitafusion\b",                re.I), "Vitafusion"),
    (re.compile(r"^culturelle\b",                re.I), "Culturelle"),
    (re.compile(r"^align\b",                     re.I), "Align"),
    (re.compile(r"^metamucil\b",                 re.I), "Metamucil"),
    (re.compile(r"^rainbow\s+light\b",           re.I), "Rainbow Light"),
    (re.compile(r"^country\s+life\b",            re.I), "Country Life"),
    (re.compile(r"^life\s+extension\b",          re.I), "Life Extension"),
    (re.compile(r"^pure\s+encapsulations\b",     re.I), "Pure Encapsulations"),
    (re.compile(r"^goli\b",                      re.I), "Goli"),
    (re.compile(r"^primal\s+harvest\b",          re.I), "Primal Harvest"),
    (re.compile(r"^liquid\s+iv\b",               re.I), "Liquid IV"),
]

def get_brand_family(norm_key: str) -> Optional[str]:
    for pat, family in BRAND_FAMILY_RULES:
        if pat.match(norm_key):
            return family
    return None

# ── Display name ──────────────────────────────────────────────────────────────

_KNOWN_CAPS = {
    "coq10":"CoQ10","co-q10":"CoQ10","areds":"AREDS","areds2":"AREDS 2",
    "dha":"DHA","epa":"EPA","msm":"MSM","sam-e":"SAM-e","5-htp":"5-HTP",
    "b12":"B12","b6":"B6","b2":"B2","b1":"B1","d3":"D3","d2":"D2","k2":"K2",
    "omega-3":"Omega-3","omega-6":"Omega-6","acv":"ACV","dhea":"DHEA",
    "nac":"NAC","gaba":"GABA","ag1":"AG1","usana":"USANA","olly":"OLLY","p3":"P3",
    "50+":"50+","nch":"NCH",
}

def to_display_name(norm_key: str) -> str:
    def _w(s):
        if s in _KNOWN_CAPS: return _KNOWN_CAPS[s]
        result, cap_next = [], True
        for ch in s:
            if ch == " ": result.append(ch); cap_next = True
            elif cap_next and ch.isalpha(): result.append(ch.upper()); cap_next = False
            else: result.append(ch)
        return "".join(result)
    return " ".join(_w(w) for w in norm_key.split())

# ── Normalize key ─────────────────────────────────────────────────────────────

def normalize_key(term: str) -> str:
    t = term.lower().strip()
    t = re.sub(r"\s+", " ", t)

    # Outer stabilization loop: strip parens → admin → size → form → category noise
    # Loops until nothing changes (handles form-suffix reveals trailing paren, etc.)
    prev = None
    while prev != t:
        prev = t
        # Trailing parentheticals (iterative to handle stacked)
        p2 = None
        while p2 != t:
            p2 = t
            t = PAREN_RE.sub("", t).strip()
        t = ADMIN_RE.sub("", t).strip()
        # Size tokens
        p2 = None
        while p2 != t:
            p2 = t; t = SIZE_RE.sub("", t).strip()
        # Form qualifiers
        p2 = None
        while p2 != t:
            p2 = t; t = FORM_SUFFIX_RE.sub("", t).strip()
        # Category noise labels (multiminerals/multivitamins as standalone trailing tokens)
        p2 = None
        while p2 != t:
            p2 = t; t = CATEGORY_NOISE_RE.sub("", t).strip()

    # Normalise dashes/spaces around hyphens (en/em → hyphen, collapse spaces)
    t = re.sub(r"[–—]", "-", t)
    t = re.sub(r"\s*-\s*", "-", t)

    # Normalise ampersands
    t = re.sub(r"\s*&\s*", " and ", t)

    # Normalise "digit plus" → "digit+" (e.g. "50 plus" → "50+")
    t = re.sub(r"(?<=\d)\s+plus\b", "+", t, flags=re.I)

    # Normalise all apostrophe variants to ASCII U+0027 straight apostrophe.
    _SQ = chr(0x27)  # ASCII straight apostrophe — set via chr() to avoid tool substitution
    t = t.replace(chr(0x92),    _SQ)  # cp1252 byte
    t = t.replace(chr(0x2019),  _SQ)  # Unicode RIGHT SINGLE QUOTATION MARK
    t = t.replace(chr(0x2018),  _SQ)  # Unicode LEFT  SINGLE QUOTATION MARK
    t = t.replace(chr(0x02bc),  _SQ)  # MODIFIER LETTER APOSTROPHE
"""
Supplement brand normalization layer v2 — SupplementSignal.
Changes from v1:
  - outer stabilization loop in normalize_key (fixes form-suffix-then-paren edge cases)
  - category-label noise stripping (multiminerals/multivitamins as standalone tokens)
  - 'plus' → '+' normalization after digit
  - Pass 3: garble-merge within brand families
  - Updated contamination: kratom + 5-hour energy KEPT (branded); monster/red bull EXCLUDED
  - page_eligible column (total_reports >= 10)
"""

import csv, json, re, sys, urllib.request
from collections import defaultdict
from typing import Optional

API_URL = (
    "https://api.fda.gov/food/event.json"
    "?search=products.industry_name.exact:"
    "%22Vit%2FMin%2FProt%2FUnconv+Diet%28Human%2FAnimal%29%22"
    "&count=products.name_brand.exact&limit=1000"
)

# ── Stripping patterns ────────────────────────────────────────────────────────

_FORM_ALTS = "|".join([
    r"tablets?", r"capsules?", r"caplets?",
    r"soft\s*gels?", r"softgels?", r"gel\s*caps?", r"gelcaps?",
    r"gumm(?:y|ies)", r"chewables?", r"chews?",
    r"liquid", r"powder", r"drops?", r"lozenges?", r"sprays?",
    r"film[\s-]?coated", r"extended[\s-]?release",
    r"rapid[\s-]?release", r"time[\s-]?release", r"sustained[\s-]?release",
    r"\ber\b", r"\bsr\b",
])
FORM_SUFFIX_RE  = re.compile(r"\s+(?:" + _FORM_ALTS + r")\s*$", re.I)
SIZE_RE         = re.compile(r"\s+\d+\s*(?:ct|count|mg|mcg|iu|oz|g\b|ml|lb|lbs|gram[s]?|pack|pk)\s*$", re.I)
ADMIN_RE        = re.compile(r"\s+no\s+(?:upc|preferred?\s*(?:name|brand)?)\s*$|\s+\((?:no\s+pref|no\s+brand|nch)\)\s*$", re.I)
# Ingredient-category labels that reporters append as noise (standalone, not in parens)
CATEGORY_NOISE_RE = re.compile(r"\s+(?:multimineral[s]?|multivitamin[s]?)\s*$", re.I)
PAREN_RE        = re.compile(r"\s*\([^()]*\)\s*$")

# ── Generic ingredient set ────────────────────────────────────────────────────

GENERIC_INGREDIENTS = {
    "vitamin a","vitamin b","vitamin b complex","vitamin b-complex",
    "vitamin b1","vitamin b2","vitamin b3","vitamin b5","vitamin b6",
    "vitamin b7","vitamin b9","vitamin b12","vitamin c","vitamin d",
    "vitamin d2","vitamin d3","vitamin e","vitamin k","vitamin k2",
    "b complex","b-complex","b12","b6","d3","d2","k2",
    "multivitamin","multivitamins","multi vitamin","multi-vitamin",
    "multi vitamins","multi-vitamins","vitamins","multi","multiminerals",
    "calcium","magnesium","zinc","iron","potassium","selenium",
    "chromium","copper","manganese","molybdenum","iodine","phosphorus","boron",
    "fish oil","omega 3","omega-3","omega 3 fatty acids","omega 6","omega-6",
    "dha","epa","krill oil","cod liver oil","flaxseed oil","flaxseed",
    "evening primrose oil",
    "biotin","folic acid","folate","niacin","riboflavin","thiamine",
    "pantothenic acid","choline","inositol",
    "coq10","co-q10","coenzyme q10","ubiquinol","ubiquinone",
    "melatonin","probiotic","probiotics","prebiotic","prebiotics",
    "turmeric","curcumin","ginger","garlic","echinacea",
    "ginkgo biloba","ginkgo","ginseng","ashwagandha",
    "valerian","valerian root","milk thistle","saw palmetto","black cohosh",
    "maca","maca root",
    "glucosamine","chondroitin","msm","collagen",
    "protein","whey protein","whey","casein","creatine",
    "l-carnitine","carnitine","l-glutamine","glutamine",
    "l-arginine","arginine","l-lysine","lysine",
    "5-htp","5 htp","sam-e","same",
    "fiber","psyllium","psyllium husk",
    "green tea","green tea extract","elderberry","bilberry","acai",
    "spirulina","chlorella","holy basil","rhodiola","eleuthero",
    "cinnamon","berberine","resveratrol","quercetin",
    "alpha lipoic acid","lipoic acid","black seed oil",
    "lutein","zeaxanthin","lycopene","beta carotene",
    "calcium carbonate","calcium citrate","calcium gluconate",
    "magnesium citrate","magnesium glycinate","magnesium oxide",
    "zinc gluconate","zinc picolinate","iron sulfate",
    "ferrous sulfate","ferrous gluconate",
    "potassium chloride","potassium gluconate","chromium picolinate",
    "colloidal silver","silver","activated charcoal","charcoal",
    "electrolytes","electrolyte","amino acids","amino acid",
    "apple cider vinegar","acv",
    "hair skin nails","hair vitamins",
    "prenatal","prenatal vitamin","prenatal vitamins",
    "postnatal","postnatal vitamins",
    "multis","chelated minerals","multimineral",
    "vitamins","d3",
}
_GENERIC_COMPRESSED = {re.sub(r"[\s-]+","",k): k for k in GENERIC_INGREDIENTS}

_INGREDIENT_STARTS = [
    "vitamin ","calcium ","magnesium ","zinc ","iron ","potassium ",
    "omega ","fish oil","folic acid",
]
_INGREDIENT_QUALIFIERS = {
    "ergocalciferol","colecalciferol","cholecalciferol","ascorbic acid",
    "citrate","gluconate","sulfate","picolinate","glycinate","oxide",
    "carbonate","cyanocobalamin","methylcobalamin","tocopherol",
    "dietary supplement","supplement","complex","forte",
    "high potency","extra strength","natural","3","2",
}

def classify_type(norm_key: str) -> str:
    if norm_key in GENERIC_INGREDIENTS: return "generic_ingredient"
    compressed = re.sub(r"[\s-]+","",norm_key)
    if compressed in _GENERIC_COMPRESSED: return "generic_ingredient"
    for prefix in _INGREDIENT_STARTS:
        if norm_key.startswith(prefix):
            remainder = norm_key[len(prefix):].strip().split()
            if not remainder: return "generic_ingredient"
            if set(remainder).issubset(_INGREDIENT_QUALIFIERS|{"and","or","with","plus","+","-","from"}):
                return "generic_ingredient"
    return "branded"

# ── Contamination ─────────────────────────────────────────────────────────────
# Actions: "exclude" = drop; "flag" = keep but mark; blank = clean branded

CONTAMINATION_RULES = [
    (re.compile(r"^exemption\s*4\b",        re.I), "privacy_exemption_code",     "exclude"),
    (re.compile(r"^wen\b",                  re.I), "cosmetic_product",            "exclude"),
    (re.compile(r"^shower\s+to\s+shower",   re.I), "cosmetic_product",            "exclude"),
    (re.compile(r"^devacurl\b",             re.I), "cosmetic_product",            "exclude"),
    (re.compile(r"^monat\b",               re.I), "cosmetic_product",            "exclude"),
    (re.compile(r"^monster\b",             re.I), "conventional_beverage",       "exclude"),
    (re.compile(r"^red\s+bull\b",          re.I), "conventional_beverage",       "exclude"),
    # Kept by editorial decision — reclassified as branded
    (re.compile(r"^kratom\b",              re.I), "regulatory_gray_zone_kept",   "keep"),
    (re.compile(r"^5[\s-]hour\s+energy",   re.I), "energy_drink_kept",           "keep"),
]

def get_contamination(raw: str) -> tuple[Optional[str], Optional[str]]:
    for pat, label, action in CONTAMINATION_RULES:
        if pat.match(raw.strip()):
            return label, action
    return None, None

# ── Brand family rules ────────────────────────────────────────────────────────

BRAND_FAMILY_RULES = [
    (re.compile(r"^centrum\s+silver\b",          re.I), "Centrum Silver"),
    (re.compile(r"^centrum\b",                   re.I), "Centrum"),
    (re.compile(r"^preservision\s+areds\s+2\b",  re.I), "PreserVision AREDS 2"),
    (re.compile(r"^preservision\b",              re.I), "PreserVision"),
    (re.compile(r"^citracal\b",                  re.I), "Citracal"),
    (re.compile(r"^hydroxycut\b",                re.I), "Hydroxycut"),
    (re.compile(r"^super\s+beta\b",              re.I), "Super Beta"),
    (re.compile(r"^one\s+a\s+day\b",             re.I), "One A Day"),
    (re.compile(r"^nature'?s?\s+bounty\b",       re.I), "Nature's Bounty"),
    (re.compile(r"^garden\s+of\s+life\b",        re.I), "Garden of Life"),
    (re.compile(r"^nature\s+made\b",             re.I), "Nature Made"),
    (re.compile(r"^benefiber\b",                 re.I), "Benefiber"),
    (re.compile(r"^emergen-?c\b",                re.I), "Emergen-C"),
    (re.compile(r"^ester-?c\b",                  re.I), "Ester-C"),
    (re.compile(r"^airborne\b",                  re.I), "Airborne"),
    (re.compile(r"^zicam\b",                     re.I), "Zicam"),
    (re.compile(r"^all\s+day\s+energy\s+greens", re.I), "All Day Energy Greens"),
    (re.compile(r"^nutrafol\b",                  re.I), "Nutrafol"),
    (re.compile(r"^herbalife\b",                 re.I), "Herbalife"),
    (re.compile(r"^plexus\b",                    re.I), "Plexus"),
    (re.compile(r"^arbonne\b",                   re.I), "Arbonne"),
    (re.compile(r"^isagenix\b",                  re.I), "Isagenix"),
    (re.compile(r"^xyngular\b",                  re.I), "Xyngular"),
    (re.compile(r"^usana\b",                     re.I), "USANA"),
    (re.compile(r"^nutrilite\b",                 re.I), "Nutrilite"),
    (re.compile(r"^amway\b",                     re.I), "Amway"),
    (re.compile(r"^ag1\b",                       re.I), "AG1"),
    (re.compile(r"^athletic\s+greens\b",         re.I), "AG1"),
    (re.compile(r"^vital\s+proteins\b",          re.I), "Vital Proteins"),
    (re.compile(r"^olly\b",                      re.I), "OLLY"),
    (re.compile(r"^thorne\b",                    re.I), "Thorne"),
    (re.compile(r"^ritual\b",                    re.I), "Ritual"),
    (re.compile(r"^new\s+chapter\b",             re.I), "New Chapter"),
    (re.compile(r"^solgar\b",                    re.I), "Solgar"),
    (re.compile(r"^natrol\b",                    re.I), "Natrol"),
    (re.compile(r"^spring\s+valley\b",           re.I), "Spring Valley"),
    (re.compile(r"^kirkland\b",                  re.I), "Kirkland"),
    (re.compile(r"^nordic\s+naturals\b",         re.I), "Nordic Naturals"),
    (re.compile(r"^vitafusion\b",                re.I), "Vitafusion"),
    (re.compile(r"^culturelle\b",                re.I), "Culturelle"),
    (re.compile(r"^align\b",                     re.I), "Align"),
    (re.compile(r"^metamucil\b",                 re.I), "Metamucil"),
    (re.compile(r"^rainbow\s+light\b",           re.I), "Rainbow Light"),
    (re.compile(r"^country\s+life\b",            re.I), "Country Life"),
    (re.compile(r"^life\s+extension\b",          re.I), "Life Extension"),
    (re.compile(r"^pure\s+encapsulations\b",     re.I), "Pure Encapsulations"),
    (re.compile(r"^goli\b",                      re.I), "Goli"),
    (re.compile(r"^primal\s+harvest\b",          re.I), "Primal Harvest"),
    (re.compile(r"^liquid\s+iv\b",               re.I), "Liquid IV"),
]

def get_brand_family(norm_key: str) -> Optional[str]:
    for pat, family in BRAND_FAMILY_RULES:
        if pat.match(norm_key):
            return family
    return None

# ── Display name ──────────────────────────────────────────────────────────────

_KNOWN_CAPS = {
    "coq10":"CoQ10","co-q10":"CoQ10","areds":"AREDS","areds2":"AREDS 2",
    "dha":"DHA","epa":"EPA","msm":"MSM","sam-e":"SAM-e","5-htp":"5-HTP",
    "b12":"B12","b6":"B6","b2":"B2","b1":"B1","d3":"D3","d2":"D2","k2":"K2",
    "omega-3":"Omega-3","omega-6":"Omega-6","acv":"ACV","dhea":"DHEA",
    "nac":"NAC","gaba":"GABA","ag1":"AG1","usana":"USANA","olly":"OLLY","p3":"P3",
    "50+":"50+","nch":"NCH",
}

def to_display_name(norm_key: str) -> str:
    def _w(s):
        if s in _KNOWN_CAPS: return _KNOWN_CAPS[s]
        result, cap_next = [], True
        for ch in s:
            if ch == " ": result.append(ch); cap_next = True
            elif cap_next and ch.isalpha(): result.append(ch.upper()); cap_next = False
            else: result.append(ch)
        return "".join(result)
    return " ".join(_w(w) for w in norm_key.split())

# ── Normalize key ─────────────────────────────────────────────────────────────

def normalize_key(term: str) -> str:
    t = term.lower().strip()
    t = re.sub(r"\s+", " ", t)

    # Outer stabilization loop: strip parens → admin → size → form → category noise
    # Loops until nothing changes (handles form-suffix reveals trailing paren, etc.)
    prev = None
    while prev != t:
        prev = t
        # Trailing parentheticals (iterative to handle stacked)
        p2 = None
        while p2 != t:
            p2 = t
            t = PAREN_RE.sub("", t).strip()
        t = ADMIN_RE.sub("", t).strip()
        # Size tokens
        p2 = None
        while p2 != t:
            p2 = t; t = SIZE_RE.sub("", t).strip()
        # Form qualifiers
        p2 = None
        while p2 != t:
            p2 = t; t = FORM_SUFFIX_RE.sub("", t).strip()
        # Category noise labels (multiminerals/multivitamins as standalone trailing tokens)
        p2 = None
        while p2 != t:
            p2 = t; t = CATEGORY_NOISE_RE.sub("", t).strip()

    # Normalise dashes/spaces around hyphens (en/em → hyphen, collapse spaces)
    t = re.sub(r"[–—]", "-", t)
    t = re.sub(r"\s*-\s*", "-", t)

    # Normalise ampersands
    t = re.sub(r"\s*&\s*", " and ", t)

    # Normalise "digit plus" → "digit+" (e.g. "50 plus" → "50+")
    t = re.sub(r"(?<=\d)\s+plus\b", "+", t, flags=re.I)

    # Normalise all apostrophe variants to ASCII U+0027 (straight apostrophe).
    _sq = chr(0x27)  # U+0027 via chr() — immune to editor curly-quote substitution
    t = t.replace(chr(0x92),   _sq)  # cp1252 RIGHT SINGLE QUOTATION MARK byte
    t = t.replace(chr(0x2019), _sq)  # Unicode RIGHT SINGLE QUOTATION MARK
    t = t.replace(chr(0x2018), _sq)  # Unicode LEFT  SINGLE QUOTATION MARK
    t = t.replace(chr(0x02bc), _sq)  # MODIFIER LETTER APOSTROPHE (rare)
    return re.sub(r"\s+", " ", t).strip()

# ── Hyphen-merge key ──────────────────────────────────────────────────────────

def hyphen_merge_key(norm_key: str) -> str:
    return re.sub(r"-", " ", norm_key)

# ── Garble key (Pass 3: intra-family dedup) ───────────────────────────────────
# Conservative: only strips parentheticals and normalizes 'plus'.
# Preserves all meaningful variant tokens (Ultra, Men's, Women's, 50+, etc.)

def garble_key(norm_key: str) -> str:
    t = re.sub(r"\s*\([^)]*\)\s*", " ", norm_key)
    t = re.sub(r"(?<=\d)\s+plus\b", "+", t, flags=re.I)
    # Fold gender-possessive variants: women's / womens / women → womens
    # men's / mens / men → mens  (same SKU, reporters drop/vary the apostrophe)
    t = re.sub(r"\bwomen'?s?\b", "womens", t, flags=re.I)
    t = re.sub(r"\bmen'?s?\b",   "mens",   t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip()
    return t

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    stats_only = "--stats-only" in sys.argv
    eprint = lambda *a, **kw: print(*a, file=sys.stderr, **kw)

    eprint("Fetching from openFDA…")
    with urllib.request.urlopen(API_URL) as resp:
        data = json.load(resp)
    raw_results = data["results"]
    raw_total = sum(r["count"] for r in raw_results)
    eprint(f"  {len(raw_results)} raw strings, {raw_total} total reports")

    # ── Pass 1: normalize_key grouping ───────────────────────────────────────
    groups = defaultdict(lambda: {"total_reports":0,"raw_pairs":[],"cont_label":None,"cont_action":None})
    for r in raw_results:
        raw, count = r["term"], r["count"]
        nk = normalize_key(raw)
        groups[nk]["total_reports"] += count
        groups[nk]["raw_pairs"].append((raw, count))
        label, action = get_contamination(raw)
        if label and groups[nk]["cont_label"] is None:
            groups[nk]["cont_label"] = label
            groups[nk]["cont_action"] = action
    eprint(f"  Pass 1 → {len(groups)} groups")

    def _merge_into(canonical, other, log_label):
        groups[canonical]["total_reports"] += groups[other]["total_reports"]
        groups[canonical]["raw_pairs"].extend(groups[other]["raw_pairs"])
        if groups[other]["cont_label"] and groups[canonical]["cont_label"] is None:
            groups[canonical]["cont_label"] = groups[other]["cont_label"]
            groups[canonical]["cont_action"] = groups[other]["cont_action"]
        eprint(f"    {log_label}: '{other}' → '{canonical}'")

    # ── Pass 2: hyphen-merge ──────────────────────────────────────────────────
    hm_canon = {}
    for nk in list(groups):
        hk = hyphen_merge_key(nk)
        if hk not in hm_canon:
            hm_canon[hk] = nk
        elif groups[nk]["total_reports"] > groups[hm_canon[hk]]["total_reports"]:
            hm_canon[hk] = nk
    to_delete = set()
    eprint("  Pass 2 hyphen-merges:")
    for nk in list(groups):
        if nk in to_delete: continue
        canonical = hm_canon[hyphen_merge_key(nk)]
        if canonical != nk:
            _merge_into(canonical, nk, "  hyphen")
            to_delete.add(nk)
    for nk in to_delete: del groups[nk]
    eprint(f"  Pass 2 → {len(groups)} groups")

    # ── Pass 3: garble-merge within brand families ────────────────────────────
    # Group by (family, garble_key); merge all but the highest-count entry
    family_gkey: dict[tuple, list] = defaultdict(list)
    for nk in list(groups):
        fam = get_brand_family(nk)
        if fam:
            family_gkey[(fam, garble_key(nk))].append(nk)

    to_delete = set()
    eprint("  Pass 3 garble-merges:")
    garble_count = 0
    for (fam, gk), nk_list in family_gkey.items():
        if len(nk_list) <= 1: continue
        canonical = max(nk_list, key=lambda nk: groups[nk]["total_reports"])
        for nk in nk_list:
            if nk == canonical or nk in to_delete: continue
            _merge_into(canonical, nk, f"  garble [{fam}]")
            to_delete.add(nk)
            garble_count += 1
    for nk in to_delete: del groups[nk]
    eprint(f"  Pass 3 → {len(groups)} groups ({garble_count} garble-merges)")

    norm_total = sum(g["total_reports"] for g in groups.values())
    assert norm_total == raw_total, f"SANITY FAIL: {norm_total} ≠ {raw_total}"
    eprint(f"  Report count conserved: {norm_total} ✓")

    # ── Build rows ────────────────────────────────────────────────────────────
    rows = []
    for nk, g in groups.items():
        pairs = sorted(g["raw_pairs"], key=lambda x: -x[1])
        cont_l   = g["cont_label"] or ""
        cont_a   = g["cont_action"] or ""
        # "keep" action → treat as clean branded (no exclusion)
        effective_excluded = (cont_a == "exclude")
        etype    = classify_type(nk)
        family   = get_brand_family(nk) or ""
        display  = to_display_name(nk)
        raw_repr = " | ".join(f"{t} ({c})" for t, c in pairs)
        eligible = (g["total_reports"] >= 10) and not effective_excluded
        rows.append({
            "canonical_display_name": display,
            "normalized_key":         nk,
            "type":                   etype,
            "brand_family":           family,
            "total_reports":          g["total_reports"],
            "page_eligible":          eligible,
            "contamination_flag":     cont_l,
            "contamination_action":   cont_a,
            "n_raw_strings_merged":   len(pairs),
            "raw_strings_merged":     raw_repr,
        })
    rows.sort(key=lambda x: -x["total_reports"])

    # ── CSV ───────────────────────────────────────────────────────────────────
    fields = ["canonical_display_name","normalized_key","type","brand_family",
              "total_reports","page_eligible","contamination_flag","contamination_action",
              "n_raw_strings_merged","raw_strings_merged"]
    if not stats_only:
        w = csv.DictWriter(sys.stdout, fieldnames=fields)
        w.writeheader()
        for r in rows: w.writerow(r)

    # ── Stats ─────────────────────────────────────────────────────────────────
    sep = "─"*72
    def thresh(lst, n): return sum(1 for r in lst if r["total_reports"] >= n)

    excl    = [r for r in rows if r["contamination_action"] == "exclude"]
    kept    = [r for r in rows if r["contamination_action"] == "keep"]
    branded = [r for r in rows if r["type"]=="branded" and r["contamination_action"]!="exclude"]
    generic = [r for r in rows if r["type"]=="generic_ingredient" and r["contamination_action"]!="exclude"]

    print(sep)
    print("SUPPLEMENT SIGNAL — NORMALIZATION SUMMARY v2")
    print(sep)
    print(f"  Raw strings: {len(raw_results)}  →  Final groups: {len(rows)}")
    print(f"  Report count: {raw_total} (conserved ✓)")
    print()
    print("── BRANDED (excl contamination-excluded) ─────────────────────────")
    print(f"  Total: {len(branded)}   ≥100: {thresh(branded,100)}   ≥25: {thresh(branded,25)}   ≥10: {thresh(branded,10)}")
    print()
    print("── GENERIC INGREDIENT ────────────────────────────────────────────")
    print(f"  Total: {len(generic)}   ≥100: {thresh(generic,100)}   ≥25: {thresh(generic,25)}   ≥10: {thresh(generic,10)}")
    print()
    print("── EXCLUDED (contamination) ──────────────────────────────────────")
    for r in excl:
        print(f"  [{r['total_reports']:>5}]  {r['canonical_display_name'][:55]}  ({r['contamination_flag']})")
    print()
    print("── KEPT BY EDITORIAL DECISION ────────────────────────────────────")
    for r in kept:
        print(f"  [{r['total_reports']:>5}]  {r['canonical_display_name'][:55]}  ({r['contamination_flag']})")
    print()
    print("── PAGE-ELIGIBLE BRANDED (≥10 reports) ──────────────────────────")
    elig_branded = [r for r in branded if r["page_eligible"]]
    print(f"  {len(elig_branded)} branded pages   {sum(1 for r in elig_branded if r['total_reports']>=100)} at ≥100   {sum(1 for r in elig_branded if r['total_reports']>=25)} at ≥25")
    print()
    print("── SANITY CHECKS ─────────────────────────────────────────────────")
    ok = True
    if norm_total != raw_total:
        print(f"  ✗  Count drift: {norm_total} ≠ {raw_total}"); ok = False
    else:
        print(f"  ✓  Report count conserved ({norm_total})")
    zc = [r for r in rows if r["total_reports"] <= 0]
    if zc: print(f"  ✗  {len(zc)} zero-count entries"); ok = False
    else: print(f"  ✓  No zero-count entries")
    ex4 = [r for r in rows if "exemption" in r["normalized_key"] and r["contamination_action"]!="exclude"]
    if ex4: print(f"  ✗  EXEMPTION 4 not excluded"); ok = False
    else: print(f"  ✓  EXEMPTION 4 excluded")
    gi_fam = [r for r in rows if r["type"]=="generic_ingredient" and r["brand_family"]]
    if gi_fam: print(f"  ✗  {len(gi_fam)} generic_ingredient entries have brand_family set")
    else: print(f"  ✓  No generic_ingredient entries with brand_family")
    print(f"  ⚠  Per-entity death check: DEFERRED to ingestion pipeline")
    if ok: print(f"\n  All automated checks passed.")
    print(sep)

if __name__ == "__main__":
    main()
