# CLAUDE.md — SupplementFiles

## Project Overview

SupplementFiles (supplementfiles.com) is a consumer-facing website that makes FDA
dietary-supplement adverse-event data accessible and understandable. When someone searches a
supplement, they see what real people reported to the FDA — reactions, outcomes, demographics,
and trends over time — in clean visualizations with plain-English context, plus editorial guides
that explain the data.

Data source: the openFDA CAERS API (CFSAN Adverse Event Reporting System — food, dietary
supplements, cosmetics). SupplementFiles surfaces real-world *reported events*, not product-label
or marketing claims — an underserved dataset distinct from retailers and WebMD-style sites.
Sibling project to PillSignal (same model, FDA drug data). YMYL (health) content: accuracy and
careful framing are paramount.

Goal: become a top result for "[supplement] side effects / reactions / adverse events" queries,
and monetize via Google AdSense once approved.

## Legal & Editorial Requirements — READ THIS FIRST

Non-negotiable. Apply to all code, copy, and content:

1. **Per-page disclaimer.** Every page carries (or closely varies): *"This data reflects
   voluntary reports submitted to the FDA (CAERS). A report does not mean the supplement caused
   the event, and the data may be incomplete or contain errors."*
2. **Never imply causation.** Use "reported with" / "reported by people taking," never "caused
   by" or "side effect of."
3. **Never rank by harm.** No "most dangerous," "worst," or comparative safety framing.
4. **No safety judgments.** Don't call a product "dangerous," "risky," "safe," or "concerning."
   Present the data; let readers conclude.
5. **Counts, never rates.** Never publish a death/serious percentage as a headline. Counts
   reflect reporting, not incidence.
6. **No medical advice.** Route specifics to "talk to a doctor or pharmacist," and include a
   not-a-substitute-for-professional-care notice.
7. **Always link to the FDA source.** Every product page links to its openFDA/CAERS query so
   readers can verify.
8. **First-visit disclaimer banner.** Non-blocking, dismissible, remembered via localStorage
   (shows once). Must NOT block content or crawlers. Text: *"SupplementFiles presents data from
   the FDA's voluntary reporting system. This data does not prove a supplement caused any adverse
   event. Always consult your healthcare provider."* with an "I understand" button.

**Editorial voice (the one nuance):** our guides DO have a voice — but it is anchored to
*factual findings*, never to judgments. "The most-reported reaction was choking" (a fact) is
encouraged; "supplement X is dangerous" (a judgment) is forbidden. Lead with findings from our
own data; keep rules 2–4 fully intact inside editorial.

**Naming a misconception to reject it is fine.** Framing like "the useful move isn't
'supplements are dangerous' or 'supplements are fine'" is teaching, not a safety judgment —
it is explicitly negating the framing, not endorsing it. Do not soften or remove these
constructions.

**"Side effects" is acceptable in SEO titles and meta descriptions** as the searcher's
category term, provided a report-framing qualifier accompanies it (e.g. "Melatonin Side
Effects: What the FDA's Reports Show"). The rule 2 causation ban applies to body-copy claims,
not to page titles. Do not strip "side effects" from titles.

## Data Integrity Rules (non-negotiable)

- **Reactions denylist:** exclude Death and outcome/administrative terms from reaction charts.
  Death appears only under Outcomes.
- **Sanity gates fail loudly:** deaths ≤ total reports; count–detail reconciliation ≥99%.
- **SKU-level pages.** Merge only orthographic garbles of the same SKU into its canonical form;
  never merge distinct SKUs; never sum across SKUs on hub pages (list individually).
- **Standalone-page threshold:** ≥25 reports, clean. Below that, products appear only in
  browse/hub listings. Generic-ingredient names are held for ingredient-aggregation pages —
  exception: discrete, searchable ingredients (kratom, melatonin) may be published as
  aggregation pages.
- **data_character tagging:** organic / event_cluster / organic_recent_emerging / held. Show a
  cluster-context line only on event_cluster and recent-emerging pages, and make the text
  accurate to the real pattern (recall/litigation vs. adoption trend).
- **Exclude non-supplement contamination** (foods, drugs) from the catalog.

## Tech Stack

- **Data source:** openFDA CAERS API (food/event.json), filtered to the dietary-supplement
  industry category.
- **Data store:** local bulk CAERS file committed to the repo (no external DB). Deliberate —
  fixes `+`/encoding query bugs and keeps builds offline-stable.
- **CAERS naming note (2026):** The FDA retired its consumer-facing CAERS info page
  (fda.gov/…/cfsan-adverse-event-reporting-system-caers → now 404/redirects to HFCS).
  The FDA's new consumer-facing name for this data is **HFCS** (Human Foods Complaint System);
  the backend consolidation is called **AEMS** (Adverse Event Management System, launched
  March 2026). However, the openFDA API (`/food/event.json`) and its docs still self-identify
  the source as "CAERS" with current data (last updated May 2026). Keep all site copy as
  "CAERS" until openFDA itself renames or redirects the endpoint — revisit at that point.
- **Build:** Node.js — `node scripts/generate-pages.js && npx pagefind --site docs`. Page generation calls `generate-assets.js` as its first step (via `execFileSync`), so favicons and OG images are always produced before pages are written — no separate assets step needed. `npm run build` runs the same command and also works.
- **Search:** Pagefind (static index over `docs/`).
- **Frontend:** static HTML/CSS/JS — no SPA, no client-side rendering of main content. Every
  page must be fully readable by crawlers without executing JS.
- **Hosting:** Cloudflare Pages, auto-deploy on push to `main`. Output dir `docs/` (gitignored;
  regenerated by build — never hand-edit).
- **DNS/CDN:** Cloudflare (supplementfiles.com).
- **Email:** hello@supplementfiles.com.
- **Analytics:** GA4 `G-6VHWEWTGNM`. Custom event schema (keep identical across sibling sites):
  | Event | Trigger | Params |
  |---|---|---|
  | `search_query` | Search input ≥3 chars, 500ms debounce, dedupe | `search_term` |
  | `search_result_click` | Pagefind result link clicked | `item_name`, `item_slug` |
  | `related_item_click` | Related product chip clicked on product page | `source_item`, `target_item` |
  | `fda_source_click` | Any openFDA/CAERS/Safety Reporting Portal link | `item_name`, `destination_url` |
  | `browse_letter_click` | A–Z letter header clicked on browse page | `letter` |
  | `dark_mode_toggle` | Theme toggle clicked | `new_theme` (`"light"`/`"dark"`) |
  | `faq_open` | *(not wired — FAQ is static text, no accordion interaction)* | — |
- **Monetization:** Google AdSense — NOT yet active (see no-ads rule below).

## Architecture

Two-stage, like PillSignal but DB-free: (1) ingest the openFDA CAERS bulk data and normalize it
locally into the committed data file; (2) `generate-pages.js` reads that file and emits static
HTML into `docs/`, then Pagefind builds the search index. Static HTML = instantly indexable, no
JS rendering required. Scaling to more products = process more of the data file; no architectural
change. Do not redesign this without flagging it first.

## Site & SEO Conventions

SEO is the primary growth channel — every decision considers indexability.

- **URLs:** products `/supplements/<slug>/`, guides `/guides/<slug>/`. Clean trailing-slash URLs.
- **Per page:** unique `<title>` + `<meta description>`; canonical URL; Open Graph + Twitter
  Card tags; JSON-LD schema.org (WebSite / Organization / Dataset / CollectionPage / FAQPage /
  Article as appropriate).
- **Guides:** SEO title + meta; Article schema; **bidirectional internal links** (guide →
  relevant product pages + methodology + related guides; homepage/footer → guides). Keep the
  guides index current.
- **Internal cross-linking** between related products (brand family, similar profiles).
- **sitemap.xml** auto-generated on build; submit to Google Search Console AND Bing Webmaster
  Tools.
- **robots.txt** allows all crawlers.
- **Fast, mobile-first, dark mode** (CSS custom properties, `prefers-color-scheme`, manual toggle
  persisted in localStorage). Optimize for Core Web Vitals. Accessible: semantic HTML, heading
  hierarchy, alt text, sufficient contrast.

## Page Content Spec

**Product page:** supplement name (H1); summary line (total reports); top reactions (chart/table,
counts, denylist applied); demographics (age, sex); outcome severity (counts); reports-over-time
trend; cluster-context line if applicable; FDA disclaimer; FDA source link; related products.

**Guide:** data-first lead (a finding, not a definition); factual voice; the disclaimers;
bidirectional links to relevant products + methodology + related guides.

**Prose type scale (guides, About, Methodology — `.article-body` and `.meth-body` containers):**
h2: 1.7rem / weight 600 / Newsreader / margin-top 2.5rem, margin-bottom 0.6rem / hairline
border-bottom. h3: 1.3rem / weight 600 / margin-top 1.8rem, margin-bottom 0.4rem. Body: 1.0625rem,
line-height 1.65–1.78, paragraph margin-bottom 1.1rem. Mobile (≤540px): h2→1.5rem, h3→1.15rem.
Do NOT apply this scale to product-page elements (hero, stat figures, outcomes table).

**Unified editorial column:** All editorial pages (guides, About, Methodology, FAQ, and other prose
pages) use a `max-width:960px` outer wrapper — the same frame as the rest of the site. Within that
frame, prose text is constrained to `max-width:68ch` via `.article-body` (guides) or per-element
rules (`.meth-body p/h2/h3/li`). This keeps guide and About/Methodology text at the same left
edge and the same line-wrap width. Do NOT center guides in a narrow 68ch outer wrapper — that
pushes the column right and makes guides look narrower than About.

## Editorial / Content

- **Data-first:** lead with findings from our own data, not generic definitions. This is the
  originality lever for AdSense and ranking.
- **Brand-only voice:** "the SupplementFiles team." Never a personal name.
- **Hold policy-sensitive topics** (e.g. kratom) out of *featured editorial* until after AdSense
  approval; factual product pages are fine.
- **No advertising anywhere until AdSense is approved** — no ad code, no placeholder ad slots, no
  ad mentions in Privacy/Terms. Re-add (plus a consent CMP for EEA/UK) at approval.

## Session Discipline

- Read data from disk; never dump raw datasets into the conversation (long sessions hit the
  1M-context limit). Keep sessions lean, one task at a time, standard-context model.
- Work from the local bulk file, not live per-product API queries.
- Report concise summaries, not raw dumps.

## Development Principles

- **Think first, build second.** Don't scaffold, generate, or restructure without explicit
  instruction — ask before acting.
- **Don't redesign the architecture** above without flagging it first.
- **Every page is real static HTML**, crawlable without JS.
- **Security:** never commit secrets; openFDA key (if used) goes in `.env`.

## Deployment

- Commit and push to `main`; Cloudflare Pages auto-builds
  (`node scripts/generate-pages.js && npx pagefind --site docs`, output `docs/`).
  Favicons are generated automatically inside `generate-pages.js` — no dashboard change needed.
- Update `sitemap.xml` for any page changes; rebuild before committing.
- After deploy, verify new/updated pages in Google Search Console (and Bing).

## Canonical Reference

The project brief is the source of truth for architecture and judgment calls. Keep it in the
repo; consult it for template, content, and expansion decisions. (If committed, wire it in:
`@docs/project-brief.md`.)

## Maintaining This File

This file is the source of truth: it leads, the code follows. Keep it current and keep it sharp.

- When a task **changes a convention or rule already documented here**, update this file to
  match and note the change in your report (e.g. "updated CLAUDE.md: dropped the governing-law
  clause").
- **Ask before adding** a new rule, section, or restructuring — propose it, don't silently grow
  the file.
- Don't bloat it: no one-off task details, no restating existing rules. If guidance gets long or
  specialized, flag it for splitting out rather than piling on.
- Conversation-only instructions are lost on /clear and compaction. If an instruction should
  persist across sessions, it belongs here.
