# SupplementFiles

**[supplementfiles.com](https://supplementfiles.com)** — FDA dietary supplement adverse event reports, made legible.

SupplementFiles takes raw data from the FDA's CFSAN Adverse Event Reporting System (CAERS) and turns it into clean, searchable pages for consumers. When someone searches a supplement, they see what real people have reported to the FDA: reactions, outcomes, who was affected, and how reports have changed over time — in plain language with the proper context.

---

## What's in the site

- **123 product pages** — one per supplement with ≥25 FDA reports, covering ~22,800 adverse event reports across 444 tracked products
- **A–Z browse index** with category filters
- **Full-text search** powered by [Pagefind](https://pagefind.app) (runs entirely client-side, no server)
- **Editorial guides** explaining the data (how to read an FDA report, melatonin side effects, how to report to the FDA)
- **Sitemap, robots.txt, Open Graph / Twitter cards, favicons** — all generated at build time

---

## How it works

This is a static site generator, not a CMS or web app.

```
data/supplement_full_catalog.json   ← source of truth (processed FDA bulk data)
        ↓
scripts/generate-pages.js           ← reads catalog, writes docs/*.html
        ↓
npx pagefind --site docs            ← builds client-side search index
        ↓
docs/                               ← output pushed to Cloudflare Pages
```

Every page is plain HTML. No client-side rendering, no database. Fully crawlable without JavaScript.

### Build

```bash
npm install
npm run build
# or: node scripts/generate-pages.js && npx pagefind --site docs
```

Output goes to `docs/` (gitignored — regenerated on every build). Favicons and OG images are generated automatically at the start of the build step via `scripts/generate-assets.js`.

---

## Data source

Raw data: [FDA CAERS bulk download](https://www.fda.gov/food/compliance-enforcement-regulatory-information/cfsan-adverse-event-reporting-system-caers) — the dietary supplement subset of the food/cosmetics adverse event database.

The `pipeline/` scripts handle ingestion: download the bulk file, filter to dietary supplements, normalize brand names, compute reactions/outcomes/demographics/yearly trends, and write `data/supplement_full_catalog.json`. This step runs offline; the committed JSON file is the build input.

**Important framing:** CAERS data reflects *voluntary reports*, not clinical trials. A report doesn't mean the supplement caused the event. All pages carry this disclaimer.

---

## Deployment

Hosted on [Cloudflare Pages](https://pages.cloudflare.com), auto-deployed on push to `main`.

| Setting | Value |
|---|---|
| Build command | `node scripts/generate-pages.js && npx pagefind --site docs` |
| Output directory | `docs` |
| Node.js version | 18+ |

---

## Tech

- **Generator:** Node.js (CommonJS), no framework
- **Search:** Pagefind (static index)
- **Hosting:** Cloudflare Pages
- **Analytics:** GA4
- **Assets:** [sharp](https://sharp.pixelplumbing.com) for favicon/OG image generation
- **Fonts:** Newsreader (headings) + Public Sans (body) via Google Fonts

---

## Sibling project

[PillSignal](https://pillsignal.com) — same model, same architecture, FDA drug adverse event data (FAERS).
