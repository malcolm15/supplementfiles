#!/usr/bin/env node
'use strict';

/**
 * generate-assets.js — SupplementFiles brand asset generation
 *
 * Generates all favicon sizes, the web manifest, and OG/Twitter images
 * from SVG via sharp. Run before generate-pages.js so favicons exist in
 * docs/ when pages are written.
 *
 * Usage: node scripts/generate-assets.js
 */

const sharp = require('sharp');
const fs    = require('fs');
const path  = require('path');

const DOCS = path.join(__dirname, '..', 'docs');

const BRAND   = '#00A67E';   // --primary  (matches site CSS)
const BRAND_D = '#008F6B';   // --primary-h (darker half of two-tone capsule)

// ─── Icon SVG ─────────────────────────────────────────────────────────────────
// Concept: brand-green rounded-square bg; bold white folder (body + tab);
// two-tone brand-colored capsule resting on the folder — reads as "Files + Supplement".

function iconSvg(size) {
  // Unique clip id per size avoids any cross-contamination if SVGs are ever inlined.
  const cid = `cap${size}`;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 100 100">
  <!-- Rounded-square background -->
  <rect width="100" height="100" rx="22" fill="${BRAND}"/>

  <!-- Folder body — bold white rectangle, legible at 16px -->
  <rect x="11" y="40" width="78" height="46" rx="4" fill="#ffffff"/>

  <!-- Folder tab — upper-left bump (joins flush with the body) -->
  <path d="M11,40 L11,30 Q11,26 15,26 L43,26 Q47.5,26 49.5,31 L52.5,40 Z" fill="#ffffff"/>

  <!-- Capsule — two-tone horizontal pill; brand color reads on white folder -->
  <clipPath id="${cid}">
    <rect x="50" y="53" width="34" height="15" rx="7.5"/>
  </clipPath>
  <!-- Left half -->
  <rect x="50" y="53" width="17" height="15" clip-path="url(#${cid})" fill="${BRAND}"/>
  <!-- Right half (slightly darker for two-tone split) -->
  <rect x="67" y="53" width="17" height="15" clip-path="url(#${cid})" fill="${BRAND_D}"/>
  <!-- White split line -->
  <rect x="66" y="53" width="2" height="15" clip-path="url(#${cid})" fill="#ffffff"/>
</svg>`;
}

// ─── OG image SVG (1200×630) ──────────────────────────────────────────────────

function ogSvg() {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <!-- Background -->
  <rect width="1200" height="630" fill="${BRAND}"/>
  <!-- Depth vignette -->
  <radialGradient id="vg" cx="50%" cy="50%" r="70%">
    <stop offset="0%" stop-color="rgba(255,255,255,0.07)"/>
    <stop offset="100%" stop-color="rgba(0,0,0,0.13)"/>
  </radialGradient>
  <rect width="1200" height="630" fill="url(#vg)"/>

  <!-- Icon — 2× scale centered at (600, 175) -->
  <g transform="translate(500,75) scale(2)">
    <rect width="100" height="100" rx="22" fill="rgba(255,255,255,0.18)"/>
    <rect x="11" y="40" width="78" height="46" rx="4" fill="#ffffff"/>
    <path d="M11,40 L11,30 Q11,26 15,26 L43,26 Q47.5,26 49.5,31 L52.5,40 Z" fill="#ffffff"/>
    <clipPath id="cap-og">
      <rect x="50" y="53" width="34" height="15" rx="7.5"/>
    </clipPath>
    <rect x="50" y="53" width="17" height="15" clip-path="url(#cap-og)" fill="${BRAND}"/>
    <rect x="67" y="53" width="17" height="15" clip-path="url(#cap-og)" fill="${BRAND_D}"/>
    <rect x="66" y="53" width="2" height="15" clip-path="url(#cap-og)" fill="#ffffff"/>
  </g>

  <!-- Wordmark -->
  <text
    x="600" y="415"
    text-anchor="middle"
    fill="#ffffff"
    font-family="-apple-system,'Helvetica Neue',Arial,sans-serif"
    font-size="104"
    font-weight="800"
    letter-spacing="-2">SupplementFiles</text>

  <!-- Tagline -->
  <text
    x="600" y="494"
    text-anchor="middle"
    fill="rgba(255,255,255,0.82)"
    font-family="-apple-system,'Helvetica Neue',Arial,sans-serif"
    font-size="38"
    font-weight="400"
    letter-spacing="0.3">FDA supplement adverse event reports, made legible</text>
</svg>`;
}

// ─── Twitter/X banner SVG (1500×500) ─────────────────────────────────────────

function twitterBannerSvg() {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="1500" height="500" viewBox="0 0 1500 500">
  <!-- Background -->
  <rect width="1500" height="500" fill="${BRAND}"/>
  <!-- Depth vignette -->
  <radialGradient id="vgb" cx="50%" cy="50%" r="75%">
    <stop offset="0%" stop-color="rgba(255,255,255,0.07)"/>
    <stop offset="100%" stop-color="rgba(0,0,0,0.14)"/>
  </radialGradient>
  <rect width="1500" height="500" fill="url(#vgb)"/>

  <!-- Wordmark -->
  <text
    x="750" y="224"
    text-anchor="middle"
    fill="#ffffff"
    font-family="-apple-system,'Helvetica Neue',Arial,sans-serif"
    font-size="140"
    font-weight="800"
    letter-spacing="-3">SupplementFiles</text>

  <!-- Divider dot -->
  <circle cx="750" cy="268" r="4" fill="rgba(255,255,255,0.5)"/>

  <!-- Tagline -->
  <text
    x="750" y="322"
    text-anchor="middle"
    fill="rgba(255,255,255,0.82)"
    font-family="-apple-system,'Helvetica Neue',Arial,sans-serif"
    font-size="44"
    font-weight="400"
    letter-spacing="0.5">FDA Supplement Adverse Event Reports</text>
</svg>`;
}

// ─── Web manifest ─────────────────────────────────────────────────────────────

function webManifest() {
  return JSON.stringify({
    name:             'SupplementFiles',
    short_name:       'SupplementFiles',
    icons: [
      { src: '/android-chrome-192x192.png', sizes: '192x192', type: 'image/png' },
      { src: '/android-chrome-512x512.png', sizes: '512x512', type: 'image/png' },
    ],
    theme_color:      BRAND,
    background_color: BRAND,
    display:          'standalone',
    start_url:        '/',
  }, null, 2);
}

// ─── Main ─────────────────────────────────────────────────────────────────────

async function main() {
  console.log('\nSupplementFiles — Generate Brand Assets\n');
  fs.mkdirSync(DOCS, { recursive: true });

  const favicons = [
    { file: 'favicon-16x16.png',          size: 16  },
    { file: 'favicon-32x32.png',          size: 32  },
    { file: 'apple-touch-icon.png',       size: 180 },
    { file: 'android-chrome-192x192.png', size: 192 },
    { file: 'android-chrome-512x512.png', size: 512 },
  ];

  for (const { file, size } of favicons) {
    await sharp(Buffer.from(iconSvg(size))).png().toFile(path.join(DOCS, file));
    console.log(`  ✓ ${file}`);
  }

  // favicon.ico — browsers accept 32×32 PNG with .ico extension
  await sharp(Buffer.from(iconSvg(32))).png().toFile(path.join(DOCS, 'favicon.ico'));
  console.log('  ✓ favicon.ico');

  // OG image
  await sharp(Buffer.from(ogSvg())).png().toFile(path.join(DOCS, 'og-image.png'));
  console.log('  ✓ og-image.png  (1200×630)');

  // Twitter/X banner
  await sharp(Buffer.from(twitterBannerSvg())).png().toFile(path.join(DOCS, 'twitter-banner.png'));
  console.log('  ✓ twitter-banner.png  (1500×500)');

  // Web manifest
  fs.writeFileSync(path.join(DOCS, 'site.webmanifest'), webManifest(), 'utf8');
  console.log('  ✓ site.webmanifest');

  console.log('\nDone.\n');
}

main().catch(err => {
  console.error('Fatal:', err.message);
  process.exit(1);
});
