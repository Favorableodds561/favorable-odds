# Odd$ Tune v1.0.0

Safe Windows cleanup, maintenance and repair, from Favorable Odds LLC. A small desktop utility that **scans first**, shows
what it found, and only changes what you explicitly choose. It is deliberately *not* an aggressive "PC optimizer".

- Web page: <https://favorableodds.io/tools/odds-tune/>
- Executable: `OddsTune.exe` (Windows x64). Product name shown to users: **Odd$ Tune**
- Status: **v1.0.0, unsigned** (no code-signing certificate yet, see [docs/SIGNING.md](docs/SIGNING.md))

## Supported Windows versions

| Target | Status |
|---|---|
| Windows 11 x64 | **Primary target** |
| Windows 10 x64 (build 19041+) | Best effort |
| ARM64, 32-bit Windows, older Windows | Not supported / not tested. The app says so instead of guessing |

The automated tests and the build run on a GitHub-hosted Windows x64 runner (a Windows Server image). Hands-on testing on
physical Windows 11 / Windows 10 machines is the publisher's manual step (see [docs/RELEASE.md](docs/RELEASE.md)).

## Safety philosophy

1. **Scan, review, choose, clean.** Scanning is strictly read-only (enforced by tests that forbid every modifying API during a scan).
2. **Allowlist only.** Odd$ Tune never searches your profile for `.tmp`/`.log` files. It only looks inside the fixed folders below.
3. **Recent files are never deleted.** A file must be old by *both* modified time and creation time (installers extract files with old
   modified times but new creation times).
4. **No links.** Symbolic links, junctions and every other reparse point are skipped, the root is re-verified while walking, and
   nothing outside the root is ever entered.
5. **Fail safe.** Locked, in-use or unreadable items are skipped and counted. One bad file never aborts a cleanup.
6. **Conservative when unsure.** If a location can't be validated (unusual `TEMP`, redirected folder) it is skipped, not guessed.
7. **Explicit actions.** Cleanup, Recycle Bin, drive optimization and repair each need an intentional click and confirmation.

## What gets cleaned (and only this)

| Category | Location | Minimum age | Admin |
|---|---|---|---|
| User temporary files | `%LOCALAPPDATA%\Temp` (and your `TEMP` folder only if it passes the safety rules) | 48 hours | No |
| Application crash dumps | `%LOCALAPPDATA%\CrashDumps` | 7 days | No |
| DirectX shader cache | `%LOCALAPPDATA%\D3DSCache` | 7 days | No |
| Windows temporary files | `%WINDIR%\Temp` | 72 hours | Some files |
| Windows Error Reporting | `%PROGRAMDATA%\Microsoft\Windows\WER\ReportQueue` and `\ReportArchive` | 7 days | Usually |
| Recycle Bin (Windows drive) | Windows' own Recycle Bin API | n/a, **only if you tick it** | No |

Empty sub-folders are removed only if they were themselves old before the run. The allowlisted folder itself is never removed.
A custom `TEMP` such as `D:\Temp` is accepted only if the folder is named `Temp`/`Tmp`, is not a drive root, a link, inside the Windows
folder, or inside/containing a personal folder (Documents, Desktop, Downloads, Pictures, Music, Videos, OneDrive, Program Files).

## What is NOT cleaned or done

Registry cleaning, "RAM boosting", disabling services or scheduled tasks, automatic startup disabling, driver updating, browser history,
cookies or passwords, Prefetch, `SoftwareDistribution`, `WinSxS`, Downloads/Documents/Desktop, uninstalling software, power-plan or
pagefile changes, DNS/network changes, telemetry, analytics, remote API calls, advertising, background services.

## Cleanup vs. repair

- **Cleanup** (Safe Cleanup tab) removes eligible old temporary files and frees space. It never runs repair tools.
- **Repair** (Maintenance tab) is a separate, explicit action for Windows problems such as errors, crashes or corruption:
  `DISM /Online /Cleanup-Image /RestoreHealth` then `sfc /scannow`. It is not a speed boost and can take a long time.
  DISM may download replacement components through Windows Update.
- **Drive optimization** runs Windows' own `defrag <system drive> /O`, which retrims an SSD or defragments a hard disk as appropriate.
- **Startup apps** are never changed. "Review Startup Apps" only opens Windows Settings > Startup Apps.

## Administrator rights

Odd$ Tune starts and scans as a normal user. Elevation is requested only when needed, after an explanation, and you can say No:

- Protected cleanup (`Windows\Temp`, error reports): optional "Restart as Administrator…".
- Drive optimization and Windows repair: Odd$ Tune starts a second, elevated copy of itself in worker mode (`--task optimize|repair`).
  Only a fixed task name crosses the UAC boundary. No script file is written and no encoded command is used. The worker window shows
  live output and the log/exit codes are saved in the Reports folder.

## Reports (local only)

- Saved on demand and after cleanup/optimization/repair in `Documents\Favorable Odds\Odd$ Tune Reports` as `.json` and `.html` (plus a `.txt` log for maintenance).
- Contents: version, timestamp, Windows version/build, CPU, RAM, disk used/free, drive media type, categories (eligible found, recovered,
  files, skipped: recent / in use or denied / linked / other), free space before/after, Recycle Bin result, operation results and exit codes.
- Not recorded: computer name, user name (paths are shortened to `%LOCALAPPDATA%` and similar). Reports are never uploaded.

## Privacy

No network code (enforced by a test that fails the build if a networking module is imported). No telemetry, accounts or auto-update.
The only outside contact is the optional "open the web page" button, which launches your default browser. DISM, when you run repair,
is a Windows component that may use Windows Update.

## Build

Official builds come from GitHub Actions (`.github/workflows/build-odds-tune.yml`): validate (compile + tests on Windows and Linux) then
PyInstaller on a Windows x64 runner, a real-EXE smoke test (`OddsTune.exe --self-test`), optional signing, **then** SHA-256, then an artifact.

Local build (Windows 11 x64, Python 3.12 x64):

```bat
cd desktop\odds-tune
build_windows.bat
```

which is equivalent to

```bat
py -3.12 -m venv .venv && .venv\Scripts\activate
pip install -r requirements-build.txt
python -m unittest discover -s tests -v
pyinstaller --noconfirm --clean --onefile --windowed --name OddsTune --version-file version_info.txt --icon odds_tune.ico --add-data "odds_tune.ico;." odds_tune.py
```

PyInstaller is pinned in `requirements-build.txt`; `--windowed` hides the console; UPX is not used (it increases antivirus false positives).
Run tests anywhere (GUI tests skip without a display): `cd desktop/odds-tune && python -m unittest discover -s tests -v`.

## Code signing and releases

See [docs/SIGNING.md](docs/SIGNING.md) and [docs/RELEASE.md](docs/RELEASE.md). The current build is **unsigned**; the SHA-256 shown on the
website is that of the exact file served. If signing is added later, the hash must be recomputed after signing.

Verify a download: `Get-FileHash .\OddsTune.exe -Algorithm SHA256` (PowerShell) or `certutil -hashfile OddsTune.exe SHA256`.

## Known limitations

- Unsigned: Windows SmartScreen / antivirus may warn. Signing is a pre-launch recommendation.
- Not yet verified by hand on physical Windows 11/10 machines (automated tests and the EXE smoke test run on a Windows runner).
- The Recycle Bin option affects the Windows drive's bin only. The pending-restart check and the startup count are informational heuristics.
- SFC result wording is matched on English Windows; on other languages only the exit code and the log are shown.
- Very large temp folders can make a scan take a while. The window stays responsive.
- Cleaning `Windows\Temp` and WER needs Administrator rights.
