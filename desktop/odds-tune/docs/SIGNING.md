# Code signing

**The current Odd$ Tune build is not code-signed.** The website and every report say so. Do not describe it as signed or "trusted".

## Why sign

An unsigned EXE downloaded from the web can trigger Windows SmartScreen and antivirus warnings. A signature identifies the publisher
and shows the file was not altered after signing.

## Where signing happens

In `.github/workflows/build-odds-tune.yml`, job **build**, step **"Sign"**: after PyInstaller and the EXE smoke test, **before** the
"Compute SHA-256 and build info" step. The step is skipped unless the secrets below exist, so the pipeline works unsigned today.

## GitHub Secrets (Settings > Secrets and variables > Actions)

| Secret | Purpose |
|---|---|
| `CODESIGN_PFX_BASE64` | Base64 of the `.pfx` certificate (`[Convert]::ToBase64String([IO.File]::ReadAllBytes('cert.pfx'))`) |
| `CODESIGN_PFX_PASSWORD` | Password for that `.pfx` |
| `CODESIGN_TIMESTAMP_URL` | Optional RFC 3161 timestamp server (default `http://timestamp.digicert.com`) |

Never commit certificates, passwords or `.env` files (`.gitignore` blocks `*.pfx`, `*.p12`, `*.pem`, `*.key`, `.env*`, and a test scans for key material).

> **Important, and not yet tested:** the included step is for a certificate that can be exported as a `.pfx`. Since mid-2023 newly issued
> public code-signing certificates must keep their private key in hardware (token, HSM or cloud service), so most new certificates cannot be
> exported. For those, replace the "Sign" step with your provider's GitHub integration (for example Azure Trusted Signing / Artifact Signing,
> or a cloud-HSM service such as DigiCert KeyLocker or SSL.com eSigner). Keep the same position in the pipeline (before hashing). This step
> has not been exercised because no certificate exists yet.

## Order matters: hash AFTER signing

Signing changes the file bytes. The pipeline computes SHA-256 only after the Sign step, records `signed`/`signature_status` in
`build-info.json`, and names the artifact `odds-tune-windows-x64-signed` or `...-unsigned`. If you sign by hand outside CI, recompute the
hash of the signed file and update the website. Never publish the pre-signing hash for a signed binary.

## Verification

`signtool verify /pa /v OddsTune.exe` or `Get-AuthenticodeSignature .\OddsTune.exe`. Keep old release hashes in the changelog for auditability.
