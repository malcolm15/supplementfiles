# SupplementFiles

FDA dietary supplement adverse event reports, made legible.

SupplementFiles makes data from the FDA's CFSAN Adverse Event Reporting System (CAERS) understandable to regular people. Search any supplement and see what people have actually reported to the FDA — reactions, outcomes, demographics, and trends over time — presented in plain English with clear context.

This is different from what WebMD or retailer sites provide. Those show label information and marketing claims. SupplementFiles shows real-world reported events from the public CAERS database.

## Important Disclaimer

SupplementFiles presents voluntary reports submitted to the FDA. A report does not mean a supplement caused any adverse event. This data may be incomplete or contain errors. SupplementFiles is not a substitute for professional medical advice. Always consult your healthcare provider.

## Status

Live at [supplementfiles.com](https://supplementfiles.com).

## Tech Stack

- **Data:** FDA CAERS bulk download
- **Build scripts:** Node.js
- **Search:** Pagefind (client-side, static)
- **Frontend:** Vanilla HTML, CSS, JavaScript — no frameworks
- **Hosting:** Cloudflare Pages

## How It Works

A Node.js pipeline ingests the FDA CAERS bulk data, filters it to dietary supplements, and normalizes it into a local JSON catalog. A second script reads that catalog and generates static HTML pages — one per supplement. Pagefind then builds a client-side search index over the output.

## Data Source

All data is sourced from the FDA's CFSAN Adverse Event Reporting System via the openFDA API and bulk downloads. SupplementFiles is not affiliated with the FDA.

## Sibling Project

[PillSignal](https://pillsignal.com) — same model, FDA drug adverse event data (FAERS).
