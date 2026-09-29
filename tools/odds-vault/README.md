# Odd$ Vault (`/tools/odds-vault/`)

Free, browser-only metadata cleaner + AES-256 ZIP packager. Static files only; no build step; deploys as-is on Vercel.

| File | Purpose |
|---|---|
| `index.html` | SEO landing page (hero, tool, education, FAQ + JSON-LD, CTAs) |
| `vault.js` | The engine, ported from the original standalone file (see "Engine changes") |
| `vault.css` | Tool styles, scoped under `.vault-app` |
| `page.js` | Analytics events + post-success "More from Favorable Odd$" reveal |
| `vendor/` | Self-hosted `zip.js` 2.7.52 and `pdf-lib` 1.17.1 (see `vendor/NOTICE.txt`) |
| `../tools.css`, `../tools.js` | Shared Free Tools chrome (nav, footer, cards), mobile menu, `foTrack()` analytics shim |

## Maintaining
- **FAQ**: the visible `<details>` FAQ and the `FAQPage` JSON-LD in `index.html` must stay word-for-word identical. Edit both together.
- **Adding a tool**: see the commented card template in `../index.html`; copy `index.html` here as the page template.
- **Analytics**: none is installed on the site. `foTrack(name, params)` forwards to `gtag`, `dataLayer` or `plausible` if one appears, and always fires a `fo:track` DOM event. Events: `vault_page_view`, `vault_started`, `vault_success` (`file_count` only), `vault_cta_click`, `vault_tool_click`, `tools_page_view`, `free_tools_click`, `shop_click`, `services_click` (each with a `location`). Params matching pass/file name/path/content are dropped.
  **The page's CSP has `connect-src 'none'` and `script-src 'self'`.** To add an analytics vendor you must loosen the CSP `<meta>` in `index.html` deliberately. Prefer a cookieless, no-file-data tool and never track anything from inside `vault.js`.

## Privacy / security review
- No `fetch`, XHR, WebSocket, beacon or upload API is used by `vault.js`, `page.js` or `tools.js`. Files are read via `File.arrayBuffer()`/`BlobReader`, and the ZIP is downloaded from a `blob:` URL.
- `zip.min.js` contains generic `fetch`/`XMLHttpRequest` code (its `HttpReader`, unused here). The page CSP (`connect-src 'none'`) blocks any network request regardless.
- Nothing is logged; passwords are never stored (no localStorage/cookies) and only passed to zip.js. Verified in Chromium: only same-origin requests plus the Google Fonts stylesheet, zero CSP violations.
- Third-party resources: Google Fonts (CSS + font files, same as the rest of the site). Libraries are self-hosted, so no CDN can alter the code that touches files.
- Behaviors worth knowing: **Generate** copies the new password to the clipboard; `autocomplete="new-password"` lets the browser offer to save it; large files are processed in memory.

## Engine changes vs. the original file
1. pdf-lib is loaded on demand (first PDF) from the same origin instead of at page load.
2. Dispatches `vault:started` / `vault:success` events (counts only).
3. **Bug fix (privacy):** in `stripPdf`, the XMP stream was un-linked from the catalog but pdf-lib still wrote the orphaned object, so its contents stayed in the output while the report claimed "XMP removed". It is now deleted from the context. Verified with a fixture PDF.

## Known limitations (documented on the page, deliberately not changed)
- JPEG: data appended after the end-of-image marker (e.g. motion-photo video) is kept. EXIF orientation is removed with the rest of EXIF, so some photos display rotated.
- PDF: only document Info fields and the catalog XMP; custom Info keys, annotations, attachments, page/image-level XMP are untouched. Encrypted PDFs fail.
- Office: core/app properties and thumbnail only. `custom.xml`, comments, tracked changes and embedded media metadata remain.
- The report can under-report "Author"/"Title" for Office files whose XML puts an `xmlns` on `<dc:creator>` (removal still happens; the whole part is replaced).
- Password strength is only a heuristic meter; 10 characters is the minimum, so a weak password weakens the AES encryption.

## Manual test checklist before/after deploy
1. Open the cleaned DOCX/XLSX/PPTX in Microsoft Office (Protected View and edit) and confirm no repair prompt.
2. Open the ZIP with 7-Zip, Keka/The Unarchiver and Windows Explorer (expect Explorer to fail); with names hidden you get `contents.zip`.
3. Real phone photos: iPhone (JPEG, not HEIC) and Android motion photo; check `exiftool` output and rotation.
4. Test on iOS Safari and Android Chrome (file picker, download, memory with large files).
5. Confirm `/tools`, `/tools/`, `/tools/odds-vault` and `/tools/odds-vault/` all load after deploy.
