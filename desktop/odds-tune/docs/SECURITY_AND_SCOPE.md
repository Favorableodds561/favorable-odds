# Odd$ Tune security and scope

## Cleanup allowlist (the only things the cleaner can touch)

`%LOCALAPPDATA%\Temp` (48 h), your validated `TEMP` folder (48 h), `%LOCALAPPDATA%\CrashDumps` (7 d), `%LOCALAPPDATA%\D3DSCache` (7 d),
`%WINDIR%\Temp` (72 h), `%PROGRAMDATA%\Microsoft\Windows\WER\ReportQueue` and `\ReportArchive` (7 d), and the Windows drive's Recycle Bin
**only when ticked**. Each root is built from a trusted base (the base must itself look right, e.g. `...\AppData\Local`, `...\Windows`,
`...\ProgramData`), then passes a final gate: it must be absolute, not a drive root, and not inside a personal or program folder.

## Defences in the cleaner (`odds_tune_core.py`)

| Risk | Defence | Test |
|---|---|---|
| Environment variable (`TEMP`, `LOCALAPPDATA`) points somewhere dangerous | Trusted-base checks + final root gate; unusable roots become "not available" | `RootValidation` |
| Symlink / junction / reparse point inside a root | Any reparse attribute or symlink is skipped; directory re-checked right before listing | `LinkProtection` |
| Root itself redirected | Root is refused (scan and clean) | `test_root_that_is_*` |
| Redirect or race while walking | Each directory's real path must stay inside the root's real path | `test_directory_redirected_outside_root_is_not_entered` |
| Deleting something recent / just installed | Age = later of modified and creation time; file re-checked immediately before delete | `AgeProtection` |
| Deleting our own running files | The PyInstaller extraction folder is excluded | `test_own_pyinstaller_extraction_folder_is_protected` |
| Locked, read-only, denied, vanished files | Skipped and counted; read-only flag cleared only for an eligible old file; never aborts the run | `MissingEmptyAndFailures` |
| Fresh empty folders removed under a running app | Folders removed only if they were old before the run; never the root | `test_empty_root_and_empty_folders` |
| Scan modifying the PC | One shared read-only traversal; no process is launched during a scan (not even PowerShell, which writes its own caches); tests forbid every modifying API and compare the tree before/after | `ScanIsReadOnly` |

## Elevation

Elevated work (drive optimization, DISM, SFC) runs in a second instance of Odd$ Tune itself (`--task optimize|repair`), started with
`ShellExecute runas`. Only a fixed task name is passed. There is **no** script file in a user-writable folder, **no** `-EncodedCommand`
and **no** `-ExecutionPolicy Bypass`. Tools are launched by absolute path under `%SystemRoot%\System32` with `shell=False`. Logs and
reports are created exclusively (never overwrite) and refused if the reports folder or its parent is a link.

## Privacy

No networking or telemetry modules (test-enforced), no accounts, no auto-update, no hidden requests. Reports omit computer and user names.
The web-page button launches the default browser only when clicked.

## Explicit non-goals

Registry cleaning, RAM boosting, service/task disabling, automatic startup disabling, driver updating, browser data cleaning, Prefetch,
SoftwareDistribution, WinSxS, uninstalling software, power-plan/pagefile/DNS changes, telemetry, advertising, background services.
