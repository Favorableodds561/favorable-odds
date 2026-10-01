# Release process

1. **Version**: change `APP_VERSION` in `odds_tune_core.py`, `version_info.txt` (both `filevers/prodvers` and the string values), the README and the
   website page. `tests/test_consistency.py` fails the build if they disagree. Use semantic versioning (`MAJOR.MINOR.PATCH`) everywhere.
2. **Push** to `feature/odds-tune-v1` (or run the workflow manually with `publish_to_repo`). The workflow validates, builds, self-tests the EXE,
   signs if secrets exist, hashes, uploads the artifact and (feature branch only) commits `tools/odds-tune/download/v<version>/OddsTune.exe`,
   `OddsTune.exe.sha256` and `build-info.json`.
3. **Website**: copy the version, size and SHA-256 from `build-info.json` into `tools/odds-tune/index.html` (release box and JSON-LD) and
   confirm `signed` matches what the page says. The hash on the page must be that of the committed file:
   `sha256sum tools/odds-tune/download/v<version>/OddsTune.exe`.
4. **Do not change `desktop/odds-tune/**` after the build you publish.** PyInstaller output is not byte-reproducible; any source change needs a new build and a new hash.
5. **Manual tests on real machines** (Windows 11 x64 primary, Windows 10 x64 best effort): launch, scan (nothing changes), cleanup on a test user,
   decline UAC (clean message), optimize drive, repair, reports, SmartScreen behaviour for the unsigned build.
6. **Download check** after deploy: download from the live site and compare `Get-FileHash` with the page.
7. **Tag** `odds-tune-v<version>` to create a draft GitHub Release from the same build (optional). Keep a changelog entry on the page.
