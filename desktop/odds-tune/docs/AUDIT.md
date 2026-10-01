# Audit of the supplied "Odd$ Tune v1.0 Build Package" and what was changed

The package's cleanup design (allowlist, age thresholds, scan-first, `defrag /O`, DISM then SFC, local reports) was kept. These problems were
found and fixed rather than preserved.

| # | Severity | Finding in the supplied package | Fix |
|---|---|---|---|
| 1 | High | Cleanup roots came straight from `TEMP` / `LOCALAPPDATA`. A mis-set `TEMP` (drive root, Documents, home) would be walked and cleaned | Trusted-base checks, strict `TEMP` rules, final root gate; unusable roots are "not available" |
| 2 | High | Repair wrote a `.ps1` into `%LOCALAPPDATA%` and ran it **elevated**: any process running as the user could swap it and get admin (local privilege escalation) | Elevated worker mode (`--task`), fixed task names, no script file, no encoded command |
| 3 | High | Junction detection relied on `Path.is_junction` (Python 3.12+) and `DirEntry.is_symlink` does not report junctions; any reparse point other than a symlink was followed on older Python | Reparse-attribute + symlink check on every entry, re-verified before listing, plus real-path containment guard |
| 4 | Medium | Scan automatically wrote HTML/JSON reports and created folders under Documents (violates "scan must not modify the PC") | Scan writes nothing; reports are saved on demand/after actions |
| 5 | Medium | Age used modified time only; installer-extracted files keep old mtimes | Age is the later of modified and creation time; re-checked right before deleting |
| 6 | Medium | Empty sub-folders were removed with no age check (could remove a folder an app just created) | Removed only if old before the run; root never removed |
| 7 | Medium | Optimize/repair ran in a console that closed immediately; results were never captured | Worker window with live output, exit codes, interpreted results, log + report |
| 8 | Medium | `SHQUERYRBINFO` struct lacked 1-byte packing, so Recycle Bin size always read as 0 | `_pack_ = 1`, fixed-width `DWORD` types, size test |
| 9 | Medium | Tk variables were read from worker threads; drive detection ran on the UI thread (UI freeze) | Queue-based hand-off, values captured before threads start |
| 10 | Medium | Drive detection launched PowerShell (bare `powershell.exe`, needless `-ExecutionPolicy Bypass`, console flash) with the `SystemDrive` env value interpolated into the script. Found by the Windows CI run: PowerShell itself writes cache files under the user profile, so a "scan" was not strictly read-only | No process is launched during a scan. Drive type, bus and model come from a query-only storage IOCTL on the system drive (validated drive letter); PowerShell is no longer used anywhere |
| 11 | Low | Physical disk was matched by `FriendlyName` (wrong with two identical drives) | The query is made on the system drive's volume itself, so no matching is needed |
| 12 | Low | The app's own PyInstaller extraction folder (inside `%TEMP%`) was not excluded | Explicitly protected |
| 13 | Low | Reports/errors could contain `C:\Users\<name>\...` | Redaction of profile paths; no computer/user name recorded |
| 14 | Low | Only 2 tests existed while the notes claimed broad validation; workflow ran tests only on one OS, hashed nothing after signing | 76 tests, Windows + Linux validation, EXE smoke test, signing hook placed before hashing |
| 15 | Low | `$` and a space in the EXE name (`Odd$ Tune.exe`) break shells, URLs and CI quoting | `OddsTune.exe`, display name stays "Odd$ Tune" |
| 16 | Info | Support check treated Windows 10 as "legacy unsupported"; no architecture handling | Win11 x64 primary, Win10 x64 best effort, ARM64 flagged unsupported |
