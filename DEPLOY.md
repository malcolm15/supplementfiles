# Deploy Guide — SupplementSignal

## Recommended: Cloudflare Pages

You already have a Cloudflare account for PillSignal — Cloudflare Pages is the natural choice.
Automatic deploys from GitHub, free SSL, global CDN, custom domain in ~5 minutes.

---

## Step 1 — Create a GitHub repo

1. Go to https://github.com/new
2. Name: `supplementsignal` (or your preferred name)
3. Set to **Private** for now (can make public later)
4. Do NOT initialize with README (the repo is already set up locally)
5. Copy the remote URL shown (e.g. `https://github.com/yourname/supplementsignal.git`)

Then in this directory:

```bash
git remote add origin https://github.com/yourname/supplementsignal.git
git branch -M main
git push -u origin main
```

---

## Step 2 — Connect to Cloudflare Pages

1. In Cloudflare dashboard → **Workers & Pages** → **Create** → **Pages** → **Connect to Git**
2. Select your GitHub account → select the `supplementsignal` repo
3. Configure the build:

| Setting | Value |
|---|---|
| **Build command** | `node scripts/generate-pages.js && npx pagefind --site docs` |
| **Build output directory** | `docs` |
| **Node.js version** | `18` (set via environment variable `NODE_VERSION = 18`) |

4. Click **Save and Deploy** — first deploy runs automatically.

---

## Step 3 — Add your GA4 measurement ID

1. Create a new GA4 property at https://analytics.google.com
   - Property name: SupplementSignal
   - Data stream: Web → enter your domain
   - Copy the Measurement ID (format: `G-XXXXXXXXXX`)
2. Open `scripts/generate-pages.js`
3. Find line: `const GA4_ID = '';`
4. Change to: `const GA4_ID = 'G-XXXXXXXXXX';`
5. Run `npm run build` (or `node scripts/generate-pages.js && npx pagefind --site docs`)
6. Commit and push — Cloudflare Pages auto-deploys

---

## Step 4 — Point your domain DNS

In **Cloudflare DNS** for your domain:

1. In Cloudflare Pages → your project → **Custom domains** → **Set up a custom domain**
2. Enter your domain (e.g. `supplementsignal.com`)
3. Cloudflare will add the DNS records automatically if your domain is on Cloudflare

If your domain is at a different registrar, add these DNS records manually:

```
Type  Name   Content
CNAME @      <your-project>.pages.dev
CNAME www    <your-project>.pages.dev
```

SSL is automatic (Cloudflare manages the certificate).

---

## Step 5 — Post-deploy checklist

- [ ] Visit your live URL and confirm homepage loads
- [ ] Test search: try "Centrum Silver" on `/search/`
- [ ] Visit a product page and confirm caveat band is visible
- [ ] Submit sitemap to Google Search Console: `https://yourdomain.com/sitemap.xml`
- [ ] Submit sitemap to Bing Webmaster Tools
- [ ] Verify GA4 is receiving hits (check Realtime report)
- [ ] Test on mobile

---

## Rebuild & deploy workflow

Every time you change data or the template:

```bash
npm run build          # generates HTML + builds Pagefind index
git add -A
git commit -m "Rebuild: describe what changed"
git push               # triggers Cloudflare Pages auto-deploy
```

Cloudflare Pages deploys in ~30 seconds. No manual steps after initial setup.

---

## Environment variables in Cloudflare Pages

If you move the GA4 ID out of the generator and into a build-time env var later:

In Cloudflare Pages → project → **Settings** → **Environment variables**:

```
NODE_VERSION = 18
GA4_ID = G-XXXXXXXXXX   (if you refactor to read from env)
```

---

## Alternative: Netlify

If you prefer Netlify:
1. netlify.com → **Add new site** → **Import an existing project** → GitHub
2. Build command: `node scripts/generate-pages.js && npx pagefind --site docs`
3. Publish directory: `docs`
4. Custom domain: same DNS CNAME approach as above

Both are free, both have auto-deploy from GitHub. Cloudflare Pages is recommended because you already have a Cloudflare account.
