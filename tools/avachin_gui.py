#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Avachin Windows Preview GUI.

This first desktop shell is deliberately Preview-only. It consumes the public
Status and Operation APIs, keeps the organizer in its isolated subprocess and
contains no duplicate recognition or file-moving logic.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.avachin_operation import OperationEvent  # noqa: E402
from tools.gui_controller import PreviewController  # noqa: E402
from tools.version import AVACHIN_VERSION  # noqa: E402


def open_local_path(value: str | Path) -> None:
    path = Path(value).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class AvachinPreviewApp:
    def __init__(
        self,
        root: tk.Tk,
        *,
        controller: PreviewController | None = None,
        initial_folder: str = "",
        offline: bool = True,
    ) -> None:
        self.root = root
        self.controller = controller or PreviewController()
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.artifact_buttons: list[ttk.Button] = []

        self.folder_var = tk.StringVar(value=initial_folder)
        self.offline_var = tk.BooleanVar(value=offline)
        self.status_var = tk.StringVar(value="Ready")
        self.progress_text_var = tk.StringVar(value="No operation running")
        self.version_var = tk.StringVar(value=f"Avachin v{AVACHIN_VERSION}")

        self.root.title(f"Avachin v{AVACHIN_VERSION} — Preview")
        self.root.minsize(840, 610)
        self.root.geometry("980x720")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._load_status()
        self.root.after(100, self._drain_events)

    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("Subtle.TLabel", foreground="#555555")
        style.configure("Safety.TLabel", font=("Segoe UI", 10, "bold"))

        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x")
        ttk.Label(header, textvariable=self.version_var, style="Title.TLabel").pack(side="left")
        ttk.Label(
            header,
            text="PREVIEW ONLY — no music file will be moved or renamed",
            style="Safety.TLabel",
        ).pack(side="right", padx=(20, 0))

        ttk.Label(
            outer,
            text="Choose a music folder, inspect runtime readiness, and run the existing organizer safely.",
            style="Subtle.TLabel",
        ).pack(fill="x", pady=(4, 14))

        status_box = ttk.LabelFrame(outer, text="Runtime status", padding=12)
        status_box.pack(fill="x")
        self.status_grid = ttk.Frame(status_box)
        self.status_grid.pack(fill="x")
        self._status_labels: dict[str, ttk.Label] = {}
        status_items = (
            ("fpcalc", "Fingerprint tool"),
            ("ffmpeg", "Audio repair"),
            ("database", "Local database"),
            ("budget", "AudD budget"),
        )
        for column, (key, title) in enumerate(status_items):
            cell = ttk.Frame(self.status_grid, padding=(8, 2))
            cell.grid(row=0, column=column, sticky="nsew")
            self.status_grid.columnconfigure(column, weight=1)
            ttk.Label(cell, text=title, style="Subtle.TLabel").pack(anchor="w")
            label = ttk.Label(cell, text="Checking…", font=("Segoe UI", 10, "bold"))
            label.pack(anchor="w", pady=(3, 0))
            self._status_labels[key] = label
        ttk.Button(status_box, text="Refresh status", command=self._load_status).pack(anchor="e", pady=(8, 0))

        source_box = ttk.LabelFrame(outer, text="Music folder", padding=12)
        source_box.pack(fill="x", pady=(14, 0))
        folder_row = ttk.Frame(source_box)
        folder_row.pack(fill="x")
        self.folder_entry = ttk.Entry(folder_row, textvariable=self.folder_var)
        self.folder_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(folder_row, text="Browse…", command=self._browse_folder).pack(side="left", padx=(8, 0))
        ttk.Checkbutton(
            source_box,
            text="Offline mode (recommended: use local database only)",
            variable=self.offline_var,
        ).pack(anchor="w", pady=(10, 0))

        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(14, 0))
        self.start_button = ttk.Button(controls, text="Start Preview", command=self._start_preview)
        self.start_button.pack(side="left")
        self.cancel_button = ttk.Button(controls, text="Cancel", command=self._cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=(8, 0))
        ttk.Label(controls, textvariable=self.status_var).pack(side="right")

        progress_box = ttk.LabelFrame(outer, text="Progress", padding=12)
        progress_box.pack(fill="x", pady=(14, 0))
        self.progress = ttk.Progressbar(progress_box, mode="determinate", maximum=100)
        self.progress.pack(fill="x")
        ttk.Label(progress_box, textvariable=self.progress_text_var).pack(anchor="w", pady=(6, 0))

        artifact_box = ttk.LabelFrame(outer, text="Reports", padding=10)
        artifact_box.pack(fill="x", pady=(14, 0))
        self.artifact_frame = ttk.Frame(artifact_box)
        self.artifact_frame.pack(fill="x")
        self.no_artifact_label = ttk.Label(
            self.artifact_frame,
            text="Report links will appear here after Preview creates them.",
            style="Subtle.TLabel",
        )
        self.no_artifact_label.pack(anchor="w")

        log_box = ttk.LabelFrame(outer, text="Operation log", padding=8)
        log_box.pack(fill="both", expand=True, pady=(14, 0))
        self.log = ScrolledText(
            log_box,
            wrap="word",
            height=14,
            font=("Consolas", 9),
            state="disabled",
        )
        self.log.pack(fill="both", expand=True)

    def _set_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _load_status(self) -> None:
        try:
            status = self.controller.status()
        except Exception as exc:
            self.status_var.set("Status check failed")
            self._set_log(f"Status error: {exc}")
            return
        tools = status.get("tools") or {}
        fpcalc_ready = bool((tools.get("fpcalc") or {}).get("available"))
        ffmpeg_ready = bool((tools.get("ffmpeg") or {}).get("available"))
        fingerprints = status.get("fingerprints") or {}
        budget = status.get("audd_budget") or {}
        self._status_labels["fpcalc"].configure(text="Ready" if fpcalc_ready else "Missing")
        self._status_labels["ffmpeg"].configure(text="Ready" if ffmpeg_ready else "Missing")
        if fingerprints.get("exists") and not fingerprints.get("error"):
            self._status_labels["database"].configure(
                text=f"{fingerprints.get('recordings', 0)} recordings"
            )
        else:
            self._status_labels["database"].configure(text="Not ready")
        self._status_labels["budget"].configure(
            text=f"{budget.get('remaining', 0)} remaining"
        )
        warnings = status.get("warnings") or []
        self.status_var.set("Ready" if not warnings else f"Ready with {len(warnings)} warning(s)")
        for warning in warnings:
            self._set_log(f"Warning: {warning}")

    def _browse_folder(self) -> None:
        initial = self.folder_var.get().strip()
        selected = filedialog.askdirectory(
            title="Choose music folder",
            initialdir=initial if Path(initial).is_dir() else str(Path.home()),
        )
        if selected:
            self.folder_var.set(selected)

    def _reset_artifacts(self) -> None:
        for button in self.artifact_buttons:
            button.destroy()
        self.artifact_buttons.clear()
        self.no_artifact_label.pack(anchor="w")

    def _add_artifact(self, key: str, path: str) -> None:
        self.no_artifact_label.pack_forget()
        title = key.replace("_", " ").strip().title() or Path(path).name
        button = ttk.Button(
            self.artifact_frame,
            text=f"Open {title}",
            command=lambda value=path: self._open_path(value),
        )
        button.pack(side="left", padx=(0, 8), pady=2)
        self.artifact_buttons.append(button)
        parent = str(Path(path).expanduser().resolve().parent)
        if not any(str(item.cget("text")) == "Open Reports Folder" for item in self.artifact_buttons):
            folder_button = ttk.Button(
                self.artifact_frame,
                text="Open Reports Folder",
                command=lambda value=parent: self._open_path(value),
            )
            folder_button.pack(side="left", padx=(0, 8), pady=2)
            self.artifact_buttons.append(folder_button)

    def _open_path(self, value: str) -> None:
        try:
            open_local_path(value)
        except Exception as exc:
            messagebox.showerror("Could not open path", str(exc), parent=self.root)

    def _start_preview(self) -> None:
        folder = self.folder_var.get().strip()
        if not folder:
            messagebox.showwarning("Choose a folder", "Select the music folder first.", parent=self.root)
            return
        self._clear_log()
        self._reset_artifacts()
        self.progress.configure(value=0, mode="determinate", maximum=100)
        self.progress_text_var.set("Starting Preview…")
        self.status_var.set("Running")
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.folder_entry.configure(state="disabled")
        try:
            self.controller.start_preview(
                folder,
                offline=self.offline_var.get(),
                event_callback=lambda event: self.events.put(("event", event)),
                completion_callback=lambda result: self.events.put(("completed", result)),
            )
        except Exception as exc:
            self._finish_controls()
            messagebox.showerror("Preview could not start", str(exc), parent=self.root)

    def _cancel(self) -> None:
        if self.controller.cancel():
            self.status_var.set("Cancelling…")
            self.cancel_button.configure(state="disabled")
            self._set_log("Cancellation requested. Avachin is stopping the isolated process safely.")

    def _handle_event(self, event: OperationEvent) -> None:
        if event.event_type == "artifact" and event.path:
            self._add_artifact(event.key, event.path)
        if event.current is not None and event.total:
            percent = max(0.0, min(100.0, event.current / event.total * 100.0))
            self.progress.configure(mode="determinate", maximum=100, value=percent)
            self.progress_text_var.set(
                f"{event.phase or event.event_type}: {event.current}/{event.total}"
            )
        elif event.event_type == "phase":
            self.progress_text_var.set(event.message or event.phase or "Working…")
        if event.message and event.event_type in {
            "phase",
            "progress",
            "warning",
            "error",
            "audio-repair",
            "summary",
            "started",
            "cancelling",
            "cancelled",
            "completed",
            "failed",
        }:
            self._set_log(f"[{event.event_type}] {event.message}")

    def _handle_completed(self, result: dict[str, Any]) -> None:
        status = str(result.get("status") or "failed")
        self.status_var.set(status.replace("-", " ").title())
        if status == "completed":
            self.progress.configure(value=100)
            self.progress_text_var.set("Preview completed. Review the reports before any future Apply action.")
        elif status == "cancelled":
            self.progress_text_var.set("Preview cancelled safely.")
        else:
            message = str(result.get("error") or "Preview failed. See the operation log.")
            self.progress_text_var.set(message)
        self._finish_controls()

    def _finish_controls(self) -> None:
        self.start_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.folder_entry.configure(state="normal")

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "event":
                    self._handle_event(payload)
                else:
                    self._handle_completed(payload)
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)

    def _on_close(self) -> None:
        if self.controller.running:
            close = messagebox.askyesno(
                "Preview is running",
                "Cancel the running Preview and close Avachin?",
                parent=self.root,
            )
            if not close:
                return
            self.controller.cancel()
        self.root.destroy()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch the Avachin Preview-only Windows GUI. Apply is intentionally unavailable."
    )
    parser.add_argument("--folder", default="", help="Optional initial music folder")
    parser.add_argument(
        "--online",
        action="store_true",
        help="Allow configured online providers; the GUI defaults to offline mode.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Print Status API JSON without opening a window.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    controller = PreviewController()
    if args.check:
        print(json.dumps(controller.status(), ensure_ascii=False, indent=2))
        return 0
    root = tk.Tk()
    AvachinPreviewApp(
        root,
        controller=controller,
        initial_folder=args.folder,
        offline=not args.online,
    )
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
