# CLAUDE.md — SupplementSignal

## Project Overview

SupplementSignal is a free consumer website that makes FDA dietary-supplement adverse-event data searchable and legible. It's the PillSignal pattern applied to supplements.

**Data source:** openFDA CAERS (`https://api.fda.gov/food/event.json`) filtered to `Vit/Min/Prot/Unconv Diet` industry.

**Status:** MVP dataset built (32 products), page generator written, pages generating. Next: homepage, sitemap, GitHub Pages deploy.

## Legal Requirements — NON-NEGOTIABLE

1. Every page must carry the caveat: "These are reports submitted to the FDA. A report does not mean the product caused the effect. Counts reflect reporting activity, not how common an effect is."
2. Never publish derived percentages (deaths/reports, % serious) as headline metrics. Absolute counts only.
3. Never imply causation. Use "reported with," "associated reports," never "caused by" or "side effects of."
4. Never editorialize — no "dangerous," "risky," "safe," "concerning" applied to any product.
5. Never merge distinct SKUs — "Centrum Silver Women's 50+" ≠ "Centrum Silver Ultra." Each SKU stands alone.
6. Never sum brand-family counts — hub pages list per-SKU counts, never a total.
7. Always link to the FDA source (openFDA CAERS).
8. Cluster context block renders ONLY for event_cluster and organic_recent_emerging products — never for organic.

## Tech Stack

- **Frontend:** Vanilla HTML, CSS, JavaScript — no frameworks, no bundler, no build tools
- **Build:** Node.js script (`scripts/generate-pages.js`) reads JSON → writes static HTML
- **Data:** `data/supplement_mvp_final_v2.json` (32 MVP products, keyed by canonical_display_name)
- **Pipeline scripts:** `pipeline/` directory (Python — do not run without explicit instruction)
- **Output:** `docs/` directory → GitHub Pages
- **Hosting:** GitHub Pages (same pattern as PillSignal at pillsignal.com)

## Architecture

### Data Schema (one record)

```
{
  canonical_display_name: "Centrum Silver Women's 50+",
  normalized_key: "centrum silver women's 50+",
  type: "branded",
  brand_family: "Centrum Silver",
  total_reports: 1415,
  page_eligible: true,
  reactions: { top_reactions: [{term, count, pct}] },
  outcomes: { "Outcome Name": {count, pct} },
  demographics: {
    gender: { Female, Male, "Unknown/Not Reported" },
    age_bands: { under_18, 18_34, 35_49, 50_64, 65_79, 80_plus, unknown, median_age, n_with_age }
  },
  yearly_trend: { "2004": 0, "2005": 0, ... },
  data_character: "organic" | "event_cluster" | "organic_recent_emerging" | "held",
  cluster_context: "...",  // render only for event_cluster / organic_recent_emerging
  sanity_checks: { deaths, total_reports, deaths_lte_total_reports }
}
```

### URL Structure

- Product pages: `/supplements/<brand-slug>/` → `docs/supplements/<brand-slug>/index.html`
- Hub pages: `/supplements/<family-slug>/` → `docs/supplements/<family-slug>/index.html`
- Methodology: `/methodology/` → `docs/methodology/index.html`
- Homepage: `/` → `docs/index.html` (not yet built)

### Slug collision resolution

When a product's slug == its brand_family slug (e.g. product "Centrum Silver" vs. hub "Centrum Silver"), the product page gets a `-supplement` suffix. The hub gets the clean family slug.

### Build command

```bash
node scripts/generate-pages.js
```

No dependencies. Regenerates all pages from the JSON data.

## Product Page Anatomy

1. Breadcrumb → brand family hub
2. Hero: H1 (product name), category pill, big report count, date range
3. **Caveat band** (permanent, warm amber, always visible)
4. Reactions card: top 10 horizontal CSS bars — counts only, no %
5. Outcomes card: table — counts only, NO percentages, NO "death rate"
6. **Affiliate slot** (visually distinct, dashed green border — placeholder)
7. Demographics card: age bands + gender as CSS bars — counts only
8. Trend card: CSS vertical histogram by year
9. **Cluster block** (only for event_cluster / organic_recent_emerging) — blue left-border
10. Related products + hub link card
11. Data source card

## Framing Rules (from project brief §6F)

- Never publish a deaths/reports ratio or "% serious" as a headline metric
- Derived percentages are for internal anomaly detection only
- The affiliate slot goes after Outcomes (natural decision point — user has seen risk info)

## SEO

- `<title>`: `{Product Name} — FDA Adverse Event Reports | SupplementSignal`
- `<meta description>`: includes total reports, date range
- JSON-LD: Dataset schema on product pages, CollectionPage on hubs
- Canonical URLs on every page
- No sitemap.xml yet — add in next session

## Development Principles

- No frameworks. Vanilla HTML/CSS/JS only.
- Every page is self-contained static HTML — crawlers read all content without JS.
- CSS is embedded in each page (no external stylesheet yet — extract in Phase 2).
- Mobile-first. Dark mode via CSS custom properties + localStorage toggle.
- The `docs/` directory is what GitHub Pages serves.
- Never use absolute counts with "%" framing for outcomes or reactions on public pages.

## Key Files

- `scripts/generate-pages.js` — the page generator (run to rebuild all pages)
- `data/supplement_mvp_final_v2.json` — MVP dataset (32 products)
- `pipeline/` — Python ingestion scripts (do not run without instruction)
- `docs/supplements/` — generated product and hub pages
- `docs/methodology/` — about/methodology page

## What's Not Built Yet

- `docs/index.html` — homepage with search/browse
- `docs/supplements/index.html` — browse all supplements listing
- `docs/sitemap.xml` — auto-generated sitemap
- `docs/robots.txt`
- GitHub repo + Pages configuration
- Favicon, OG image

## Environment Variables (for Phase 2 — live data refresh)

```
OPENFDA_API_KEY=   # openFDA API key for higher rate limits
```
