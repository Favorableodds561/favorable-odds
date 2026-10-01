# Odd$ Guard (`/tools/odds-guard/`)

Landing page + gated download for the Windows PowerShell audit tool **Odd$ Guard v0.1.0**. Static files only, deploys as-is on Vercel. Unlike Odd$ Vault this is **not** a browser tool: the page only distributes the ZIP.

| Path | Purpose |
|---|---|
| `index.html` | SEO landing page (hero, email step, release details, checks, limits, sample, how-to, guide, FAQ + JSON-LD) |
| `guard.css`, `guard.js`, `guard-config.js` | Page styles; lead form + reveal + events; **the config/integration point** |
| `download/OddsGuard-v0.1.zip` (+ `.sha256`) | The public release. Never linked in static HTML; `guard.js` adds the link after a successful lead step |
| `source/OddsGuard.ps1.txt`, `Run-OddsGuard.bat.txt` | Plain-text copies of the exact files inside the ZIP, for "read before you run" |
| `sample-report/index.html` | The supplied sample report, **unmodified** (byte-identical) |
| `vendor/email.min.js` | Self-hosted `@emailjs/browser` 4.4.1 (see `vendor/NOTICE.txt`) |

## Email capture (how the download unlocks)
1. Visitor enters an email; `guard.js` validates it and calls the configured provider.
2. **Only when the provider resolves** is the download link inserted and the panel shown. On failure nothing is revealed, nothing is stored, and the visitor sees an error plus an email-us link. A honeypot field drops naive bots.
3. Only the flag `fo_guard_unlocked=1` is kept in `localStorage` so returning visitors skip the form. The email itself is never stored, logged or sent to analytics.

**Provider today: EmailJS**, the provider already used by `/services` and `/bookkeeping` (same public key and service ID; the same 'order request' template `template_lbtqhem`). Each lead arrives in that inbox as a request titled "Odd$ Guard v0.1.0 free download". This is a *notification*, not a mailing list: there is no list, no consent record, no unsubscribe tooling.

**To change provider** (recommended before real volume; Brevo is already in your stack): add a function under `providers` in `guard.js` that returns a Promise resolving only when the address was really accepted, set `lead.provider` in `guard-config.js`, and update the `connect-src` host in the CSP `<meta>` of `index.html`. Setting `lead.provider: null` disables the form and keeps the download hidden.

**This is a soft gate.** The ZIP is a public static file, so anyone who knows the URL can fetch it. That is normal for a lead magnet, but it is not access control. (`X-Robots-Tag: noindex` is set on `download/`, `source/` and `sample-report/` in `vercel.json`.)

## Releasing a new version
1. Put the new ZIP in `download/` and regenerate `OddsGuard-vX.Y.zip.sha256` (`sha256sum`).
2. Update `source/*.txt` from the ZIP contents and `sample-report/index.html` if the demo changed.
3. Update in `index.html`: version, file name, size, both SHA-256 values (Release details), the JSON-LD `softwareVersion`, and `guard-config.js` (`version`, `downloadPath`) and the `download` attribute of `#download-link`.
4. Verify: `unzip -p download/OddsGuard-vX.Y.zip OddsGuard/OddsGuard.ps1 | sha256sum` must equal the hash shown for `OddsGuard.ps1`.

## Analytics events (via `foTrack`, no analytics vendor installed)
`guard_page_view`, `guard_cta_click`, `guard_sample_click`, `guard_form_submit`, `guard_download_reveal`, `guard_download_click`, `guard_help_click`, `guard_source_click`, `guard_tool_click` (directory), `services_click`, `free_tools_click`, `shop_click`. None carries the email address, report contents, computer names, file names or scan details. If you add an analytics vendor, extend the page CSP deliberately.

## Security / distribution review of v0.1.0 (static review of the source; the script was **not** executed: no Windows/PowerShell available)
- **Package:** ZIP = `OddsGuard/` with `OddsGuard.ps1` (66,666 B, CRLF line endings), `Run-OddsGuard.bat` (575 B), `README.md`, `OddsGuard-SAMPLE-report.html`. Contents are byte-identical to the loose files supplied. No hidden files, binaries, credentials, keys, emails or personal data; the only names/paths are the fictional demo data (`Martha`, `support01`, `vm`).
- **Code signing:** **not signed** (no Authenticode signature block). The page says so. README also says to sign before selling.
- **Network:** the script has no web/socket cmdlets or .NET network calls. `https://favorableodds.io` appears only as a link inside the generated report and the report contains no scripts or external resources. Caveat: `Get-AuthenticodeSignature` is performed by Windows, which may do certificate lookups online.
- **Writes:** report HTML + JSON to `Reports\` next to the script (fallback `Desktop\OddsGuard Reports`), plus a temporary `.write-test` file it deletes. No registry/system changes; the only executed processes are `Start-Process` on the finished report (unless `-NoOpen`). All scan-derived text is HTML-encoded in the report.
- **Launcher:** elevates via UAC (`Start-Process -Verb RunAs`); on refusal it runs a limited scan. Runs PowerShell with `-NoProfile -ExecutionPolicy Bypass` (process-scoped, not persistent). That is standard for unsigned scripts but is a pattern AV/SmartScreen heuristics dislike.
- **Admin:** needed for some checks (Defender exclusions are skipped without it; other users' folders may be unreadable). Everything else runs unelevated.
- **Sensitive output:** the report/JSON contain computer name, Windows usernames, file paths, full startup/task command lines (may contain tokens in arguments), Defender exclusions, hosts entries, proxy addresses. The page warns users before sharing.

### Issues found (documented; the scanner was NOT modified)
1. **Unsigned** (launch blocker for a wide public release; see below).
2. **Sample report is inconsistent:** the "What was checked" list says 6 startup items, 9 task actions and 7 extensions, but the inventory tables list 2, 1 and 1. Cosmetic, but a careful reader will notice.
3. **Launcher breaks on paths containing an apostrophe** (e.g. `C:\Users\O'Brien\...`): the single-quoted `Start-Process '%~f0'` fails, so it prints "Permission was not granted" and runs a limited scan even if the user would have approved.
4. **HKCU checks reflect the elevating account:** if a standard user approves UAC with another admin's password, startup (HKCU) and proxy checks describe the admin's profile. The page tells users to run it from the account they want checked.
5. **Coverage is narrower than "antivirus/browsers" implies:** exclusions come from Microsoft Defender only; extensions only Chrome/Edge/Brave; accounts are local only. The page states this.
6. **Errors are silent by design** (`$ErrorActionPreference='SilentlyContinue'`); a check that fails to read something can look "Clear". The report only marks *whole checks* as skipped.
7. **Windows 10/11 Home/Pro, with and without admin, is still untested** (the README lists it as a to-do). The page says "built for Windows 10 and 11" and does not claim it was tested.
8. **Public ZIP contains the sample report.** Harmless, but it carries a hostname (`vm`) and could be mistaken for a real scan. Consider removing it from the public ZIP (the page hosts it anyway).

## Launch blockers / recommendations
- Sign `OddsGuard.ps1` (and ideally the ZIP/launcher) with a code-signing certificate, re-issue the ZIP and update both hashes on the page.
- Test on real Windows 10/11 (Home + Pro, admin and standard, PowerShell 5.1) and with Defender + a third-party AV.
- Add a privacy policy page and confirm the marketing-email wording under the form (it promises updates/tips and removal on request). Decide how you will actually email leads and honour opt-outs (unsubscribe, physical address if you send commercial email; EU visitors may need explicit consent).
- Create a dedicated EmailJS template or move to a real ESP; EmailJS free tier limits will throttle a lead magnet (when it fails, visitors are not given the download by design).
- There is no fixed-price PC cleanup product: "View Tech Services" goes to `/#services` (Computer Cleanup & Maintenance). Consider an Instant Service such as a report review.
