#!/usr/bin/env node
'use strict';

const fs   = require('fs');
const path = require('path');

// ─── Config ───────────────────────────────────────────────────────────────────
const BASE_URL       = 'https://supplementfiles.com';
const CURRENT_DATE   = '2026-06-03';
const FORMATTED_DATE = 'June 3, 2026';
const DATA_FILE      = path.join(__dirname, '../data/supplement_mvp_final_v2.json');
const OUT_DIR        = path.join(__dirname, '../docs');
const GA4_ID         = 'G-6VHWEWTGNM'; // SupplementFiles GA4 property

// ─── Category labels (by brand family / product name substring) ───────────────
const CATEGORY_MAP = [
  ['Centrum Silver',        'Multivitamin'],
  ['Centrum',               'Multivitamin'],
  ['One A Day',             'Multivitamin'],
  ['Flintstones',           "Children's Multivitamin"],
  ['PreserVision',          'Eye Health Supplement'],
  ['Super Beta Prostate',   'Prostate Health Supplement'],
  ['Citracal',              'Calcium Supplement'],
  ['Hydroxycut',            'Weight Loss Supplement'],
  ['5 Hour Energy',         'Energy Supplement'],
  ['Kratom',                'Botanical Supplement'],
  ['Benefiber',             'Fiber Supplement'],
  ['Nutrafol',              'Hair Growth Supplement'],
  ['Virility',              'Male Enhancement Supplement'],
  ['All Day Energy',        'Energy Supplement'],
];

function getCategory(p) {
  const haystack = `${p.canonical_display_name} ${p.brand_family || ''}`;
  for (const [key, label] of CATEGORY_MAP) {
    if (haystack.includes(key)) return label;
  }
  return 'Dietary Supplement';
}

// ─── Reactions denylist ───────────────────────────────────────────────────────
// Excludes outcome-status, healthcare-process, administrative, and efficacy terms
// that are miscategorized as reactions. Death remains fully visible in the Outcomes section.
const REACTIONS_DENYLIST = new Set([
  // Death / mortality outcomes
  'Death', 'DEATH', 'Accidental death',
  // Healthcare process / disposition
  'Hospitalisation', 'HOSPITALISATION', 'Emergency care', 'GASTRIC LAVAGE',
  // Administrative / reporter-context
  'INCORRECT DOSE ADMINISTERED', 'DRUG EXPOSURE DURING PREGNANCY',
  'FAILURE OF CHILD RESISTANT MECHANISM FOR PHARMACEUTICAL PRODUCT',
  'ACCIDENTAL DRUG INTAKE BY CHILD', 'Accidental exposure to product by child',
  // Report-quality / non-specific
  'UNEVALUABLE EVENT', 'Illness',
  // Efficacy / quality complaints
  'THERAPEUTIC RESPONSE UNEXPECTED',
]);

// ─── Per-product context notes ────────────────────────────────────────────────
// Used when the denylist removes terms that represent a real safety pattern.
// Map: canonical_display_name → function(product) → HTML string | ''
// <!-- REVIEW --> comments flag notes for copy refinement before launch.
const PRODUCT_CONTEXT_NOTES = {
  'Flintstones Complete': (p) => {
    const childTerms = new Set([
      'ACCIDENTAL DRUG INTAKE BY CHILD',
      'Accidental exposure to product by child',
      'FAILURE OF CHILD RESISTANT MECHANISM FOR PHARMACEUTICAL PRODUCT',
    ]);
    const childCount = p.reactions.top_reactions
      .filter(r => childTerms.has(r.term))
      .reduce((sum, r) => sum + r.count, 0);
    if (!childCount) return '';
    // <!-- REVIEW: refine wording before launch -->
    return `<!-- REVIEW: accidental child ingestion note — refine wording before launch -->
    <div class="cluster-block" id="child-safety-note">
      <strong>Accidental ingestion by children:</strong> A notable share of these reports involve accidental ingestion by children. Keep gummy vitamins stored safely out of reach.
    </div>`;
  },
};

// ─── Utilities ────────────────────────────────────────────────────────────────
function slug(s) {
  return String(s).toLowerCase()
    .replace(/\+/g, '-plus')
    .replace(/'/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/-{2,}/g, '-')
    .replace(/^-+|-+$/g, '');
}

function esc(s) {
  return String(s || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function fmt(n) {
  return Number(n).toLocaleString('en-US');
}

function ensure(d) {
  fs.mkdirSync(d, { recursive: true });
}

function dateRange(trend) {
  const yrs = Object.entries(trend)
    .filter(([, v]) => v > 0)
    .map(([k]) => parseInt(k));
  if (!yrs.length) return 'N/A';
  return `${Math.min(...yrs)}–${Math.max(...yrs)}`;
}

// Title-case all-caps MedDRA terms (e.g. "FOREIGN BODY TRAUMA" → "Foreign Body Trauma")
function meddraTerm(t) {
  if (t === t.toUpperCase() && t.length > 3) {
    return t.split(' ').map(w => w.charAt(0) + w.slice(1).toLowerCase()).join(' ');
  }
  return t;
}

// ─── CSS (embedded in every page) ────────────────────────────────────────────
const INLINE_CSS = `
<style>
  /* ── Tokens ────────────────────────────────────────────────────────────── */
  :root,[data-theme="light"]{
    --bg:#ffffff;--surface:#f8fafc;--border:#e2e8f0;
    --text:#0f172a;--muted:#64748b;
    --primary:#00A67E;--primary-h:#008F6B;--primary-l:#e6f9f1;
    --caveat-bg:#fffbeb;--caveat-b:#f59e0b;--caveat-t:#92400e;
    --cluster-bg:#eff6ff;--cluster-b:#3b82f6;--cluster-t:#1e40af;
    --banner-bg:#fffbeb;--banner-t:#92400e;--banner-b:rgba(146,64,14,.3);
    --aff-bg:#f0fdf4;--aff-b:#86efac;--aff-t:#166534;
    --bar:#00A67E;--track:#e2e8f0;
    --font:system-ui,-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;
  }
  [data-theme="dark"]{
    --bg:#0f172a;--surface:#1e293b;--border:#334155;
    --text:#f1f5f9;--muted:#94a3b8;
    --primary:#34d1a0;--primary-h:#2bbd8e;--primary-l:#0d3d2e;
    --caveat-bg:#1c1508;--caveat-b:#d97706;--caveat-t:#fcd34d;
    --cluster-bg:#172554;--cluster-b:#3b82f6;--cluster-t:#93c5fd;
    --banner-bg:#1c1508;--banner-t:#d4b896;--banner-b:rgba(212,184,150,.25);
    --aff-bg:#052e16;--aff-b:#166534;--aff-t:#86efac;
    --bar:#34d1a0;--track:#273344;
  }

  /* ── Reset ─────────────────────────────────────────────────────────────── */
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  body{font-family:var(--font);font-size:1rem;line-height:1.6;color:var(--text);background:var(--bg);transition:background .2s,color .2s}
  a{color:var(--primary);text-decoration:none}
  a:hover{text-decoration:underline;color:var(--primary-h)}
  h1,h2,h3{line-height:1.25}
  ::-webkit-scrollbar{width:8px;height:8px}
  ::-webkit-scrollbar-track{background:var(--surface)}
  ::-webkit-scrollbar-thumb{background:var(--border);border-radius:4px}

  /* ── Theme toggle ───────────────────────────────────────────────────────── */
  .theme-toggle{display:flex;align-items:center;justify-content:center;width:32px;height:32px;background:none;border:1px solid var(--border);border-radius:6px;cursor:pointer;color:var(--muted);padding:0;flex-shrink:0;transition:color .15s,border-color .15s,background .15s}
  .theme-toggle:hover{color:var(--primary);border-color:var(--primary);background:var(--primary-l)}
  [data-theme="light"] .icon-sun{display:none}
  [data-theme="dark"]  .icon-moon{display:none}

  /* ── Disclaimer banner ──────────────────────────────────────────────────── */
  #disclaimer-banner{background:var(--banner-bg);color:var(--banner-t);font-size:.875rem;line-height:1.5;border-bottom:1px solid var(--banner-b)}
  .banner-seen #disclaimer-banner{display:none}
  .banner-inner{max-width:960px;margin:0 auto;padding:.75rem 1rem;display:flex;align-items:center;gap:1rem;flex-wrap:wrap}
  .banner-inner p{flex:1;min-width:200px}
  #banner-btn{flex-shrink:0;background:transparent;border:1px solid var(--banner-b);color:var(--banner-t);padding:.3rem 1rem;border-radius:4px;cursor:pointer;font-size:.8rem;font-family:var(--font);white-space:nowrap;transition:background .15s}
  #banner-btn:hover{background:rgba(0,0,0,.05)}

  /* ── Site header ────────────────────────────────────────────────────────── */
  .site-header{border-bottom:1px solid var(--border);padding:.875rem 1rem;background:var(--bg);position:sticky;top:0;z-index:10}
  .site-header .inner{max-width:960px;margin:0 auto;display:flex;align-items:center;justify-content:space-between;gap:1rem}
  .logo{font-size:1.1rem;font-weight:700;color:var(--primary);letter-spacing:-.02em}
  .logo:hover{text-decoration:none;color:var(--primary-h)}
  .header-nav{display:flex;align-items:center;gap:.75rem}
  .header-link{font-size:.875rem;color:var(--muted)}
  .header-link:hover{color:var(--primary);text-decoration:none}

  /* ── Layout ─────────────────────────────────────────────────────────────── */
  main{max-width:960px;margin:0 auto;padding:2rem 1rem 4rem}

  /* ── Product hero ────────────────────────────────────────────────────────── */
  .product-hero{margin-bottom:1.5rem}
  .product-hero h1{font-size:clamp(1.6rem,4vw,2.1rem);font-weight:800;letter-spacing:-.03em;color:var(--text);margin-top:.4rem}
  .cat-pill{display:inline-flex;align-items:center;background:var(--primary-l);color:var(--primary-h);font-size:.72rem;font-weight:700;padding:.2rem .7rem;border-radius:20px;letter-spacing:.04em;text-transform:uppercase}
  [data-theme="dark"] .cat-pill{color:var(--primary)}
  .product-meta{margin-top:.5rem;font-size:.875rem;color:var(--muted);line-height:1.6}
  .product-meta .big-count{font-size:1.4rem;font-weight:800;color:var(--text);font-variant-numeric:tabular-nums;letter-spacing:-.02em}
  .breadcrumb{font-size:.8rem;color:var(--muted);margin-bottom:.75rem}
  .breadcrumb a{color:var(--muted)}
  .breadcrumb a:hover{color:var(--primary)}

  /* ── Caveat band ─────────────────────────────────────────────────────────── */
  .caveat-band{background:var(--caveat-bg);border-left:4px solid var(--caveat-b);border-radius:0 6px 6px 0;padding:.875rem 1rem .875rem 1.25rem;font-size:.875rem;color:var(--caveat-t);margin-bottom:2rem;line-height:1.6}

  /* ── Section cards ───────────────────────────────────────────────────────── */
  .card{background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:1.5rem;margin-bottom:1.25rem}
  .card h2{font-size:1.05rem;font-weight:700;color:var(--text);margin-bottom:.3rem}
  .section-note{font-size:.8rem;color:var(--muted);line-height:1.5;margin-bottom:1.25rem}

  /* ── Reaction bars ───────────────────────────────────────────────────────── */
  .bars-list{display:flex;flex-direction:column;gap:.55rem}
  .bar-row{display:grid;grid-template-columns:minmax(0,11rem) 1fr 4.5rem;align-items:center;gap:.625rem}
  @media(max-width:480px){.bar-row{grid-template-columns:minmax(0,8rem) 1fr 3.5rem;font-size:.875rem}}
  .bar-label{font-size:.875rem;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .bar-track{background:var(--track);border-radius:4px;height:20px;overflow:hidden}
  .bar-fill{background:var(--bar);height:100%;border-radius:4px;transition:width .4s ease}
  .bar-count{font-size:.8rem;color:var(--muted);text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}

  /* ── Outcomes table ──────────────────────────────────────────────────────── */
  .outcomes-table{width:100%;border-collapse:collapse;font-size:.875rem}
  .outcomes-table th{text-align:left;padding:.5rem .75rem;color:var(--muted);font-weight:600;font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;border-bottom:2px solid var(--border)}
  .outcomes-table td{padding:.55rem .75rem;border-bottom:1px solid var(--border);color:var(--text);vertical-align:top}
  .outcomes-table tr:last-child td{border-bottom:none}
  .outcomes-table .count-cell{text-align:right;font-variant-numeric:tabular-nums;color:var(--muted);white-space:nowrap}

  /* ── Demographics ────────────────────────────────────────────────────────── */
  .demo-grid{display:grid;grid-template-columns:1fr 1fr;gap:1.5rem}
  @media(max-width:560px){.demo-grid{grid-template-columns:1fr}}
  .demo-block h3{font-size:.8rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin-bottom:.875rem}

  /* ── Year histogram ──────────────────────────────────────────────────────── */
  .hist-outer{overflow-x:auto;padding-bottom:.25rem}
  .hist-bars{display:flex;align-items:flex-end;gap:4px;height:90px;min-width:min-content}
  .hist-col{display:flex;flex-direction:column;align-items:center;width:26px;flex-shrink:0}
  @media(max-width:600px){.hist-col{width:20px}}
  .hist-bar{width:100%;background:var(--bar);border-radius:3px 3px 0 0;transition:background .2s;cursor:default;min-height:0}
  .hist-bar:hover{background:var(--primary-h)}
  .hist-labels{display:flex;gap:4px;margin-top:4px}
  .hist-year{width:26px;flex-shrink:0;font-size:.57rem;color:var(--muted);text-align:center;white-space:nowrap}
  @media(max-width:600px){.hist-year{width:20px;font-size:.5rem}}

  /* ── Cluster context ─────────────────────────────────────────────────────── */
  .cluster-block{background:var(--cluster-bg);border-left:4px solid var(--cluster-b);border-radius:0 6px 6px 0;padding:.875rem 1rem .875rem 1.25rem;font-size:.875rem;color:var(--cluster-t);margin-bottom:1.25rem;line-height:1.6}
  .cluster-block strong{font-weight:700}

  /* ── Affiliate slot ──────────────────────────────────────────────────────── */
  .aff-slot{background:var(--aff-bg);border:1px dashed var(--aff-b);border-radius:8px;padding:1.25rem;margin-bottom:1.25rem;text-align:center;color:var(--aff-t);font-size:.875rem}
  .aff-slot strong{font-weight:600;display:block;margin-bottom:.25rem;font-size:.9rem}
  .aff-slot p{color:var(--muted);font-size:.8rem;margin-top:.25rem}

  /* ── Hub list ────────────────────────────────────────────────────────────── */
  .hub-list{list-style:none;display:flex;flex-direction:column;gap:.5rem}
  .hub-sku{display:flex;align-items:center;justify-content:space-between;padding:.75rem 1rem;background:var(--surface);border:1px solid var(--border);border-radius:8px;gap:1rem;flex-wrap:wrap;transition:border-color .15s}
  .hub-sku:hover{border-color:var(--primary)}
  .hub-sku a{font-weight:500;color:var(--text)}
  .hub-sku a:hover{color:var(--primary);text-decoration:none}
  .hub-count{font-size:.85rem;color:var(--muted);font-variant-numeric:tabular-nums;flex-shrink:0}

  /* ── Related products ────────────────────────────────────────────────────── */
  .related-links{display:flex;flex-wrap:wrap;gap:.5rem;margin-top:.75rem}
  .rel-chip{font-size:.8rem;padding:.3rem .75rem;border:1px solid var(--border);border-radius:20px;color:var(--muted);transition:color .15s,border-color .15s,background .15s;line-height:1.4}
  .rel-chip:hover{color:var(--primary);border-color:var(--primary);background:var(--primary-l);text-decoration:none}
  .hub-back{font-size:.875rem;color:var(--primary);font-weight:600;display:inline-flex;align-items:center;gap:.25rem}

  /* ── Site footer ─────────────────────────────────────────────────────────── */
  .site-footer{border-top:1px solid var(--border);padding:1.5rem 1rem;background:var(--surface)}
  .footer-inner{max-width:960px;margin:0 auto;display:flex;flex-direction:column;gap:.5rem;font-size:.8rem;color:var(--muted)}
  .footer-inner a{color:var(--muted)}
  .footer-inner a:hover{color:var(--primary)}
  .footer-links{display:flex;flex-wrap:wrap;gap:.875rem;margin-bottom:.25rem}

  /* ── Content pages (methodology, about, privacy, terms, faq, contact) ────── */
  .meth-body h2{font-size:1.05rem;font-weight:700;color:var(--text);margin:1.75rem 0 .4rem}
  .meth-body p{font-size:.9375rem;color:var(--text);margin-bottom:.875rem;max-width:64ch}
  .meth-body ul{padding-left:1.25rem;margin-bottom:.875rem}
  .meth-body li{font-size:.9375rem;color:var(--text);margin-bottom:.3rem;max-width:64ch}
  .meth-body a{color:var(--primary)}
  .meth-body strong{font-weight:700}

  /* ── FAQ ─────────────────────────────────────────────────────────────────── */
  .faq-list{display:flex;flex-direction:column}
  .faq-q{font-weight:700;font-size:.95rem;color:var(--text);margin:1.25rem 0 .3rem}
  .faq-a{font-size:.9375rem;color:var(--text);max-width:64ch;padding-left:1rem;border-left:3px solid var(--border);line-height:1.65}

  /* ── TODO placeholder markers ────────────────────────────────────────────── */
  .todo{background:#fff3cd;color:#856404;border:1px solid #ffc107;border-radius:3px;padding:.1em .35em;font-family:monospace;font-size:.85em;font-weight:700;white-space:nowrap}
  [data-theme="dark"] .todo{background:#332d00;color:#ffc107;border-color:#664f00}

  /* ── Homepage hero ───────────────────────────────────────────────────────── */
  .home-hero{text-align:center;padding:3rem 1rem 2.5rem;max-width:680px;margin:0 auto}
  .home-hero h1{font-size:clamp(1.75rem,4vw,2.5rem);font-weight:800;letter-spacing:-.03em;color:var(--text);margin-bottom:.75rem}
  .home-sub{font-size:1.0625rem;color:var(--muted);max-width:520px;margin:0 auto 2rem;line-height:1.6}
  .search-form{display:flex;gap:.5rem;max-width:520px;margin:0 auto;flex-wrap:nowrap}
  .search-input{flex:1;min-width:0;padding:.75rem 1rem;border:2px solid var(--border);border-radius:8px;font-size:1rem;font-family:var(--font);background:var(--bg);color:var(--text);outline:none;transition:border-color .15s}
  .search-input:focus{border-color:var(--primary)}
  .search-input::placeholder{color:var(--muted)}
  .search-btn{padding:.75rem 1.25rem;background:var(--primary);color:#fff;border:none;border-radius:8px;font-size:1rem;font-weight:600;cursor:pointer;font-family:var(--font);white-space:nowrap;flex-shrink:0;transition:background .15s}
  .search-btn:hover{background:var(--primary-h)}
  .search-hints{margin-top:.875rem;font-size:.8rem;color:var(--muted)}
  .search-hints a{color:var(--primary);font-weight:500}

  /* ── Trust block ─────────────────────────────────────────────────────────── */
  .trust-block{background:var(--caveat-bg);border-left:4px solid var(--caveat-b);border-radius:0 8px 8px 0;padding:1.25rem 1.5rem;margin-bottom:2rem;font-size:.9rem;color:var(--caveat-t);line-height:1.6}
  .trust-block h2{font-size:.85rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--caveat-t);margin-bottom:.5rem}
  .trust-block-links{display:flex;flex-wrap:wrap;gap:.75rem;margin-top:.75rem;font-size:.8rem}
  .trust-block-links a{color:var(--caveat-t);font-weight:600;text-decoration:underline}
  .trust-block-links a:hover{opacity:.8}

  /* ── Stats bar ───────────────────────────────────────────────────────────── */
  .stats-bar{display:flex;flex-wrap:wrap;justify-content:center;gap:1.5rem 2.5rem;padding:1.25rem 1rem;border-top:1px solid var(--border);border-bottom:1px solid var(--border);margin-bottom:2rem;background:var(--surface)}
  .stat-item{text-align:center}
  .stat-num{font-size:1.4rem;font-weight:800;color:var(--text);letter-spacing:-.02em;display:block;font-variant-numeric:tabular-nums}
  .stat-label{font-size:.75rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}

  /* ── Featured products grid ──────────────────────────────────────────────── */
  .section-hd{font-size:1.05rem;font-weight:700;color:var(--text);margin-bottom:1rem}
  .featured-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:.875rem;margin-bottom:2rem}
  @media(max-width:640px){.featured-grid{grid-template-columns:repeat(2,1fr)}}
  @media(max-width:380px){.featured-grid{grid-template-columns:1fr}}
  .featured-card{border:1px solid var(--border);border-radius:10px;padding:1.125rem;background:var(--bg);transition:border-color .15s,box-shadow .15s;text-decoration:none;display:flex;flex-direction:column;gap:.3rem}
  .featured-card:hover{border-color:var(--primary);box-shadow:0 2px 12px rgba(0,166,126,.1);text-decoration:none}
  .featured-card-name{font-size:.9rem;font-weight:600;color:var(--text);line-height:1.3}
  .featured-card-count{font-size:.8rem;color:var(--muted)}
  .featured-card-count strong{color:var(--text);font-variant-numeric:tabular-nums}

  /* ── Browse page ─────────────────────────────────────────────────────────── */
  .browse-view{display:none}
  .browse-view.active{display:block}
  .browse-tabs{display:flex;gap:.5rem;margin-bottom:1.5rem;flex-wrap:wrap}
  .browse-tab{padding:.4rem 1rem;border:1px solid var(--border);border-radius:20px;font-size:.875rem;color:var(--muted);cursor:pointer;background:none;font-family:var(--font);transition:color .15s,border-color .15s,background .15s;font-weight:500}
  .browse-tab.active,.browse-tab:hover{color:var(--primary);border-color:var(--primary);background:var(--primary-l)}
  .az-group{margin-bottom:1.5rem}
  .az-letter{font-size:1rem;font-weight:800;color:var(--muted);letter-spacing:.04em;margin-bottom:.4rem;border-bottom:1px solid var(--border);padding-bottom:.25rem}
  .az-list{list-style:none}
  .az-item{display:flex;align-items:center;justify-content:space-between;padding:.45rem .5rem;border-radius:6px;gap:1rem;transition:background .1s}
  .az-item:hover{background:var(--surface)}
  .az-item a{font-size:.9rem;font-weight:500;color:var(--text)}
  .az-item a:hover{color:var(--primary);text-decoration:none}
  .az-item-meta{font-size:.78rem;color:var(--muted);white-space:nowrap;flex-shrink:0}
  .family-block{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:1.125rem;margin-bottom:.875rem}
  .family-block-hd{display:flex;align-items:center;justify-content:space-between;gap:1rem;margin-bottom:.75rem;flex-wrap:wrap}
  .family-block h3{font-size:.9375rem;font-weight:700;color:var(--text);margin:0}
  .family-block h3 a{color:var(--text)}
  .family-block h3 a:hover{color:var(--primary);text-decoration:none}
  .family-sku-row{display:flex;align-items:center;justify-content:space-between;padding:.35rem 0;border-bottom:1px solid var(--border);gap:1rem}
  .family-sku-row:last-child{border-bottom:none;padding-bottom:0}
  .family-sku-row a{font-size:.875rem;color:var(--muted)}
  .family-sku-row a:hover{color:var(--primary);text-decoration:none}
  .family-sku-count{font-size:.78rem;color:var(--muted);white-space:nowrap;font-variant-numeric:tabular-nums}

  /* ── Search page ─────────────────────────────────────────────────────────── */
  .search-wrap{max-width:720px;margin:0 auto}
  .pf-hint{font-size:.8rem;color:var(--muted);margin-top:1.5rem}

  /* ── 404 page ────────────────────────────────────────────────────────────── */
  .error-hero{text-align:center;padding:4rem 1rem 2rem}
  .error-hero h1{font-size:4rem;font-weight:800;color:var(--border);margin-bottom:.5rem;letter-spacing:-.04em}
  .error-hero p{color:var(--muted);margin-bottom:1.5rem}
  .error-links{display:flex;justify-content:center;gap:1rem;flex-wrap:wrap}
  .error-links a{padding:.6rem 1.25rem;border:1px solid var(--border);border-radius:8px;font-size:.9rem;color:var(--text);font-weight:500;transition:border-color .15s,color .15s}
  .error-links a:hover{border-color:var(--primary);color:var(--primary);text-decoration:none}
</style>`;

// ─── Inline JS ────────────────────────────────────────────────────────────────
const INLINE_JS = `
<script>
  // Theme toggle
  document.querySelector('.theme-toggle')?.addEventListener('click',function(){
    var h=document.documentElement,t=h.getAttribute('data-theme')==='dark'?'light':'dark';
    h.setAttribute('data-theme',t);localStorage.setItem('ss-theme',t);
  });
  // Banner dismiss
  document.getElementById('banner-btn')?.addEventListener('click',function(){
    localStorage.setItem('ss-banner-seen','1');
    document.documentElement.classList.add('banner-seen');
  });
</script>`;

// ─── SVG icons ───────────────────────────────────────────────────────────────
const ICON_MOON = `<svg class="icon-moon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`;
const ICON_SUN  = `<svg class="icon-sun" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>`;

// ─── Page shell ───────────────────────────────────────────────────────────────
function pageShell({ title, description, canonical, jsonLd, body }) {
  return `<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${esc(title)}</title>
  <meta name="description" content="${esc(description)}">
  <link rel="canonical" href="${esc(canonical)}">
  <meta property="og:type" content="website">
  <meta property="og:title" content="${esc(title)}">
  <meta property="og:description" content="${esc(description)}">
  <meta property="og:url" content="${esc(canonical)}">
  <meta property="og:site_name" content="SupplementFiles">
  <meta name="twitter:card" content="summary">
  <meta name="twitter:title" content="${esc(title)}">
  <meta name="twitter:description" content="${esc(description)}">
  <script type="application/ld+json">${jsonLd}<\/script>
  <script>
    /* Apply saved theme + banner-seen before first paint to prevent flash */
    (function(){
      var t=localStorage.getItem('ss-theme')||'light';
      document.documentElement.setAttribute('data-theme',t);
      if(localStorage.getItem('ss-banner-seen'))
        document.documentElement.classList.add('banner-seen');
    })();
  <\/script>
  ${GA4_ID ? `<!-- Google Analytics -->
  <script async src="https://www.googletagmanager.com/gtag/js?id=${GA4_ID}"><\/script>
  <script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','${GA4_ID}');<\/script>` : '<!-- GA4: set GA4_ID in scripts/generate-pages.js and regenerate -->'}
  ${INLINE_CSS}
</head>
<body>

  <div id="disclaimer-banner">
    <div class="banner-inner">
      <p>SupplementFiles presents data from FDA's voluntary adverse event reporting system. Reports do not prove that any product caused any effect. Always consult your healthcare provider.</p>
      <button id="banner-btn">I understand</button>
    </div>
  </div>

  <header class="site-header">
    <div class="inner">
      <a href="/" class="logo">SupplementFiles</a>
      <nav class="header-nav">
        <a href="/supplements/" class="header-link">Browse</a>
        <a href="/about/" class="header-link">About</a>
        <a href="/methodology/" class="header-link">Methodology</a>
        <button class="theme-toggle" aria-label="Toggle dark mode">${ICON_MOON}${ICON_SUN}</button>
      </nav>
    </div>
  </header>

  ${body}

  <footer class="site-footer">
    <div class="footer-inner">
      <div class="footer-links">
        <a href="/about/">About</a>
        <a href="/faq/">FAQ</a>
        <a href="/methodology/">Methodology</a>
        <a href="/supplements/">Browse</a>
        <a href="/search/">Search</a>
        <a href="/privacy/">Privacy</a>
        <a href="/terms/">Terms</a>
        <a href="/contact/">Contact</a>
      </div>
      <div class="footer-links" style="margin-top:.25rem">
        <a href="https://open.fda.gov/food/event/" target="_blank" rel="noopener noreferrer">openFDA CAERS source ↗</a>
      </div>
      <p>Data from FDA's CFSAN Adverse Event Reporting System (CAERS). Reports are voluntary and unverified — they do not establish causation. Last updated ${FORMATTED_DATE}.</p>
      <p>SupplementFiles is not medical advice. Consult your healthcare provider before making any health decisions.</p>
    </div>
  </footer>

  ${INLINE_JS}
</body>
</html>`;
}

// ─── Reaction bars ────────────────────────────────────────────────────────────
function reactionBarsHTML(reactions) {
  const filtered = reactions.top_reactions
    .filter(r => !REACTIONS_DENYLIST.has(r.term))
    .slice(0, 10);
  if (!filtered.length) return '<p class="section-note">No reaction data available after filtering.</p>';
  const maxCount = filtered[0].count;
  return `<div class="bars-list">
  ${filtered.map(r => {
    const pct = Math.round((r.count / maxCount) * 100);
    return `<div class="bar-row">
    <div class="bar-label" title="${esc(r.term)}">${esc(meddraTerm(r.term))}</div>
    <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
    <div class="bar-count">${fmt(r.count)}</div>
  </div>`;
  }).join('\n  ')}
</div>`;
}

// ─── Outcomes table ───────────────────────────────────────────────────────────
function outcomesTableHTML(outcomes) {
  const sorted = Object.entries(outcomes).sort((a, b) => b[1].count - a[1].count);
  return `<table class="outcomes-table">
  <thead><tr><th>Outcome</th><th style="text-align:right">Reports</th></tr></thead>
  <tbody>
  ${sorted.map(([name, { count }]) => `<tr>
    <td>${esc(name)}</td>
    <td class="count-cell">${fmt(count)}</td>
  </tr>`).join('\n  ')}
  </tbody>
</table>`;
}

// ─── Demographics ─────────────────────────────────────────────────────────────
function demographicsHTML(demographics) {
  const { gender, age_bands } = demographics;

  const AGE_KEYS   = ['under_18','18_34','35_49','50_64','65_79','80_plus','unknown'];
  const AGE_LABELS = { under_18:'Under 18', '18_34':'18–34', '35_49':'35–49',
    '50_64':'50–64', '65_79':'65–79', '80_plus':'80+', unknown:'Unknown' };

  const agePairs  = AGE_KEYS.map(k => [AGE_LABELS[k], age_bands[k] || 0]);
  const maxAge    = Math.max(...agePairs.map(([, v]) => v), 1);
  const genderPairs = Object.entries(gender);
  const maxGender = Math.max(...genderPairs.map(([, v]) => v), 1);

  function barsFor(pairs, maxVal) {
    return pairs.map(([label, count]) => {
      const pct = Math.round((count / maxVal) * 100);
      return `<div class="bar-row" style="grid-template-columns:minmax(0,7rem) 1fr 4rem">
      <div class="bar-label">${esc(label)}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
      <div class="bar-count">${fmt(count)}</div>
    </div>`;
    }).join('\n    ');
  }

  const ageNote = age_bands.n_with_age
    ? `<p class="section-note" style="margin-top:.5rem">${fmt(age_bands.n_with_age)} reports had age data; ${fmt(age_bands.unknown || 0)} unknown.</p>`
    : '';

  return `<div class="demo-grid">
  <div class="demo-block">
    <h3>Age</h3>
    <div class="bars-list">
    ${barsFor(agePairs, maxAge)}
    </div>
    ${ageNote}
  </div>
  <div class="demo-block">
    <h3>Gender</h3>
    <div class="bars-list">
    ${barsFor(genderPairs, maxGender)}
    </div>
  </div>
</div>`;
}

// ─── Year histogram ───────────────────────────────────────────────────────────
function yearHistHTML(yearlyTrend) {
  // Show all years from first nonzero to last nonzero
  const entries = Object.entries(yearlyTrend)
    .map(([k, v]) => [parseInt(k), v])
    .sort((a, b) => a[0] - b[0]);

  const nonzeroYears = entries.filter(([, v]) => v > 0).map(([k]) => k);
  if (!nonzeroYears.length) return '<p class="section-note">No yearly data available.</p>';

  const firstYear = Math.min(...nonzeroYears);
  const lastYear  = Math.max(...nonzeroYears);
  const filtered  = entries.filter(([k]) => k >= firstYear && k <= lastYear);

  const maxVal = Math.max(...filtered.map(([, v]) => v), 1);
  const MAX_PX = 90;

  const barCols = filtered.map(([year, count]) => {
    const h    = count > 0 ? Math.max(Math.round((count / maxVal) * MAX_PX), 3) : 0;
    const tip  = `${year}: ${fmt(count)} report${count !== 1 ? 's' : ''}`;
    return `<div class="hist-col">
      <div class="hist-bar" style="height:${h}px" title="${esc(tip)}"></div>
    </div>`;
  }).join('\n    ');

  const labelCols = filtered.map(([year]) =>
    `<div class="hist-year">'${String(year).slice(2)}</div>`
  ).join('\n    ');

  return `<div class="hist-outer">
  <div class="hist-bars">
    ${barCols}
  </div>
  <div class="hist-labels">
    ${labelCols}
  </div>
</div>
<p class="section-note" style="margin-top:.5rem">Hover bars for exact counts.</p>`;
}

// ─── Product page ─────────────────────────────────────────────────────────────
function renderProductPage(product, allProducts, slugMap) {
  const name        = product.canonical_display_name;
  const productSlug = slugMap.get(name);
  const category    = getCategory(product);
  const range       = dateRange(product.yearly_trend);
  const total       = product.total_reports;
  const isCluster   = ['event_cluster', 'organic_recent_emerging'].includes(product.data_character);
  const canonical   = `${BASE_URL}/supplements/${productSlug}/`;

  // Related products: same brand family, different SKU, top 3 by count
  const related = allProducts
    .filter(p => p.canonical_display_name !== name
              && p.brand_family && p.brand_family === product.brand_family
              && p.page_eligible !== false)
    .sort((a, b) => b.total_reports - a.total_reports)
    .slice(0, 3);

  const familySlugVal = product.brand_family ? slug(product.brand_family) : null;

  const jsonLd = JSON.stringify({
    '@context': 'https://schema.org',
    '@type': 'Dataset',
    name: `${name} — FDA Adverse Event Reports`,
    description: `${total} adverse event reports for ${name} submitted to FDA's CAERS database. Includes reactions, outcomes, and demographics.`,
    url: canonical,
    creator: { '@type': 'Organization', name: 'SupplementFiles' },
    publisher: { '@type': 'Organization', name: 'SupplementFiles' },
    dateModified: CURRENT_DATE,
    distribution: [{
      '@type': 'DataDownload',
      contentUrl: 'https://open.fda.gov/food/event/',
      encodingFormat: 'application/json',
      name: 'openFDA CAERS'
    }],
    variableMeasured: 'Adverse Event Reports',
    measurementTechnique: 'FDA Voluntary Adverse Event Reporting'
  });

  const breadcrumb = product.brand_family
    ? `<nav class="breadcrumb" aria-label="Breadcrumb">
      <a href="/supplements/">Supplements</a> ›
      <a href="/supplements/${familySlugVal}/">${esc(product.brand_family)}</a> ›
      ${esc(name)}
    </nav>`
    : `<nav class="breadcrumb" aria-label="Breadcrumb">
      <a href="/supplements/">Supplements</a> › ${esc(name)}
    </nav>`;

  const clusterBlock = isCluster && product.cluster_context
    ? `<div class="cluster-block">
      <strong>Context about this data:</strong> ${esc(product.cluster_context)}
    </div>` : '';

  const productNote = PRODUCT_CONTEXT_NOTES[name]
    ? PRODUCT_CONTEXT_NOTES[name](product)
    : '';

  const relatedSection = related.length || product.brand_family
    ? `<div class="card" data-pagefind-ignore>
      ${product.brand_family
        ? `<p style="margin-bottom:${related.length ? '.75rem' : '0'}">
            <a class="hub-back" href="/supplements/${familySlugVal}/">
              ← View all ${esc(product.brand_family)} products in FDA data
            </a>
          </p>`
        : ''}
      ${related.length
        ? `<h2 style="font-size:1rem;margin-bottom:.25rem">Related Products</h2>
           <div class="related-links">
             ${related.map(p => `<a class="rel-chip" href="/supplements/${slugMap.get(p.canonical_display_name)}/">${esc(p.canonical_display_name)} (${fmt(p.total_reports)})</a>`).join('\n             ')}
           </div>`
        : ''}
    </div>` : '';

  const body = `
  <main data-pagefind-body data-pagefind-filter="category:${esc(category)}">
    <div data-pagefind-ignore>${breadcrumb}</div>

    <div class="product-hero">
      <span class="cat-pill">${esc(category)}</span>
      <h1 data-pagefind-meta="title">${esc(name)}</h1>
      <p class="product-meta">
        <span class="big-count">${fmt(total)}</span> adverse event reports submitted to the FDA ·
        ${range} · Data current as of ${FORMATTED_DATE}
      </p>
    </div>

    <div class="caveat-band" data-pagefind-ignore>
      These are reports submitted to the FDA. A report does not mean the product caused the effect. Counts reflect reporting activity, not how common an effect is.
    </div>

    <div class="card" id="reactions">
      <h2>Most Reported Reactions</h2>
      <p class="section-note">Top 10 reactions from ${fmt(total)} reports. One report may include multiple reactions — reaction totals may exceed the report count.</p>
      ${reactionBarsHTML(product.reactions)}
    </div>

    <div class="card" id="outcomes">
      <h2>Reported Outcomes</h2>
      <p class="section-note">Outcome categories as recorded in FDA reports. One report may include multiple outcomes.</p>
      ${outcomesTableHTML(product.outcomes)}
    </div>

    <div class="card" id="demographics">
      <h2>Who Reported</h2>
      <p class="section-note">Reporter demographics where available. Many reports do not include age or gender data.</p>
      ${demographicsHTML(product.demographics)}
    </div>

    <div class="card" id="trend">
      <h2>Reports by Year</h2>
      <p class="section-note">Annual report counts from ${range}. Spike years may reflect recalls, media coverage, or litigation rather than changes in the product.</p>
      ${yearHistHTML(product.yearly_trend)}
    </div>

    ${clusterBlock}

    ${productNote}

    ${relatedSection}

    <div class="card" id="source" data-pagefind-ignore>
      <h2>Data Source</h2>
      <p class="section-note">This page presents data from the FDA's CFSAN Adverse Event Reporting System (CAERS) via the openFDA API. Reports are voluntary and unverified. The FDA has not concluded that this product caused any reported event.</p>
      <a href="https://open.fda.gov/food/event/" target="_blank" rel="noopener noreferrer" style="font-size:.875rem;font-weight:600">View openFDA CAERS data ↗</a>
      &nbsp;·&nbsp;
      <a href="/methodology/" style="font-size:.875rem">About our methodology</a>
    </div>
  </main>`;

  return pageShell({
    title: `${name} — FDA Adverse Event Reports | SupplementFiles`,
    description: `${total} adverse event reports for ${name} submitted to the FDA's CAERS database (${range}). See reported reactions, outcomes, and who reported.`,
    canonical,
    jsonLd,
    body
  });
}

// ─── Brand hub page ───────────────────────────────────────────────────────────
function renderHubPage(familyName, skus, slugMap) {
  const hubSlug  = slug(familyName);
  const canonical = `${BASE_URL}/supplements/${hubSlug}/`;
  const sortedSkus = [...skus].sort((a, b) => b.total_reports - a.total_reports);

  const jsonLd = JSON.stringify({
    '@context': 'https://schema.org',
    '@type': 'CollectionPage',
    name: `${familyName} Products — FDA Adverse Event Reports`,
    description: `FDA adverse event reports for ${familyName} product variants, individually tracked from the CAERS database. Counts are per-SKU — never combined.`,
    url: canonical,
    publisher: { '@type': 'Organization', name: 'SupplementFiles' },
    dateModified: CURRENT_DATE
  });

  const skuListHTML = sortedSkus.map(p => {
    const pSlug = slugMap.get(p.canonical_display_name);
    const range = dateRange(p.yearly_trend);
    return `<li class="hub-sku">
      <a href="/supplements/${pSlug}/">${esc(p.canonical_display_name)}</a>
      <span class="hub-count">${fmt(p.total_reports)} reports · ${range}</span>
    </li>`;
  }).join('\n    ');

  const body = `
  <main>
    <nav class="breadcrumb" aria-label="Breadcrumb">
      <a href="/supplements/">Supplements</a> › ${esc(familyName)}
    </nav>

    <div class="product-hero">
      <span class="cat-pill">Brand Family</span>
      <h1>${esc(familyName)} Products in FDA Data</h1>
      <p class="product-meta">
        Individual FDA adverse event report counts for ${esc(familyName)} product variants.
        Counts are per-product — they are <strong>never combined</strong> across SKUs.
      </p>
    </div>

    <div class="caveat-band">
      These are reports submitted to the FDA. A report does not mean any product caused the effect. Each SKU's count is tracked individually and is never summed across variants.
    </div>

    <div class="card">
      <h2>${esc(familyName)} Product Variants</h2>
      <p class="section-note">Each entry is a distinct product as named in FDA reports. Click any product to see its full adverse event breakdown.</p>
      <ul class="hub-list">
    ${skuListHTML}
      </ul>
    </div>

    <div class="card" id="source">
      <h2>Data Source</h2>
      <p class="section-note">Data from FDA's CFSAN Adverse Event Reporting System (CAERS). Reports are voluntary submissions — they do not establish that any product caused any event.</p>
      <a href="https://open.fda.gov/food/event/" target="_blank" rel="noopener noreferrer" style="font-size:.875rem;font-weight:600">View openFDA CAERS source ↗</a>
      &nbsp;·&nbsp;
      <a href="/methodology/" style="font-size:.875rem">About our methodology</a>
    </div>
  </main>`;

  return {
    html: pageShell({
      title: `${familyName} Products — FDA Adverse Event Reports | SupplementFiles`,
      description: `FDA adverse event reports for ${familyName} product variants, individually tracked. ${sortedSkus.length} SKUs from the CAERS database.`,
      canonical,
      jsonLd,
      body
    }),
    hubSlug
  };
}

// ─── Methodology page (full content from methodology-page.md) ─────────────────
function renderMethodologyPage() {
  const canonical = `${BASE_URL}/methodology/`;
  const jsonLd = JSON.stringify({
    '@context': 'https://schema.org',
    '@type': 'WebPage',
    name: 'About the Data &amp; How to Read It — SupplementFiles',
    description: 'What the FDA CAERS data is, where it comes from, and what it does and does not mean. Read this before drawing conclusions from any product page.',
    url: canonical,
    publisher: { '@type': 'Organization', name: 'SupplementFiles' },
    dateModified: CURRENT_DATE
  });

  const body = `
  <main>
    <div style="max-width:960px;margin:0 auto;padding:2rem 1rem 4rem">
      <div class="product-hero" style="margin-bottom:1.5rem">
        <h1 style="font-size:clamp(1.5rem,3vw,2rem)">About the Data &amp; How to Read It</h1>
        <p class="product-meta">SupplementFiles makes a public government dataset — the FDA's records of adverse events reported for dietary supplements — searchable and readable. This page explains exactly what that data is, where it comes from, and what it does and does not mean. Please read it before drawing conclusions from any product page.</p>
      </div>

      <div class="card meth-body">
        <h2>Where this data comes from</h2>
        <p>Every figure on this site comes from the <strong>FDA Adverse Event Reporting System for foods and supplements (CAERS)</strong>, published openly by the FDA through its <a href="https://open.fda.gov" target="_blank" rel="noopener noreferrer">openFDA</a> program. CAERS collects reports of health problems that people, health professionals, and manufacturers have associated with a dietary supplement (or food or cosmetic). We download the full public dataset, isolate the dietary-supplement records, and organize them by product.</p>
        <p>The data covers reports from <strong>2004 to the present</strong> and is refreshed on a <strong>quarterly</strong> basis, in step with the FDA's own update schedule. The "data current as of" date on each page tells you the last time we refreshed.</p>

        <h2>The single most important thing to understand</h2>
        <p><strong>A report is not proof that a product caused harm.</strong> When someone files an adverse event report, they are saying that a health problem occurred <em>while</em> a product was being used — not that the product was tested and found responsible. The FDA does not verify most reports, and it explicitly cautions that when a report names more than one product or more than one symptom, there is no way to know which product, if any, was responsible.</p>
        <p>So the counts on this site tell you <strong>what has been reported</strong>, not how often a product actually causes a problem, and not whether it causes that problem at all. A report can reflect a coincidence, an unrelated illness, a pre-existing condition, or use of several products at once.</p>

        <h2>Why we show counts, not rates</h2>
        <p>You will notice we never display a figure like "X% of users were hospitalized" or a "death rate." That would be misleading, for a simple reason: <strong>the number of reports reflects reporting activity, not real-world frequency.</strong> A product's report count rises when it draws regulatory attention, becomes the subject of a lawsuit, is filed in bulk by a single source, or is simply used by millions of people. It does not tell you your personal odds of anything.</p>
        <p>Because of this, dividing serious outcomes by total reports produces a number that looks like a risk but isn't one. We show absolute counts and let you see the data for what it is.</p>

        <h2>How to read a product page</h2>
        <ul>
          <li><strong>Total reports</strong> — how many adverse event reports name this exact product.</li>
          <li><strong>Reactions</strong> — the health effects people reported (for example, nausea, dizziness, or a specific medical event), shown as counts. This list describes symptoms and effects; outcomes like death are shown separately, below.</li>
          <li><strong>Outcomes</strong> — how serious the reported events were: whether they involved a hospitalization, an emergency room visit, a life-threatening event, or a death. These are counts of how reports were classified, not rates.</li>
          <li><strong>Who reported</strong> — the age ranges and sexes recorded in the reports, where available.</li>
          <li><strong>Reports over time</strong> — when the reports were filed. This often matters: a cluster of reports in a single year usually reflects a recall, a wave of litigation, or a batch of reports filed together, rather than a steady ongoing pattern. Where a product's reports concentrate in a particular period, we note it.</li>
        </ul>

        <h2>How we handle product names</h2>
        <p>Reports are filed with free-text product names, which arrive inconsistently spelled and capitalized. We clean up these formatting differences so that the same product isn't split across "VITAMIN D" and "Vitamin D." We do <strong>not</strong> combine genuinely different products — "Centrum Silver Women's 50+" and "Centrum Silver Ultra Women's" are kept separate, because they are separate products and their reports belong to them individually. Brand pages that group a product family list each product's count on its own and never blend them into a single figure.</p>

        <h2>What we include and leave out</h2>
        <p>We publish a page for a product only when it has enough reports to be meaningful. We also set aside the small number of products whose reports clearly come from a single concentrated filing event rather than from independent reporting, because presenting those as a typical safety profile would mislead. Products below our reporting threshold appear within their brand's listing but do not get a standalone page.</p>

        <h2>This is not medical advice</h2>
        <p>SupplementFiles is an information resource, not a medical provider. Nothing here is a diagnosis, a recommendation, or a substitute for professional guidance. If you have a health concern about a supplement you take, talk to a doctor or pharmacist before making any change.</p>

        <h2>Report an adverse event yourself</h2>
        <p>If you have experienced a problem you believe is connected to a dietary supplement, you can report it directly to the FDA through the <a href="https://www.safetyreporting.hhs.gov" target="_blank" rel="noopener noreferrer">Safety Reporting Portal</a> or MedWatch. Reporting is what makes data like this exist, and it helps the FDA identify problems.</p>

        <h2>Corrections and contact</h2>
        <p>We want this data represented accurately. If you are a manufacturer or a member of the public who believes something here is wrong or misleading, please reach out — <a href="/contact/">contact us</a> — and we will review it promptly.</p>

        <p style="margin-top:1.5rem;font-size:.8rem;color:var(--muted)"><em>Source: U.S. Food &amp; Drug Administration, CAERS, via openFDA. SupplementFiles is an independent project and is not affiliated with, endorsed by, or operated by the FDA or any government agency.</em></p>
      </div>
    </div>
  </main>`;

  return pageShell({
    title: 'About the Data — SupplementFiles',
    description: 'What the FDA CAERS adverse event data is, where it comes from, and what it does and does not mean. Read before drawing conclusions from any product page.',
    canonical, jsonLd, body
  });
}

// ─── About page ────────────────────────────────────────────────────────────────
function renderAboutPage() {
  const canonical = `${BASE_URL}/about/`;
  const jsonLd = JSON.stringify({
    '@context': 'https://schema.org', '@type': 'AboutPage',
    name: 'About SupplementFiles',
    url: canonical,
    publisher: { '@type': 'Organization', name: 'SupplementFiles' }
  });

  const body = `
  <main>
    <div style="max-width:960px;margin:0 auto;padding:2rem 1rem 4rem">
      <div class="product-hero" style="margin-bottom:1.5rem">
        <h1 style="font-size:clamp(1.5rem,3vw,2rem)">About SupplementFiles</h1>
      </div>
      <div class="card meth-body">
        <p>SupplementFiles is a free, independent resource that takes a public government dataset — the U.S. Food &amp; Drug Administration's records of adverse events reported for dietary supplements — and makes it searchable and readable for ordinary people.</p>
        <p>That data has always been public, but it lives in a database built for researchers and developers, not for someone who simply wants to know what's been reported about a supplement they take. We organize it by product, translate the medical terminology into plain language, and present it honestly — so you can see what people have reported to the FDA and decide what it means for you, in conversation with a healthcare professional.</p>

        <h2>What we do — and what we don't</h2>
        <p>We <strong>present</strong> the data. We don't rank products, we don't recommend or warn against them, and we don't sell anything based on what the data shows. We're not a substitute for medical advice, and we don't claim any product is safe or dangerous — we show you what has been reported and let the record speak.</p>

        <h2>The standards we hold ourselves to</h2>
        <p>Because trust in health information has to be earned, here is exactly how we handle the data:</p>
        <ul>
          <li><strong>Counts, not rates.</strong> We show the number of reports, never a "death rate" or "risk percentage." Report counts reflect how often something was <em>reported</em> — which is shaped by news coverage, lawsuits, and how many people use a product — not how often it actually happens.</li>
          <li><strong>Reports are not proof.</strong> A report means a health problem was reported alongside a product, not that the product caused it. We frame every page accordingly.</li>
          <li><strong>We present the record faithfully.</strong> We report what each FDA record actually says about each specific product, and we don't blend different products together to make a number look bigger or smaller.</li>
          <li><strong>We correct mistakes.</strong> If we've gotten something wrong, we want to know and we'll fix it — see <a href="/contact/">Contact</a>.</li>
        </ul>

        <h2>Who we are</h2>
        <p>SupplementFiles is built and maintained by a small independent team that believes public safety data should actually be usable by the public. We are <strong>not affiliated with, endorsed by, or operated by the FDA or any government agency.</strong> Our source data comes from the FDA's CAERS database via the openFDA program; how we organize and explain it is our own work.</p>
        <p>For how the data is collected, updated, and interpreted, see our <a href="/methodology/">Methodology</a> page.</p>
      </div>
    </div>
  </main>`;

  return pageShell({
    title: 'About — SupplementFiles',
    description: 'SupplementFiles makes FDA dietary supplement adverse event reports searchable and readable for ordinary people. Independent, non-commercial, data-forward.',
    canonical, jsonLd, body
  });
}

// ─── FAQ page ──────────────────────────────────────────────────────────────────
function renderFaqPage() {
  const canonical = `${BASE_URL}/faq/`;

  const QA = [
    { q: 'What is this site?', a: 'SupplementFiles makes the FDA\'s adverse-event reports for dietary supplements searchable and readable. Search any covered product and see what health problems people have reported to the FDA, with the medical terms translated into plain language.' },
    { q: 'Does a report mean the supplement caused harm?', a: 'No. A report means someone experienced a health problem while using a product and reported it — not that the product was tested and found responsible. The FDA does not verify most reports, and many reports involve several products at once, so there\'s often no way to know which one, if any, was involved.' },
    { q: 'Why don\'t you show percentages or a "risk rate"?', a: 'Because they would mislead. The number of reports reflects reporting activity — driven by attention, lawsuits, and how many people use a product — not your personal odds of anything. Dividing serious outcomes by total reports produces a figure that looks like a risk but isn\'t one. We show plain counts instead.' },
    { q: 'Why are all of a product\'s reports from one year?', a: 'For some products, reports cluster in a single period because of a recall, a wave of lawsuits, or a batch of reports filed together. Where that\'s the case, we note it on the page. A cluster is a sign to read the context, not a measure of ongoing risk.' },
    { q: 'Why does a basic vitamin or fiber supplement show serious outcomes, even deaths?', a: 'Reports often come from people who are elderly or already ill, and a serious event reported alongside a product doesn\'t mean the product caused it. This is exactly why we show counts with context rather than rates.' },
    { q: 'My company\'s product is listed. How do I respond or request a correction?', a: 'We present public FDA data as filed, without asserting causation. If you believe something is inaccurate or presented misleadingly, contact us (see Contact) and we\'ll review it promptly.' },
    { q: 'Is this medical advice?', a: 'No. SupplementFiles is an information resource, not a medical provider. Talk to a doctor or pharmacist before making any decision about a supplement.' },
    { q: 'How current is the data?', a: 'We refresh from the FDA\'s quarterly data releases. Each page shows when it was last updated.' },
    { q: 'How do I report a problem I had with a supplement?', a: 'Report it directly to the FDA through the Safety Reporting Portal (safetyreporting.hhs.gov) or MedWatch. Reporting is what makes data like this exist.' },
    { q: 'Where does the data come from?', a: 'The FDA\'s CAERS database, published through the openFDA program. See our Methodology page for the full detail.' },
  ];

  const jsonLd = JSON.stringify({
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: QA.map(({ q, a }) => ({
      '@type': 'Question',
      name: q,
      acceptedAnswer: { '@type': 'Answer', text: a }
    }))
  });

  const faqHTML = QA.map(({ q, a }) => `
        <dt class="faq-q">${esc(q)}</dt>
        <dd class="faq-a">${esc(a)}</dd>`).join('');

  const body = `
  <main>
    <div style="max-width:960px;margin:0 auto;padding:2rem 1rem 4rem">
      <div class="product-hero" style="margin-bottom:1.5rem">
        <h1 style="font-size:clamp(1.5rem,3vw,2rem)">Frequently Asked Questions</h1>
      </div>
      <div class="card meth-body">
        <dl class="faq-list">${faqHTML}
        </dl>
        <p style="margin-top:2rem;font-size:.875rem;color:var(--muted)">More questions? See our <a href="/methodology/">full methodology</a> or <a href="/contact/">contact us</a>.</p>
      </div>
    </div>
  </main>`;

  return pageShell({
    title: 'FAQ — SupplementFiles',
    description: 'Answers to common questions about SupplementFiles: what the FDA data means, why we show counts not rates, how to read the reports, and more.',
    canonical, jsonLd, body
  });
}

// ─── Privacy Policy page ───────────────────────────────────────────────────────
function renderPrivacyPage() {
  const canonical = `${BASE_URL}/privacy/`;
  const jsonLd = JSON.stringify({ '@context': 'https://schema.org', '@type': 'WebPage', name: 'Privacy Policy — SupplementFiles', url: canonical });
  const TODO = (text) => `<mark class="todo">${esc(text)}</mark>`;

  const body = `
  <main>
    <div style="max-width:960px;margin:0 auto;padding:2rem 1rem 4rem">
      <div class="product-hero" style="margin-bottom:1.5rem">
        <h1 style="font-size:clamp(1.5rem,3vw,2rem)">Privacy Policy</h1>
        <p class="product-meta">Effective ${TODO('[EFFECTIVE DATE]')}</p>
      </div>
      <div class="card meth-body">
        <p>This Privacy Policy explains how SupplementFiles ("we," "us") handles information when you visit supplementfiles.com.</p>

        <h2>Information we collect</h2>
        <p>We do not ask you to create an account or submit personal information to browse the site. We collect limited information automatically:</p>
        <ul>
          <li><strong>Usage and device data</strong> through analytics — pages visited, time on site, approximate (city-level) location, and device and browser type.</li>
          <li><strong>Server and security logs</strong> kept by our hosting provider (Cloudflare), which may include IP addresses, for security and reliability.</li>
          <li><strong>Cookies and similar technologies</strong> used by our analytics provider, described below.</li>
        </ul>

        <h2>Analytics</h2>
        <p>We use <strong>Google Analytics 4</strong> to understand how visitors use the site so we can improve it. Google Analytics uses cookies and similar identifiers to collect usage data, which is processed in aggregate. You can opt out using the Google Analytics Opt-out Browser Add-on.</p>

        <h2>Your choices and consent</h2>
        <p>If you are in the European Economic Area, the United Kingdom, or Switzerland, we request your consent for non-essential (analytics) cookies through a consent banner when you arrive, and you can change your choices at any time.</p>

        <h2>Your rights</h2>
        <p>Depending on where you live, you may have rights to access, correct, or delete your personal information, and to object to or restrict certain processing (under the EU/UK GDPR), or to know about and delete personal information (under the California CCPA/CPRA). We do not sell your personal information. To exercise any right, contact us at ${TODO('[CONTACT EMAIL]')}.</p>

        <h2>Children's privacy</h2>
        <p>This site is not directed to children under 13, and we do not knowingly collect personal information from them.</p>

        <h2>Changes</h2>
        <p>We may update this policy; the effective date above reflects the latest version.</p>

        <h2>Contact</h2>
        <p>Questions about this policy: ${TODO('[CONTACT EMAIL]')}.</p>
      </div>
    </div>
  </main>`;

  return pageShell({ title: 'Privacy Policy — SupplementFiles', description: 'How SupplementFiles collects, uses, and protects your information.', canonical, jsonLd, body });
}

// ─── Terms of Use page ─────────────────────────────────────────────────────────
function renderTermsPage() {
  const canonical = `${BASE_URL}/terms/`;
  const jsonLd = JSON.stringify({ '@context': 'https://schema.org', '@type': 'WebPage', name: 'Terms of Use — SupplementFiles', url: canonical });
  const TODO = (text) => `<mark class="todo">${esc(text)}</mark>`;

  const body = `
  <main>
    <div style="max-width:960px;margin:0 auto;padding:2rem 1rem 4rem">
      <div class="product-hero" style="margin-bottom:1.5rem">
        <h1 style="font-size:clamp(1.5rem,3vw,2rem)">Terms of Use &amp; Disclaimer</h1>
        <p class="product-meta">Effective ${TODO('[EFFECTIVE DATE]')}</p>
      </div>
      <div class="card meth-body">
        <p>By using supplementfiles.com, you agree to these terms. If you do not agree, please do not use the site.</p>

        <h2>Informational purpose only — not medical advice</h2>
        <p>SupplementFiles provides information drawn from public FDA data for general informational purposes only. <strong>It is not medical advice and is not a substitute for professional diagnosis or treatment.</strong> Always consult a qualified healthcare professional before making any decision about a supplement, medication, or your health. No doctor–patient or professional relationship is created by using this site.</p>

        <h2>About the data and causation</h2>
        <p>The information on this site comes from adverse-event reports submitted to the U.S. FDA (the CAERS database, via openFDA). These reports are <strong>submitted by the public, health professionals, and manufacturers; they are largely unverified; and they do not establish that any product caused any effect.</strong> We present this data as-is and <strong>do not assert that any product is unsafe, defective, or responsible for any reported outcome</strong>, nor do we endorse, recommend, or disparage any product or brand. Report counts reflect reporting activity, not real-world frequency or risk.</p>

        <h2>No warranty</h2>
        <p>The site and its contents are provided "as is" and "as available," without warranties of any kind, express or implied, including accuracy, completeness, or fitness for a particular purpose. Data may contain errors, omissions, or inconsistencies originating in the source records.</p>

        <h2>Limitation of liability</h2>
        <p>To the fullest extent permitted by law, SupplementFiles and its operators will not be liable for any direct, indirect, incidental, consequential, or other damages arising from your use of, or reliance on, the site or its content.</p>

        <h2>Corrections</h2>
        <p>If you believe information here is inaccurate or misleading, <a href="/contact/">contact us</a> and we will review it.</p>

        <h2>Intellectual property</h2>
        <p>The underlying FDA data is a public-domain work of the U.S. government. The organization, presentation, written explanations, and design of this site are the property of SupplementFiles and may not be copied wholesale without permission.</p>

        <h2>Third-party links</h2>
        <p>The site may contain links to third-party sites, which we do not control and are not responsible for.</p>

        <h2>Governing law</h2>
        <p>These terms are governed by the laws of ${TODO('[STATE/COUNTRY]')}, without regard to conflict-of-laws principles.</p>

        <h2>Changes</h2>
        <p>We may update these terms; the effective date above reflects the latest version.</p>

        <h2>Contact</h2>
        <p>Questions about these terms: ${TODO('[CONTACT EMAIL]')}.</p>
      </div>
    </div>
  </main>`;

  return pageShell({ title: 'Terms of Use — SupplementFiles', description: 'Terms of use and disclaimer for SupplementFiles. FDA data is presented for informational purposes only and does not constitute medical advice.', canonical, jsonLd, body });
}

// ─── Contact page ──────────────────────────────────────────────────────────────
function renderContactPage() {
  const canonical = `${BASE_URL}/contact/`;
  const jsonLd = JSON.stringify({ '@context': 'https://schema.org', '@type': 'ContactPage', name: 'Contact — SupplementFiles', url: canonical });
  const TODO = (text) => `<mark class="todo">${esc(text)}</mark>`;

  const body = `
  <main>
    <div style="max-width:960px;margin:0 auto;padding:2rem 1rem 4rem">
      <div class="product-hero" style="margin-bottom:1.5rem">
        <h1 style="font-size:clamp(1.5rem,3vw,2rem)">Contact</h1>
      </div>
      <div class="card meth-body">
        <p>SupplementFiles is an independent resource, and we want the information here to be accurate and fair.</p>

        <h2>General questions</h2>
        <p>${TODO('[CONTACT EMAIL]')}</p>

        <h2>Corrections and right-of-reply</h2>
        <p>If you are a manufacturer or a member of the public and believe something on the site is inaccurate or presented misleadingly, email us at ${TODO('[CONTACT EMAIL]')} with the product and the specific concern, and we'll review it promptly.</p>

        <h2>Medical emergencies and adverse event reporting</h2>
        <p><strong>We cannot help with medical emergencies or personal health questions.</strong> If you are experiencing a medical problem, contact a healthcare professional.</p>
        <p>To report an adverse event you experienced with a supplement, file it directly with the FDA through the <a href="https://www.safetyreporting.hhs.gov" target="_blank" rel="noopener noreferrer">Safety Reporting Portal</a> or MedWatch — that is what allows data like this to exist.</p>

        <p style="margin-top:1.5rem;font-size:.875rem;color:var(--muted)">We read every message but cannot promise individual responses to all of them.</p>
      </div>
    </div>
  </main>`;

  return pageShell({ title: 'Contact — SupplementFiles', description: 'Contact SupplementFiles with questions, corrections, or right-of-reply requests about supplement adverse event data.', canonical, jsonLd, body });
}

// ─── Homepage ─────────────────────────────────────────────────────────────────
function renderHomepage(allProducts, slugMap) {
  const canonical = `${BASE_URL}/`;

  // Featured products: handpicked for signal diversity and search interest
  const FEATURED = [
    "Centrum Silver Women's 50+",
    '5 Hour Energy',
    'Kratom',
    'Hydroxycut Regular',
    'Super Beta Prostate',
    'Preservision AREDS 2',
  ];
  const featuredProducts = FEATURED
    .map(name => allProducts.find(p => p.canonical_display_name === name))
    .filter(Boolean);

  const featuredCards = featuredProducts.map(p => {
    const pSlug = slugMap.get(p.canonical_display_name);
    const cat   = getCategory(p);
    return `<a class="featured-card" href="/supplements/${pSlug}/">
      <span class="cat-pill">${esc(cat)}</span>
      <div class="featured-card-name">${esc(p.canonical_display_name)}</div>
      <div class="featured-card-count"><strong>${fmt(p.total_reports)}</strong> reports</div>
    </a>`;
  }).join('\n    ');

  const totalReports = allProducts.reduce((s, p) => s + p.total_reports, 0);

  const jsonLd = JSON.stringify([
    {
      '@context': 'https://schema.org',
      '@type': 'WebSite',
      name: 'SupplementFiles',
      url: BASE_URL,
      description: 'FDA dietary supplement adverse event reports, made searchable and legible.',
      potentialAction: {
        '@type': 'SearchAction',
        target: { '@type': 'EntryPoint', urlTemplate: `${BASE_URL}/search/?q={search_term_string}` },
        'query-input': 'required name=search_term_string'
      }
    },
    {
      '@context': 'https://schema.org',
      '@type': 'Organization',
      name: 'SupplementFiles',
      url: BASE_URL
    }
  ]);

  const body = `
  <main>
    <div class="home-hero">
      <h1>FDA Supplement Adverse Event Reports, Made Legible</h1>
      <p class="home-sub">Search real reports submitted to the FDA about dietary supplements — by brand, product, and outcome. Data from the FDA's CAERS database.</p>
      <form class="search-form" action="/search/" method="get" role="search">
        <input class="search-input" type="search" name="q" placeholder="Search supplements — try &quot;Centrum Silver&quot; or &quot;Kratom&quot;" aria-label="Search supplements">
        <button class="search-btn" type="submit">Search</button>
      </form>
      <p class="search-hints">
        Try:
        <a href="/supplements/5-hour-energy/">5 Hour Energy</a> ·
        <a href="/supplements/kratom/">Kratom</a> ·
        <a href="/supplements/centrum-silver-womens-50-plus/">Centrum Silver Women's 50+</a>
      </p>
    </div>

    <div class="stats-bar">
      <div class="stat-item"><span class="stat-num">54,000+</span><span class="stat-label">Total CAERS reports</span></div>
      <div class="stat-item"><span class="stat-num">${allProducts.length}</span><span class="stat-label">Products indexed</span></div>
      <div class="stat-item"><span class="stat-num">2004–2026</span><span class="stat-label">Data coverage</span></div>
      <div class="stat-item"><span class="stat-num">${FORMATTED_DATE}</span><span class="stat-label">Last updated</span></div>
    </div>

    <div style="max-width:960px;margin:0 auto;padding:0 1rem">
      <div class="trust-block">
        <h2>What this data is — and isn't</h2>
        <p>All data comes from the FDA's CFSAN Adverse Event Reporting System (CAERS) — voluntary reports submitted by consumers, healthcare providers, and manufacturers. <strong>A report does not mean the product caused the effect.</strong> Report counts reflect reporting activity, not real-world incidence or causation. Many factors — media coverage, recalls, litigation — influence how many reports a product accumulates.</p>
        <div class="trust-block-links">
          <a href="https://open.fda.gov/food/event/" target="_blank" rel="noopener noreferrer">openFDA CAERS source ↗</a>
          <a href="/methodology/">Full methodology &amp; data notes</a>
        </div>
      </div>

      <h2 class="section-hd">Notable products in the data</h2>
      <div class="featured-grid">
        ${featuredCards}
      </div>

      <div style="display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:3rem">
        <a href="/supplements/" style="padding:.75rem 1.5rem;background:var(--primary);color:#fff;border-radius:8px;font-weight:600;font-size:.9375rem">Browse all ${allProducts.length} products →</a>
        <a href="/methodology/" style="padding:.75rem 1.5rem;border:1px solid var(--border);border-radius:8px;font-weight:600;font-size:.9375rem;color:var(--text)">About the data</a>
      </div>
    </div>
  </main>`;

  return pageShell({
    title: 'SupplementFiles — FDA Supplement Adverse Event Reports',
    description: 'Search real FDA adverse event reports for dietary supplements. Data from the FDA\'s CAERS database — reactions, outcomes, and demographics by brand.',
    canonical,
    jsonLd,
    body
  });
}

// ─── Browse / index page ───────────────────────────────────────────────────────
function renderBrowsePage(allProducts, slugMap, families) {
  const canonical = `${BASE_URL}/supplements/`;

  // A-Z: sort by first meaningful character (skip leading digits/spaces)
  const sorted = [...allProducts].sort((a, b) => {
    const ka = a.canonical_display_name.replace(/^\d+\s*/, '').toLowerCase();
    const kb = b.canonical_display_name.replace(/^\d+\s*/, '').toLowerCase();
    return ka.localeCompare(kb);
  });

  // Group by first letter (digits → '#')
  const byLetter = {};
  for (const p of sorted) {
    const first = p.canonical_display_name[0].toUpperCase();
    const key   = /[A-Z]/.test(first) ? first : '#';
    if (!byLetter[key]) byLetter[key] = [];
    byLetter[key].push(p);
  }

  const azHTML = Object.entries(byLetter)
    .sort(([a], [b]) => a === '#' ? 1 : b === '#' ? -1 : a.localeCompare(b))
    .map(([letter, items]) => `<div class="az-group">
      <div class="az-letter">${esc(letter)}</div>
      <ul class="az-list">
        ${items.map(p => {
          const pSlug = slugMap.get(p.canonical_display_name);
          const cat   = getCategory(p);
          return `<li class="az-item">
          <a href="/supplements/${pSlug}/">${esc(p.canonical_display_name)}</a>
          <span class="az-item-meta">${esc(cat)} · ${fmt(p.total_reports)} reports</span>
        </li>`;
        }).join('\n        ')}
      </ul>
    </div>`).join('\n  ');

  // Family view: families with ≥2 members first, solo products after
  const familyEntries = Object.entries(families)
    .filter(([, skus]) => skus.length >= 2)
    .sort(([a], [b]) => a.localeCompare(b));

  const soloProducts = allProducts
    .filter(p => !p.brand_family || (families[p.brand_family] || []).length < 2)
    .sort((a, b) => a.canonical_display_name.localeCompare(b.canonical_display_name));

  const familyHTML = familyEntries.map(([familyName, skus]) => {
    const hubSlug     = slug(familyName);
    const sortedSkus  = [...skus].sort((a, b) => b.total_reports - a.total_reports);
    const skuRowsHTML = sortedSkus.map(p => {
      const pSlug = slugMap.get(p.canonical_display_name);
      return `<div class="family-sku-row">
          <a href="/supplements/${pSlug}/">${esc(p.canonical_display_name)}</a>
          <span class="family-sku-count">${fmt(p.total_reports)} reports</span>
        </div>`;
    }).join('\n        ');
    return `<div class="family-block">
      <div class="family-block-hd">
        <h3><a href="/supplements/${hubSlug}/">${esc(familyName)}</a></h3>
        <span class="az-item-meta">${skus.length} SKUs tracked</span>
      </div>
      ${skuRowsHTML}
    </div>`;
  }).join('\n  ');

  const soloHTML = soloProducts.length ? `<h3 style="font-size:.85rem;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin:1.5rem 0 .75rem">Other Products</h3>
  <ul class="az-list">
    ${soloProducts.map(p => {
      const pSlug = slugMap.get(p.canonical_display_name);
      return `<li class="az-item">
      <a href="/supplements/${pSlug}/">${esc(p.canonical_display_name)}</a>
      <span class="az-item-meta">${fmt(p.total_reports)} reports</span>
    </li>`;
    }).join('\n    ')}
  </ul>` : '';

  const jsonLd = JSON.stringify({
    '@context': 'https://schema.org',
    '@type': 'CollectionPage',
    name: 'All Dietary Supplements — FDA Adverse Event Reports',
    description: `Browse ${allProducts.length} dietary supplement products indexed from the FDA's CAERS adverse event database.`,
    url: canonical,
    publisher: { '@type': 'Organization', name: 'SupplementFiles' },
    dateModified: CURRENT_DATE
  });

  const body = `
  <main>
    <div style="max-width:960px;margin:0 auto;padding:2rem 1rem 4rem">
      <div class="product-hero" style="text-align:left;max-width:unset">
        <h1 style="font-size:clamp(1.5rem,3vw,2rem)">Dietary Supplements in FDA Data</h1>
        <p class="product-meta">${allProducts.length} products indexed from the FDA's CAERS database · ${FORMATTED_DATE}</p>
      </div>

      <div class="browse-tabs" role="tablist">
        <button class="browse-tab active" role="tab" aria-selected="true" data-view="az">A–Z</button>
        <button class="browse-tab" role="tab" aria-selected="false" data-view="families">By brand family</button>
      </div>

      <div id="view-az" class="browse-view active">
        ${azHTML}
      </div>

      <div id="view-families" class="browse-view">
        ${familyHTML}
        ${soloHTML}
      </div>
    </div>
  </main>

  <script>
    document.querySelectorAll('.browse-tab').forEach(function(tab){
      tab.addEventListener('click',function(){
        document.querySelectorAll('.browse-tab').forEach(function(t){t.classList.remove('active');t.setAttribute('aria-selected','false');});
        document.querySelectorAll('.browse-view').forEach(function(v){v.classList.remove('active');});
        tab.classList.add('active');tab.setAttribute('aria-selected','true');
        document.getElementById('view-'+tab.dataset.view).classList.add('active');
      });
    });
  </script>`;

  return pageShell({
    title: 'All Dietary Supplements — FDA Adverse Event Reports | SupplementFiles',
    description: `Browse ${allProducts.length} dietary supplement products indexed from the FDA's CAERS database. Reactions, outcomes, and demographics by brand.`,
    canonical,
    jsonLd,
    body
  });
}

// ─── Search page ───────────────────────────────────────────────────────────────
function renderSearchPage() {
  const canonical = `${BASE_URL}/search/`;
  const jsonLd = JSON.stringify({
    '@context': 'https://schema.org',
    '@type': 'WebPage',
    name: 'Search — SupplementFiles',
    url: canonical,
    publisher: { '@type': 'Organization', name: 'SupplementFiles' }
  });

  const body = `
  <main>
    <div style="max-width:960px;margin:0 auto;padding:2rem 1rem 4rem">
      <div class="product-hero" style="margin-bottom:1rem">
        <h1 style="font-size:clamp(1.5rem,3vw,2rem)">Search Supplements</h1>
        <p class="product-meta">Search across ${''} products indexed from the FDA's CAERS database.</p>
      </div>
      <div class="search-wrap">
        <div id="search"></div>
        <p class="pf-hint">Search is powered by <a href="https://pagefind.app" target="_blank" rel="noopener">Pagefind</a> — results are indexed from the full text of every product page.</p>
      </div>
    </div>
  </main>

  <link href="/pagefind/pagefind-ui.css" rel="stylesheet">
  <script src="/pagefind/pagefind-ui.js"><\/script>
  <script>
    window.addEventListener('DOMContentLoaded', function() {
      var ui = new PagefindUI({ element: '#search', showImages: false, excerptLength: 120 });
      // Pre-fill from ?q= URL parameter
      var q = new URLSearchParams(window.location.search).get('q');
      if (q) {
        var inp = document.querySelector('.pagefind-ui__search-input');
        if (inp) { inp.value = q; inp.dispatchEvent(new Event('input', { bubbles: true })); }
      }
    });
  <\/script>`;

  return pageShell({ title: 'Search — SupplementFiles', description: 'Search FDA adverse event reports for dietary supplements by brand name.', canonical, jsonLd, body });
}

// ─── 404 page ──────────────────────────────────────────────────────────────────
function render404() {
  const canonical = `${BASE_URL}/404.html`;
  const jsonLd = JSON.stringify({ '@context': 'https://schema.org', '@type': 'WebPage', name: 'Page Not Found — SupplementFiles', url: canonical });

  const body = `
  <main>
    <div class="error-hero">
      <h1>404</h1>
      <p>This page doesn't exist or may have moved.</p>
      <div class="error-links">
        <a href="/">Back to homepage</a>
        <a href="/supplements/">Browse all supplements</a>
        <a href="/search/">Search</a>
      </div>
    </div>
  </main>`;

  return pageShell({ title: 'Page Not Found — SupplementFiles', description: 'The requested page could not be found.', canonical, jsonLd, body });
}

// ─── Sitemap ───────────────────────────────────────────────────────────────────
function generateSitemap(productSlugs, hubSlugs) {
  const urls = [
    { loc: `${BASE_URL}/`,             priority: '1.0', freq: 'weekly'  },
    { loc: `${BASE_URL}/supplements/`, priority: '0.8', freq: 'weekly'  },
    { loc: `${BASE_URL}/search/`,      priority: '0.5', freq: 'monthly' },
    { loc: `${BASE_URL}/about/`,       priority: '0.7', freq: 'monthly' },
    { loc: `${BASE_URL}/faq/`,         priority: '0.7', freq: 'monthly' },
    { loc: `${BASE_URL}/methodology/`, priority: '0.6', freq: 'monthly' },
    { loc: `${BASE_URL}/privacy/`,     priority: '0.3', freq: 'yearly'  },
    { loc: `${BASE_URL}/terms/`,       priority: '0.3', freq: 'yearly'  },
    { loc: `${BASE_URL}/contact/`,     priority: '0.4', freq: 'monthly' },
    ...productSlugs.map(s => ({ loc: `${BASE_URL}/supplements/${s}/`, priority: '0.8', freq: 'monthly' })),
    ...hubSlugs.map(s    => ({ loc: `${BASE_URL}/supplements/${s}/`, priority: '0.7', freq: 'monthly' })),
  ];
  const urlXml = urls.map(u =>
    `  <url>\n    <loc>${u.loc}</loc>\n    <changefreq>${u.freq}</changefreq>\n    <priority>${u.priority}</priority>\n    <lastmod>${CURRENT_DATE}</lastmod>\n  </url>`
  ).join('\n');
  return `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urlXml}\n</urlset>`;
}

// ─── Robots.txt ────────────────────────────────────────────────────────────────
function generateRobots() {
  return `User-agent: *\nAllow: /\n\nSitemap: ${BASE_URL}/sitemap.xml\n`;
}

// ─── Main ─────────────────────────────────────────────────────────────────────
function main() {
  const raw = JSON.parse(fs.readFileSync(DATA_FILE, 'utf8'));
  const allProducts = Object.values(raw).filter(p => p.page_eligible !== false);

  // Build family groups
  const families = {};
  for (const p of allProducts) {
    if (p.brand_family) {
      if (!families[p.brand_family]) families[p.brand_family] = [];
      families[p.brand_family].push(p);
    }
  }

  // Pre-compute slugs — detect collisions with family hub slugs and resolve
  const familySlugs = new Set(Object.keys(families).map(slug));
  const slugMap = new Map(); // canonical_display_name → url slug

  for (const p of allProducts) {
    let s = slug(p.canonical_display_name);
    // If this product's slug == its own family's hub slug, disambiguate
    if (p.brand_family && slug(p.brand_family) === s) {
      s = s + '-supplement';
    }
    slugMap.set(p.canonical_display_name, s);
  }

  let count = 0;

  // Generate product pages
  for (const product of allProducts) {
    const productSlug = slugMap.get(product.canonical_display_name);
    const outDir = path.join(OUT_DIR, 'supplements', productSlug);
    ensure(outDir);
    const html = renderProductPage(product, allProducts, slugMap);
    fs.writeFileSync(path.join(outDir, 'index.html'), html, 'utf8');
    console.log(`  ✓ /supplements/${productSlug}/  (${fmt(product.total_reports)} reports)`);
    count++;
  }

  // Generate hub pages for families with ≥2 eligible SKUs
  for (const [familyName, skus] of Object.entries(families)) {
    if (skus.length < 2) continue;
    const { html, hubSlug } = renderHubPage(familyName, skus, slugMap);
    const outDir = path.join(OUT_DIR, 'supplements', hubSlug);
    ensure(outDir);
    fs.writeFileSync(path.join(outDir, 'index.html'), html, 'utf8');
    console.log(`  ✓ /supplements/${hubSlug}/  (hub: ${skus.length} SKUs)`);
    count++;
  }

  // Methodology + supporting pages
  const SUPPORT_PAGES = [
    ['methodology', renderMethodologyPage],
    ['about',       renderAboutPage],
    ['faq',         renderFaqPage],
    ['privacy',     renderPrivacyPage],
    ['terms',       renderTermsPage],
    ['contact',     renderContactPage],
  ];
  for (const [dir, fn] of SUPPORT_PAGES) {
    ensure(path.join(OUT_DIR, dir));
    fs.writeFileSync(path.join(OUT_DIR, dir, 'index.html'), fn(), 'utf8');
    console.log(`  ✓ /${dir}/`);
    count++;
  }

  // Homepage
  fs.writeFileSync(path.join(OUT_DIR, 'index.html'), renderHomepage(allProducts, slugMap), 'utf8');
  console.log('  ✓ / (homepage)');
  count++;

  // Browse / index page
  ensure(path.join(OUT_DIR, 'supplements'));
  fs.writeFileSync(path.join(OUT_DIR, 'supplements', 'index.html'), renderBrowsePage(allProducts, slugMap, families), 'utf8');
  console.log('  ✓ /supplements/ (browse index)');
  count++;

  // Search page
  ensure(path.join(OUT_DIR, 'search'));
  fs.writeFileSync(path.join(OUT_DIR, 'search', 'index.html'), renderSearchPage(), 'utf8');
  console.log('  ✓ /search/');
  count++;

  // 404
  fs.writeFileSync(path.join(OUT_DIR, '404.html'), render404(), 'utf8');
  console.log('  ✓ 404.html');
  count++;

  // Sitemap + robots.txt
  const productSlugs = allProducts.map(p => slugMap.get(p.canonical_display_name));
  const hubSlugs = Object.entries(families)
    .filter(([, skus]) => skus.length >= 2)
    .map(([name]) => slug(name));

  fs.writeFileSync(path.join(OUT_DIR, 'sitemap.xml'), generateSitemap(productSlugs, hubSlugs), 'utf8');
  console.log('  ✓ sitemap.xml');

  fs.writeFileSync(path.join(OUT_DIR, 'robots.txt'), generateRobots(), 'utf8');
  console.log('  ✓ robots.txt');

  console.log(`\nDone — ${count} pages written to docs/`);
}

main();
