"""Odd$ Tune - safe Windows cleanup, maintenance and repair (GUI entry point).

Command line (all optional; the normal way to run is to double-click):
  --task optimize|repair    Elevated worker mode. Started by the main window after the user approves the UAC prompt.
  --self-test <file.json>   Headless smoke test used by the build pipeline. Scans (read-only), builds the window, exits.
  --version                 Print the version (console builds only).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import platform
import queue
import shutil
import sys
import threading
import traceback
import webbrowser
from pathlib import Path
from tkinter import BooleanVar, Listbox, StringVar, Text, Tk, messagebox
from tkinter import ttk

import odds_tune_core as core
from odds_tune_core import APP_NAME, APP_VERSION, PUBLISHER, WEBSITE, bytes_readable

# Brand palette
INK = "#0d0d0f"
PANEL = "#16171a"
PANEL_2 = "#202126"
IVORY = "#f5f1e8"
MUTED = "#aaa69c"
BRONZE = "#c8963c"
GREEN = "#66c983"
BLUE = "#6ca7ff"
RED = "#db6a5d"


def resource_path(name: str) -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / name


def apply_icon(root: Tk) -> None:
    try:
        ico = resource_path("odds_tune.ico")
        if ico.is_file() and core.is_windows():
            root.iconbitmap(default=str(ico))
    except Exception:
        pass


def configure_style() -> None:
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure("Root.TFrame", background=INK)
    style.configure("Panel.TFrame", background=PANEL)
    style.configure("Panel2.TFrame", background=PANEL_2)
    style.configure("Title.TLabel", background=INK, foreground=IVORY, font=("Segoe UI Semibold", 24))
    style.configure("Sub.TLabel", background=INK, foreground=MUTED, font=("Segoe UI", 10))
    style.configure("Good.TLabel", background=INK, foreground=GREEN, font=("Segoe UI", 10))
    style.configure("H2.TLabel", background=PANEL, foreground=IVORY, font=("Segoe UI Semibold", 14))
    style.configure("Body.TLabel", background=PANEL, foreground=MUTED, font=("Segoe UI", 10))
    style.configure("MetricTitle.TLabel", background=PANEL_2, foreground=MUTED, font=("Segoe UI", 9))
    style.configure("Metric.TLabel", background=PANEL_2, foreground=IVORY, font=("Segoe UI Semibold", 12))
    style.configure("Status.TLabel", background=INK, foreground=MUTED, font=("Consolas", 9))
    style.configure("Safe.TLabel", background=PANEL_2, foreground=GREEN, font=("Segoe UI Semibold", 8))
    style.configure("Change.TLabel", background=PANEL_2, foreground=BRONZE, font=("Segoe UI Semibold", 8))
    style.configure("Warn.TLabel", background=PANEL_2, foreground=RED, font=("Segoe UI Semibold", 8))
    style.configure("TCheckbutton", background=PANEL_2, foreground=IVORY, font=("Segoe UI", 10))
    style.map("TCheckbutton", background=[("active", PANEL_2)], foreground=[("active", IVORY), ("disabled", MUTED)])
    style.configure("Primary.TButton", font=("Segoe UI Semibold", 11), padding=(18, 11), background=BRONZE, foreground=INK)
    style.map("Primary.TButton", background=[("active", "#ddb25d"), ("disabled", "#6d603f")], foreground=[("disabled", "#2a2a2a")])
    style.configure("Secondary.TButton", font=("Segoe UI Semibold", 10), padding=(12, 9), background="#2a2c33", foreground=IVORY)
    style.map("Secondary.TButton", background=[("active", "#383a44"), ("disabled", "#1c1d22")], foreground=[("disabled", MUTED)])
    style.configure("Danger.TButton", font=("Segoe UI Semibold", 10), padding=(12, 9), background="#6c2f2a", foreground=IVORY)
    style.map("Danger.TButton", background=[("active", "#874038")])
    style.configure("Horizontal.TProgressbar", troughcolor=PANEL_2, background=BRONZE, bordercolor=PANEL_2,
                    lightcolor=BRONZE, darkcolor=BRONZE)
    style.configure("TNotebook", background=INK, borderwidth=0)
    style.configure("TNotebook.Tab", background=PANEL_2, foreground=MUTED, padding=(14, 8), font=("Segoe UI Semibold", 10))
    style.map("TNotebook.Tab", background=[("selected", PANEL)], foreground=[("selected", IVORY)])


class OddTuneApp:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        self.root.geometry("1000x780")
        self.root.minsize(880, 700)
        self.root.configure(bg=INK)
        apply_icon(root)
        self.categories = core.build_categories()
        self.snapshot: core.HealthSnapshot | None = None
        self.scan_complete = False
        self.busy = False
        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.recycle_var = BooleanVar(value=False)
        self.category_vars = {c.key: BooleanVar(value=c.default_selected and c.available) for c in self.categories}
        self.status_var = StringVar(value="Ready. Scan your PC first. Scanning does not change anything.")
        self.metric_vars = {k: StringVar(value="Not scanned") for k in ("windows", "disk", "cleanable", "restart", "drive")}
        self.category_size_vars = {c.key: StringVar(value="Not scanned") for c in self.categories}
        self.recycle_size_var = StringVar(value="Not scanned")
        configure_style()
        self._build_ui()
        self.root.after(100, self._poll)

    # ------------------------------------------------------------------ layout
    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, style="Root.TFrame", padding=22)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer, style="Root.TFrame")
        header.pack(fill="x")
        left = ttk.Frame(header, style="Root.TFrame")
        left.pack(side="left", fill="x", expand=True)
        ttk.Label(left, text="ODD$ TUNE", style="Title.TLabel").pack(anchor="w")
        ttk.Label(left, text="Safe Windows cleanup, maintenance and repair.", style="Sub.TLabel").pack(anchor="w", pady=(2, 0))
        ttk.Label(left, text="Local-only  ·  No telemetry  ·  No account  ·  Nothing is uploaded", style="Good.TLabel").pack(anchor="w", pady=(4, 0))
        right = ttk.Frame(header, style="Root.TFrame")
        right.pack(side="right", anchor="n")
        self.access_var = StringVar(value="Administrator" if core.is_admin() else "Standard access")
        ttk.Label(right, textvariable=self.access_var, style="Sub.TLabel").pack(anchor="e")
        ttk.Label(right, text=f"Version {APP_VERSION}", style="Sub.TLabel").pack(anchor="e")

        step = ttk.Frame(outer, style="Panel.TFrame", padding=(16, 12))
        step.pack(fill="x", pady=(16, 10))
        self.scan_btn = ttk.Button(step, text="SCAN MY PC", style="Primary.TButton", command=self.start_scan)
        self.scan_btn.pack(side="left")
        ttk.Label(step, text="Step 1  ·  Read-only. Looks at your PC and shows what could be cleaned. Nothing is changed or deleted.",
                  style="Body.TLabel", wraplength=640).pack(side="left", padx=14)
        self.admin_btn = ttk.Button(step, text="Restart as Administrator…", style="Secondary.TButton", command=self.restart_admin)
        self.admin_btn.pack(side="right")

        metrics = ttk.Frame(outer, style="Root.TFrame")
        metrics.pack(fill="x", pady=(0, 10))
        for i, (title, key) in enumerate([("WINDOWS", "windows"), ("SYSTEM DRIVE", "drive"), ("DISK FREE", "disk"),
                                           ("SAFE CLEANUP FOUND", "cleanable"), ("RESTART", "restart")]):
            card = ttk.Frame(metrics, style="Panel2.TFrame", padding=12)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 4, 0 if i == 4 else 4))
            metrics.columnconfigure(i, weight=1, uniform="m")
            ttk.Label(card, text=title, style="MetricTitle.TLabel").pack(anchor="w")
            ttk.Label(card, textvariable=self.metric_vars[key], style="Metric.TLabel", wraplength=160).pack(anchor="w", pady=(3, 0))

        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)
        tabs = {name: ttk.Frame(notebook, style="Panel.TFrame", padding=16)
                for name in ("Safe Cleanup", "Maintenance", "Reports", "Trust & Privacy")}
        for name, frame in tabs.items():
            notebook.add(frame, text=name)
        self._build_cleanup(tabs["Safe Cleanup"])
        self._build_maintenance(tabs["Maintenance"])
        self._build_reports(tabs["Reports"])
        self._build_trust(tabs["Trust & Privacy"])

        self.progress = ttk.Progressbar(outer, mode="indeterminate")
        self.progress.pack(fill="x", pady=(12, 4))
        ttk.Label(outer, textvariable=self.status_var, style="Status.TLabel", wraplength=940).pack(fill="x")

    def _build_cleanup(self, tab) -> None:
        ttk.Label(tab, text="Safe Cleanup", style="H2.TLabel").pack(anchor="w")
        ttk.Label(tab, text="Step 2  ·  Review. Step 3  ·  Choose. Only the allowlisted locations below are ever touched, "
                            "and recent files are always left alone.", style="Body.TLabel", wraplength=900).pack(anchor="w", pady=(4, 10))
        for c in self.categories:
            row = ttk.Frame(tab, style="Panel2.TFrame", padding=(12, 9))
            row.pack(fill="x", pady=3)
            label = c.name + ("  ·  needs Administrator" if c.requires_admin else "")
            ttk.Checkbutton(row, text=label, variable=self.category_vars[c.key],
                            state="normal" if c.available else "disabled").pack(side="left", anchor="n")
            desc = c.description if c.available else f"Not available: {c.unavailable_reason}"
            if c.notes:
                desc += "  " + " ".join(c.notes)
            ttk.Label(row, text=desc, style="MetricTitle.TLabel", wraplength=520).pack(side="left", padx=12, fill="x", expand=True)
            ttk.Label(row, textvariable=self.category_size_vars[c.key], style="Metric.TLabel").pack(side="right")

        rb = ttk.Frame(tab, style="Panel2.TFrame", padding=(12, 9))
        rb.pack(fill="x", pady=3)
        ttk.Checkbutton(rb, text="Empty Recycle Bin  ·  your choice", variable=self.recycle_var).pack(side="left")
        ttk.Label(rb, text="Permanently deletes what is already in the Recycle Bin of your Windows drive. Off unless you tick it.",
                  style="MetricTitle.TLabel", wraplength=520).pack(side="left", padx=12, fill="x", expand=True)
        ttk.Label(rb, textvariable=self.recycle_size_var, style="Metric.TLabel").pack(side="right")

        actions = ttk.Frame(tab, style="Panel.TFrame")
        actions.pack(fill="x", pady=(14, 0))
        self.clean_btn = ttk.Button(actions, text="Run Selected Safe Cleanup", style="Primary.TButton",
                                    command=self.confirm_clean, state="disabled")
        self.clean_btn.pack(side="left")
        ttk.Label(actions, text="CHANGES YOUR PC. Asks you to confirm first, then saves a before/after report on this computer.",
                  style="Body.TLabel", wraplength=640).pack(side="left", padx=12)

    def _maintenance_card(self, parent, title, badge, badge_style, body, button_text, command, danger=False) -> ttk.Button:
        card = ttk.Frame(parent, style="Panel2.TFrame", padding=14)
        card.pack(fill="x", pady=5)
        text = ttk.Frame(card, style="Panel2.TFrame")
        text.pack(side="left", fill="x", expand=True)
        ttk.Label(text, text=title, style="Metric.TLabel").pack(anchor="w")
        ttk.Label(text, text=badge, style=badge_style).pack(anchor="w", pady=(2, 0))
        ttk.Label(text, text=body, style="MetricTitle.TLabel", wraplength=660).pack(anchor="w", pady=(4, 0))
        btn = ttk.Button(card, text=button_text, style="Danger.TButton" if danger else "Secondary.TButton", command=command)
        btn.pack(side="right", padx=(12, 0))
        return btn

    def _build_maintenance(self, tab) -> None:
        ttk.Label(tab, text="Maintenance and repair", style="H2.TLabel").pack(anchor="w")
        ttk.Label(tab, text="These use tools built into Windows. Odd$ Tune never disables services or startup programs and never edits "
                            "the registry for speed. Cleanup and repair are separate: repair is for Windows problems, not for speed.",
                  style="Body.TLabel", wraplength=900).pack(anchor="w", pady=(4, 10))
        self.tools_var = StringVar(value="Run a scan to check which Windows tools are available on this PC.")
        ttk.Label(tab, textvariable=self.tools_var, style="Body.TLabel", wraplength=900).pack(anchor="w", pady=(0, 6))
        self._maintenance_card(tab, "Review Startup Apps", "READ-ONLY  ·  opens Windows Settings", "Safe.TLabel",
                               "Opens Windows' Startup Apps page so you decide what runs at sign-in. Odd$ Tune never turns startup programs off for you.",
                               "Review Startup Apps", self.review_startup)
        self.optimize_btn = self._maintenance_card(
            tab, "Optimize System Drive", "CHANGES YOUR PC  ·  needs Administrator", "Change.TLabel",
            "Runs Windows' own  defrag <drive> /O.  Windows picks the right action for the drive type: retrim for an SSD, "
            "defragmentation for a hard disk.", "Optimize Drive…", self.optimize_drive)
        self.repair_btn = self._maintenance_card(
            tab, "Advanced Windows Repair", "REPAIR  ·  CHANGES YOUR PC  ·  needs Administrator", "Warn.TLabel",
            "Runs DISM /Online /Cleanup-Image /RestoreHealth, then System File Checker (sfc /scannow). Use it for Windows errors, "
            "crashes or corruption, not as a speed boost. It can take a long time and DISM may use Windows Update.",
            "Run DISM + SFC…", self.repair_windows, danger=True)

    def _build_reports(self, tab) -> None:
        ttk.Label(tab, text="Reports", style="H2.TLabel").pack(anchor="w")
        ttk.Label(tab, text="Reports are plain HTML and JSON files saved on this computer. Nothing is uploaded. "
                            "They do not include your computer name or user name.", style="Body.TLabel", wraplength=900).pack(anchor="w", pady=(4, 10))
        bar = ttk.Frame(tab, style="Panel.TFrame")
        bar.pack(fill="x")
        self.save_scan_btn = ttk.Button(bar, text="Save Scan Report", style="Secondary.TButton", command=self.save_scan_report, state="disabled")
        self.save_scan_btn.pack(side="left")
        ttk.Button(bar, text="Open Reports Folder", style="Secondary.TButton", command=self.open_reports).pack(side="left", padx=8)
        ttk.Button(bar, text="Refresh List", style="Secondary.TButton", command=self.refresh_reports).pack(side="left")
        self.reports_list = Listbox(tab, bg=PANEL_2, fg=IVORY, selectbackground=BRONZE, selectforeground=INK, bd=0,
                                    highlightthickness=0, font=("Consolas", 9), height=10)
        self.reports_list.pack(fill="both", expand=True, pady=(10, 0))
        self.reports_list.bind("<Double-Button-1>", self.open_selected_report)
        self._report_paths: list[Path] = []
        self.refresh_reports()

    def _build_trust(self, tab) -> None:
        ttk.Label(tab, text="Built to be inspectable", style="H2.TLabel").pack(anchor="w")
        text = (
            "• No telemetry, analytics, cloud API or upload code in this app.\n"
            "• Scan first. Scanning never deletes or writes anything.\n"
            "• Cleanup needs your explicit click, confirmation and category selection.\n"
            "• Only allowlisted Windows temp, cache and error-report folders are targeted.\n"
            "• Recent files are protected by age thresholds (48 hours, 72 hours or 7 days).\n"
            "• Symbolic links, junctions and other redirected folders are never followed.\n"
            "• No registry cleaner, RAM booster, service disabling, driver updater or browser-history wipe.\n"
            "• Administrator permission is requested only for system operations, and you can say No.\n"
            "• Reports stay on this PC unless you choose to share them.")
        ttk.Label(tab, text=text, style="Body.TLabel", justify="left", wraplength=900).pack(anchor="w", pady=(10, 14))
        ttk.Label(tab, text=f"Odd$ Tune v{APP_VERSION}  ·  {PUBLISHER}", style="Body.TLabel").pack(anchor="w")
        ttk.Button(tab, text="Open the Odd$ Tune web page (opens your browser)", style="Secondary.TButton",
                   command=lambda: webbrowser.open(WEBSITE)).pack(anchor="w", pady=(12, 0))

    # ------------------------------------------------------------------ events from worker threads
    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                getattr(self, f"_on_{kind}")(payload)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def set_busy(self, busy: bool, message: str) -> None:
        self.busy = busy
        self.status_var.set(message)
        if busy:
            self.progress.start(12)
            self.scan_btn.config(state="disabled")
            self.clean_btn.config(state="disabled")
        else:
            self.progress.stop()
            self.scan_btn.config(state="normal")
            self.clean_btn.config(state="normal" if self.scan_complete else "disabled")

    # ------------------------------------------------------------------ scan (read-only)
    def start_scan(self) -> None:
        if self.busy:
            return
        self.set_busy(True, "Scanning allowlisted locations and Windows facts (read-only)…")
        threading.Thread(target=self._scan_worker, daemon=True).start()

    def _scan_worker(self) -> None:
        try:
            snap = core.collect_snapshot(self.categories)
            self.events.put(("scan_done", snap))
        except Exception:
            self.events.put(("failed", ("Scan failed", traceback.format_exc(limit=3))))

    def _on_scan_done(self, snap: core.HealthSnapshot) -> None:
        self.snapshot = snap
        self.scan_complete = True
        self.metric_vars["windows"].set(f"{snap.windows}\nbuild {snap.build}, {snap.architecture}" if snap.build else snap.windows)
        self.metric_vars["drive"].set(f"{snap.system_drive}  {snap.drive_media}\n{snap.drive_bus}")
        self.metric_vars["disk"].set(f"{bytes_readable(snap.disk_free)}\nof {bytes_readable(snap.disk_total)}")
        self.metric_vars["cleanable"].set(f"{bytes_readable(snap.cleanable_bytes)}\n{snap.cleanable_files} files")
        self.metric_vars["restart"].set("Pending" if snap.pending_restart else "Not pending")
        self.recycle_size_var.set(f"{bytes_readable(snap.recycle_bin_bytes)} · {snap.recycle_bin_items} items")
        for c in self.categories:
            self.category_size_vars[c.key].set(f"{bytes_readable(c.estimate_bytes)} · {c.estimate_files} files" if c.available else "n/a")
        self.save_scan_btn.config(state="normal")
        t = snap.tools
        self.tools_var.set("Detected on this PC:  drive optimization (defrag) " + ("available" if t.get("defrag") else "NOT found") +
                           "  ·  DISM " + ("available" if t.get("dism") else "NOT found") +
                           "  ·  System File Checker " + ("available" if t.get("sfc") else "NOT found") +
                           ".  Optimization and repair need Administrator permission.")
        self.optimize_btn.config(state="normal" if t.get("defrag") or not core.is_windows() else "disabled")
        self.repair_btn.config(state="normal" if (t.get("dism") and t.get("sfc")) or not core.is_windows() else "disabled")
        note = "" if snap.support_tier == "primary" else f" {snap.support_note}"
        self.set_busy(False, f"Scan complete: {bytes_readable(snap.cleanable_bytes)} eligible across {snap.cleanable_files} files. "
                             f"Nothing was changed.{note}")

    def save_scan_report(self) -> None:
        if not self.snapshot:
            return
        try:
            report = core.build_report(self.snapshot, self.categories, "scan")
            _j, h = core.save_report(report)
        except OSError as exc:
            messagebox.showerror(APP_NAME, f"The report could not be saved: {core.redact(str(exc))}")
            return
        self.refresh_reports()
        self.status_var.set(f"Scan report saved: {core.redact(str(h))}")

    # ------------------------------------------------------------------ cleanup
    def confirm_clean(self) -> None:
        if not self.scan_complete or self.snapshot is None or self.busy:
            return
        selected = [c for c in self.categories if self.category_vars[c.key].get() and c.available]
        recycle = bool(self.recycle_var.get())
        if not selected and not recycle:
            messagebox.showinfo(APP_NAME, "Select at least one cleanup category.")
            return
        size = sum(c.estimate_bytes for c in selected) + (self.snapshot.recycle_bin_bytes if recycle else 0)
        names = "\n".join(f"  •  {c.name}" for c in selected) + ("\n  •  Recycle Bin (permanent)" if recycle else "")
        admin_note = ("\n\nSome selected system folders need Administrator access. Without it those files are skipped. "
                      "Use 'Restart as Administrator…' if you want them included."
                      if any(c.requires_admin for c in selected) and not core.is_admin() else "")
        if not messagebox.askyesno("Confirm Safe Cleanup",
                                   f"Odd$ Tune will try to remove about {bytes_readable(size)} from:\n\n{names}{admin_note}\n\n"
                                   "Recent files, locked files and anything outside these locations are left alone. Continue?"):
            return
        self.set_busy(True, "Running the selected cleanup…")
        keys = {c.key for c in selected}
        threading.Thread(target=self._clean_worker, args=(keys, recycle), daemon=True).start()

    def _clean_worker(self, keys: set[str], recycle: bool) -> None:   # values captured on the UI thread
        try:
            drive = core.system_drive()
            try:
                free_before = shutil.disk_usage(drive + "\\" if core.is_windows() else Path.home()).free
            except OSError:
                free_before = None
            core.clean_categories(self.categories, keys)
            result = core.empty_recycle_bin(drive) if recycle else None
            try:
                free_after = shutil.disk_usage(drive + "\\" if core.is_windows() else Path.home()).free
            except OSError:
                free_after = None
            assert self.snapshot is not None
            report = core.build_report(self.snapshot, self.categories, "cleanup", disk_free_before=free_before,
                                       disk_free_after=free_after, recycle_result=result)
            report_path, err = None, ""
            try:
                report_path = core.save_report(report)[1]
            except OSError as exc:
                err = core.redact(str(exc))
            self.events.put(("clean_done", (result, report_path, err, free_before, free_after)))
        except Exception:
            self.events.put(("failed", ("Cleanup failed", traceback.format_exc(limit=3))))

    def _on_clean_done(self, payload) -> None:
        result, report_path, err, free_before, free_after = payload
        removed = sum(c.stats.deleted_bytes for c in self.categories)
        files = sum(c.stats.deleted_files for c in self.categories)
        skipped = sum(c.stats.skipped_total for c in self.categories)
        in_use = sum(c.stats.skipped_locked for c in self.categories)
        self.scan_complete = False
        self.set_busy(False, f"Cleanup finished: {bytes_readable(removed)} removed from {files} files; {skipped} items skipped.")
        lines = [f"Removed {bytes_readable(removed)} from {files} files.",
                 f"Skipped {skipped} items (recent, in use or access denied: {in_use}). That is normal."]
        if free_before is not None and free_after is not None:
            lines.append(f"Free space: {bytes_readable(free_before)} → {bytes_readable(free_after)}.")
        if result is not None:
            lines.append(f"Recycle Bin: {result[1]}")
        lines.append(f"Report saved: {core.redact(str(report_path))}" if report_path else f"The report could not be saved ({err}).")
        lines.append("Run another scan to refresh the totals.")
        self.refresh_reports()
        messagebox.showinfo("Cleanup Complete", "\n\n".join(lines))

    # ------------------------------------------------------------------ elevation / maintenance
    def _explain_elevation(self, title: str, body: str) -> bool:
        return messagebox.askyesno(title, body + "\n\nWindows will ask for your permission first. If you choose No there, nothing starts.\n\nContinue?")

    def _handle_launch(self, outcome: str, what: str) -> None:
        if outcome == "started":
            self.status_var.set(f"{what} started in a separate Administrator window. Progress and a log appear there.")
        elif outcome == "denied":
            messagebox.showinfo(APP_NAME, f"Windows did not grant Administrator permission, so {what.lower()} was not started. Nothing was changed.")
        else:
            messagebox.showerror(APP_NAME, f"{what} could not be started.")

    def restart_admin(self) -> None:
        if core.is_admin():
            messagebox.showinfo(APP_NAME, "Odd$ Tune is already running with Administrator access.")
            return
        if not self._explain_elevation("Restart as Administrator",
                                       "Administrator access lets Odd$ Tune also clean the protected Windows Temp and Windows Error "
                                       "Reporting folders. Odd$ Tune will close and reopen."):
            return
        outcome = core.relaunch_as_admin()
        if outcome == "started":
            self.root.after(250, self.root.destroy)
        elif outcome == "denied":
            messagebox.showinfo(APP_NAME, "Windows did not grant Administrator permission. Odd$ Tune keeps running with standard access.")
        else:
            messagebox.showerror(APP_NAME, "Odd$ Tune could not restart with Administrator access.")

    def review_startup(self) -> None:
        core.open_startup_settings()
        self.status_var.set("Opened Windows Startup Apps. Odd$ Tune does not change anything there.")

    def optimize_drive(self) -> None:
        if not core.is_windows():
            return
        s = self.snapshot
        info = (f"System drive: {s.system_drive}\nDetected: {s.drive_media} ({s.drive_bus}), {s.drive_model}" if s
                else f"System drive: {core.system_drive()}\n(Run a scan first to see the drive type.)")
        if self._explain_elevation("Optimize System Drive",
                                   f"{info}\n\nWindows will run  defrag /O  and choose the right optimization for the drive "
                                   "(retrim for an SSD, defragmentation for a hard disk). This needs Administrator permission. "
                                   "A window shows progress and a log is saved in your Reports folder."):
            self._handle_launch(core.launch_elevated_task("optimize"), "Drive optimization")

    def repair_windows(self) -> None:
        if not core.is_windows():
            return
        if self._explain_elevation("Advanced Windows Repair",
                                   "This is a repair tool, not a speed boost. Use it if Windows shows errors, crashes or corruption.\n\n"
                                   "It runs, in order:\n  1. DISM /Online /Cleanup-Image /RestoreHealth\n  2. sfc /scannow\n\n"
                                   "It can take a long time and should not be interrupted. DISM may download replacement components "
                                   "through Windows Update. Needs Administrator permission."):
            self._handle_launch(core.launch_elevated_task("repair"), "Advanced Windows Repair")

    # ------------------------------------------------------------------ reports
    def refresh_reports(self) -> None:
        self._report_paths = core.list_reports()
        self.reports_list.delete(0, "end")
        for p in self._report_paths:
            self.reports_list.insert("end", p.name)
        if not self._report_paths:
            self.reports_list.insert("end", "No reports yet.")

    def open_selected_report(self, _event=None) -> None:
        sel = self.reports_list.curselection()
        if sel and sel[0] < len(self._report_paths) and core.is_windows():
            os.startfile(str(self._report_paths[sel[0]]))  # type: ignore[attr-defined]

    def open_reports(self) -> None:
        d = core.report_dir(create=True)
        if core.is_windows():
            os.startfile(str(d))  # type: ignore[attr-defined]
        else:
            webbrowser.open(d.as_uri())

    def _on_failed(self, payload) -> None:
        title, details = payload
        self.set_busy(False, title)
        messagebox.showerror(title, details)


# ======================================================================================================================
# Elevated worker window (defrag /O, or DISM then SFC). Shows live output and saves a log + report.
# ======================================================================================================================

class WorkerWindow:
    TITLES = {"optimize": "Drive optimization", "repair": "Advanced Windows Repair (DISM + SFC)"}

    def __init__(self, root: Tk, task: str):
        self.root, self.task = root, task
        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.running = True
        root.title(f"{APP_NAME} - {self.TITLES[task]}")
        root.geometry("860x560")
        root.configure(bg=INK)
        apply_icon(root)
        configure_style()
        frame = ttk.Frame(root, style="Root.TFrame", padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=self.TITLES[task], style="Title.TLabel").pack(anchor="w")
        ttk.Label(frame, text="Running with Administrator permission. Please keep this window open until it says Finished.",
                  style="Sub.TLabel").pack(anchor="w", pady=(2, 10))
        self.text = Text(frame, bg=PANEL, fg=IVORY, insertbackground=IVORY, font=("Consolas", 9), wrap="word", height=22, bd=0)
        self.text.pack(fill="both", expand=True)
        self.text.config(state="disabled")
        self.progress = ttk.Progressbar(frame, mode="indeterminate")
        self.progress.pack(fill="x", pady=(10, 4))
        self.progress.start(12)
        self.status = StringVar(value="Starting…")
        ttk.Label(frame, textvariable=self.status, style="Status.TLabel").pack(fill="x")
        self.close_btn = ttk.Button(frame, text="Close", style="Secondary.TButton", command=root.destroy, state="disabled")
        self.close_btn.pack(anchor="e", pady=(8, 0))
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        threading.Thread(target=self._work, daemon=True).start()
        root.after(100, self._poll)

    def on_close(self) -> None:
        if self.running:
            messagebox.showinfo(APP_NAME, "Please wait. This operation should not be interrupted.")
        else:
            self.root.destroy()

    def _append(self, line: str) -> None:
        self.text.config(state="normal")
        self.text.insert("end", line + "\n")
        self.text.see("end")
        self.text.config(state="disabled")

    def _work(self) -> None:
        log = None
        try:
            stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            try:
                core.report_dir(create=True)
                log = core.LogWriter(core.report_dir() / f"odds-tune-{self.task}_{stamp}.txt")
            except OSError:
                log = None
            if log is None or log._fh is None:
                self.events.put(("line", "(A log file could not be created in your Reports folder; output is shown here only.)"))
            records = core.run_maintenance_task(self.task, lambda text, prog: self.events.put(("progress" if prog else "line", text)), log)
            self.events.put(("line", "Saving report…"))
            snap = core.collect_snapshot([])
            report = core.build_report(snap, [], self.task, operations=records)
            try:
                core.save_report(report)
            except OSError:
                pass
            self.events.put(("done", records))
        except Exception:
            self.events.put(("line", "An unexpected error occurred:\n" + core.redact(traceback.format_exc(limit=3))))
            self.events.put(("done", []))
        finally:
            if log:
                log.close()

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "line":
                    self._append(payload)
                elif kind == "progress":
                    self.status.set(payload.strip()[:120])
                elif kind == "done":
                    self.running = False
                    self.progress.stop()
                    ok = bool(payload) and all(r.ok for r in payload)
                    self.status.set("Finished. " + ("All steps completed." if ok else "One or more steps reported a problem. See the output above."))
                    self.close_btn.config(state="normal")
        except queue.Empty:
            pass
        self.root.after(100, self._poll)


# ======================================================================================================================
# Entry points
# ======================================================================================================================

def run_self_test(out_path: str) -> int:
    """Headless smoke test for CI: read-only scan + build the real window. Never deletes anything."""
    result: dict = {"product": APP_NAME, "version": APP_VERSION, "frozen": bool(getattr(sys, "frozen", False)),
                    "python": platform.python_version(), "scan_ok": False, "gui_ok": False, "errors": []}
    try:
        cats = core.build_categories()
        snap = core.collect_snapshot(cats)
        result["scan_ok"] = True
        result["windows"] = f"{snap.windows} build {snap.build} {snap.architecture}"
        result["categories"] = [{"key": c.key, "available": c.available, "found_bytes": c.estimate_bytes} for c in cats]
        result["tools"] = snap.tools
    except Exception:
        result["errors"].append(traceback.format_exc(limit=4))
    try:
        root = Tk()
        root.withdraw()
        OddTuneApp(root)
        root.update_idletasks()
        root.update()
        root.destroy()
        result["gui_ok"] = True
    except Exception:
        result["errors"].append(traceback.format_exc(limit=4))
    Path(out_path).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0 if result["scan_ok"] and result["gui_ok"] else 1


def _arg_value(flag: str) -> str | None:
    argv = sys.argv[1:]
    return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else None


def main() -> int:
    argv = sys.argv[1:]
    if "--version" in argv:
        if sys.stdout:
            print(f"{APP_NAME} {APP_VERSION}")
        return 0
    if "--self-test" in argv:
        out = _arg_value("--self-test")
        return run_self_test(out) if out else 2
    if not core.is_windows():
        if sys.stdout:
            print(f"{APP_NAME} is a Windows utility (Windows 11 x64 primary, Windows 10 x64 best-effort).")
        return 2
    try:  # crisp text on high-DPI displays
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
    except Exception:
        pass
    root = Tk()
    task = _arg_value("--task")
    if "--task" in argv:
        if task not in core.TASKS or not core.is_admin():
            root.withdraw()
            messagebox.showerror(APP_NAME, "This operation must be started from the main Odd$ Tune window, "
                                           "with Administrator permission.")
            return 2
        WorkerWindow(root, task)
    else:
        OddTuneApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
