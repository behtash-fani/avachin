#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Avachin Windows Review Center.

The window consumes ReviewController only. It never performs recognition, file
moves, retagging or direct SQLite writes. All corrections are backed up,
audited and undoable by the controller.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.review_controller import ReviewController  # noqa: E402
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


class ReviewCenterApp:
    def __init__(
        self,
        root: tk.Tk,
        *,
        controller: ReviewController | None = None,
        initial_report: str = "",
    ) -> None:
        self.root = root
        self.controller = controller or ReviewController()
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.queue_items: dict[str, dict[str, Any]] = {}
        self.recordings: dict[str, dict[str, Any]] = {}
        self.audio_items: dict[str, dict[str, Any]] = {}
        self.history_items: dict[str, dict[str, Any]] = {}

        self.status_var = tk.StringVar(value="Ready")
        self.report_var = tk.StringVar(value=initial_report)
        self.queue_count_var = tk.StringVar(value="No report loaded")
        self.search_var = tk.StringVar()
        self.recording_status_var = tk.StringVar(value="")
        self.artist_var = tk.StringVar()
        self.title_var = tk.StringVar()
        self.album_var = tk.StringVar()
        self.reason_var = tk.StringVar(value="manual identity correction")
        self.merge_target_var = tk.StringVar()

        self.root.title(f"Avachin v{AVACHIN_VERSION} — Review Center")
        self.root.geometry("1180x790")
        self.root.minsize(980, 680)
        self._build_ui()
        self.root.after(100, self._drain_events)
        self.refresh_queue()
        self.refresh_recordings()
        self.refresh_history()

    def _build_ui(self) -> None:
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("Safe.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("Subtle.TLabel", foreground="#555555")

        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer)
        header.pack(fill="x")
        ttk.Label(header, text=f"Avachin v{AVACHIN_VERSION} Review Center", style="Title.TLabel").pack(side="left")
        ttk.Label(
            header,
            text="BACKUP + AUDIT + UNDO — audio files are never moved or deleted",
            style="Safe.TLabel",
        ).pack(side="right")
        ttk.Label(
            outer,
            text="Inspect uncertain results and correct the local acoustic memory before Apply is enabled.",
            style="Subtle.TLabel",
        ).pack(fill="x", pady=(4, 10))

        self.tabs = ttk.Notebook(outer)
        self.tabs.pack(fill="both", expand=True)
        self.queue_tab = ttk.Frame(self.tabs, padding=10)
        self.database_tab = ttk.Frame(self.tabs, padding=10)
        self.history_tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(self.queue_tab, text="Review Queue")
        self.tabs.add(self.database_tab, text="Local Database")
        self.tabs.add(self.history_tab, text="Audit & Undo")
        self._build_queue_tab()
        self._build_database_tab()
        self._build_history_tab()

        status = ttk.Frame(outer)
        status.pack(fill="x", pady=(8, 0))
        ttk.Label(status, textvariable=self.status_var).pack(side="left")
        ttk.Button(status, text="Open Review Backups", command=self._open_backup_folder).pack(side="right")

    def _build_queue_tab(self) -> None:
        report_box = ttk.LabelFrame(self.queue_tab, text="Detection report", padding=8)
        report_box.pack(fill="x")
        ttk.Entry(report_box, textvariable=self.report_var).pack(side="left", fill="x", expand=True)
        ttk.Button(report_box, text="Browse…", command=self._browse_report).pack(side="left", padx=(8, 0))
        ttk.Button(report_box, text="Refresh", command=self.refresh_queue).pack(side="left", padx=(8, 0))
        ttk.Label(report_box, textvariable=self.queue_count_var).pack(side="right", padx=(12, 0))

        content = ttk.Panedwindow(self.queue_tab, orient="vertical")
        content.pack(fill="both", expand=True, pady=(10, 0))
        upper = ttk.Frame(content)
        lower = ttk.Frame(content)
        content.add(upper, weight=3)
        content.add(lower, weight=2)

        columns = ("decision", "artist", "title", "confidence", "provider", "reason", "path")
        self.queue_tree = ttk.Treeview(upper, columns=columns, show="headings", selectmode="browse")
        widths = {"decision": 80, "artist": 150, "title": 180, "confidence": 80, "provider": 110, "reason": 210, "path": 340}
        for column in columns:
            self.queue_tree.heading(column, text=column.replace("_", " ").title())
            self.queue_tree.column(column, width=widths[column], anchor="w")
        scroll = ttk.Scrollbar(upper, orient="vertical", command=self.queue_tree.yview)
        self.queue_tree.configure(yscrollcommand=scroll.set)
        self.queue_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.queue_tree.bind("<<TreeviewSelect>>", self._queue_selected)

        actions = ttk.Frame(lower)
        actions.pack(fill="x")
        ttk.Button(actions, text="Play selected file", command=self._play_queue_file).pack(side="left")
        ttk.Button(actions, text="Find current DB association", command=self._find_queue_association).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Apply verified identity", command=self._apply_queue_identity).pack(side="right")
        self._build_identity_form(lower)

    def _build_identity_form(self, parent: ttk.Frame) -> None:
        form = ttk.LabelFrame(parent, text="Verified identity", padding=8)
        form.pack(fill="x", pady=(8, 0))
        fields = (
            ("Artist", self.artist_var, 0),
            ("Title", self.title_var, 1),
            ("Album", self.album_var, 2),
        )
        for label, variable, column in fields:
            cell = ttk.Frame(form)
            cell.grid(row=0, column=column, sticky="ew", padx=(0, 8) if column < 2 else 0)
            form.columnconfigure(column, weight=1)
            ttk.Label(cell, text=label).pack(anchor="w")
            ttk.Entry(cell, textvariable=variable).pack(fill="x")
        ttk.Label(form, text="Reason").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(form, textvariable=self.reason_var).grid(row=2, column=0, columnspan=3, sticky="ew")

    def _build_database_tab(self) -> None:
        search_box = ttk.Frame(self.database_tab)
        search_box.pack(fill="x")
        ttk.Entry(search_box, textvariable=self.search_var).pack(side="left", fill="x", expand=True)
        status_combo = ttk.Combobox(
            search_box,
            textvariable=self.recording_status_var,
            values=("", "active", "revoked", "merged", "orphaned"),
            width=12,
            state="readonly",
        )
        status_combo.pack(side="left", padx=(8, 0))
        ttk.Button(search_box, text="Search", command=self.refresh_recordings).pack(side="left", padx=(8, 0))
        self.search_var.trace_add("write", lambda *_: None)

        pane = ttk.Panedwindow(self.database_tab, orient="horizontal")
        pane.pack(fill="both", expand=True, pady=(10, 0))
        left = ttk.Frame(pane)
        right = ttk.Frame(pane)
        pane.add(left, weight=2)
        pane.add(right, weight=3)

        rec_columns = ("status", "artist", "title", "album", "audio", "id")
        self.recording_tree = ttk.Treeview(left, columns=rec_columns, show="headings", selectmode="browse")
        rec_widths = {"status": 75, "artist": 145, "title": 170, "album": 150, "audio": 55, "id": 235}
        for column in rec_columns:
            self.recording_tree.heading(column, text=column.title())
            self.recording_tree.column(column, width=rec_widths[column], anchor="w")
        rec_scroll = ttk.Scrollbar(left, orient="vertical", command=self.recording_tree.yview)
        self.recording_tree.configure(yscrollcommand=rec_scroll.set)
        self.recording_tree.pack(side="left", fill="both", expand=True)
        rec_scroll.pack(side="right", fill="y")
        self.recording_tree.bind("<<TreeviewSelect>>", self._recording_selected)

        audio_box = ttk.LabelFrame(right, text="Physical audio encodings", padding=8)
        audio_box.pack(fill="both", expand=True)
        audio_columns = ("id", "duration", "fingerprints", "segments", "path")
        self.audio_tree = ttk.Treeview(audio_box, columns=audio_columns, show="headings", selectmode="browse", height=9)
        audio_widths = {"id": 55, "duration": 75, "fingerprints": 80, "segments": 70, "path": 470}
        for column in audio_columns:
            self.audio_tree.heading(column, text=column.title())
            self.audio_tree.column(column, width=audio_widths[column], anchor="w")
        self.audio_tree.pack(fill="both", expand=True)
        self.audio_tree.bind("<<TreeviewSelect>>", self._audio_selected)

        correction = ttk.LabelFrame(right, text="Correct selected audio", padding=8)
        correction.pack(fill="x", pady=(8, 0))
        row = ttk.Frame(correction)
        row.pack(fill="x")
        for label, variable in (("Artist", self.artist_var), ("Title", self.title_var), ("Album", self.album_var)):
            cell = ttk.Frame(row)
            cell.pack(side="left", fill="x", expand=True, padx=(0, 8))
            ttk.Label(cell, text=label).pack(anchor="w")
            ttk.Entry(cell, textvariable=variable).pack(fill="x")
        ttk.Label(correction, text="Reason").pack(anchor="w", pady=(6, 0))
        ttk.Entry(correction, textvariable=self.reason_var).pack(fill="x")
        buttons = ttk.Frame(correction)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Play audio", command=self._play_selected_audio).pack(side="left")
        ttk.Button(buttons, text="Reassign audio", command=self._reassign_selected_audio).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Revoke recording", command=self._revoke_selected_recording).pack(side="right")

        merge = ttk.LabelFrame(right, text="Merge duplicate recording", padding=8)
        merge.pack(fill="x", pady=(8, 0))
        ttk.Label(merge, text="Target recording ID").pack(anchor="w")
        merge_row = ttk.Frame(merge)
        merge_row.pack(fill="x")
        ttk.Entry(merge_row, textvariable=self.merge_target_var).pack(side="left", fill="x", expand=True)
        ttk.Button(merge_row, text="Merge selected into target", command=self._merge_selected_recording).pack(side="left", padx=(8, 0))

    def _build_history_tab(self) -> None:
        toolbar = ttk.Frame(self.history_tab)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Refresh", command=self.refresh_history).pack(side="left")
        ttk.Button(toolbar, text="Undo selected", command=self._undo_selected).pack(side="right")
        ttk.Button(toolbar, text="Undo latest applied action", command=self._undo_latest).pack(side="right", padx=(0, 8))

        columns = ("status", "type", "reviewer", "reason", "created", "source", "target", "id")
        self.history_tree = ttk.Treeview(self.history_tab, columns=columns, show="headings", selectmode="browse")
        widths = {"status": 70, "type": 125, "reviewer": 90, "reason": 220, "created": 150, "source": 170, "target": 170, "id": 220}
        for column in columns:
            self.history_tree.heading(column, text=column.title())
            self.history_tree.column(column, width=widths[column], anchor="w")
        self.history_tree.pack(fill="both", expand=True, pady=(10, 0))
        self.audit_log = ScrolledText(self.history_tab, height=9, font=("Consolas", 9), state="disabled")
        self.audit_log.pack(fill="x", pady=(8, 0))
        self.history_tree.bind("<<TreeviewSelect>>", self._history_selected)

    def _run(self, label: str, function: Callable[[], Any], callback: Callable[[Any], None] | None = None) -> None:
        self.status_var.set(label)

        def worker() -> None:
            try:
                result = function()
                self.events.put(("success", (result, callback)))
            except Exception as exc:
                self.events.put(("error", exc))

        threading.Thread(target=worker, name="avachin-review-worker", daemon=True).start()

    def _drain_events(self) -> None:
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "error":
                self.status_var.set("Operation failed")
                messagebox.showerror("Review operation failed", str(payload), parent=self.root)
            elif kind == "success":
                result, callback = payload
                self.status_var.set("Ready")
                if callback is not None:
                    callback(result)
        self.root.after(100, self._drain_events)

    def _browse_report(self) -> None:
        selected = filedialog.askopenfilename(
            title="Choose detection-report.json",
            filetypes=(("JSON", "*.json"), ("All files", "*.*")),
        )
        if selected:
            self.report_var.set(selected)
            self.refresh_queue()

    def refresh_queue(self) -> None:
        report = self.report_var.get().strip() or None
        self._run("Loading review queue…", lambda: self.controller.queue(report), self._show_queue)

    def _show_queue(self, result: dict[str, Any]) -> None:
        for item in self.queue_tree.get_children():
            self.queue_tree.delete(item)
        self.queue_items.clear()
        report_path = str(result.get("report_path") or "")
        if report_path:
            self.report_var.set(report_path)
        items = result.get("items") or []
        for index, item in enumerate(items):
            key = f"q-{index}"
            self.queue_items[key] = dict(item)
            self.queue_tree.insert(
                "",
                "end",
                iid=key,
                values=(
                    item.get("decision", ""),
                    item.get("artist", ""),
                    item.get("title", ""),
                    item.get("overall_confidence", ""),
                    item.get("provider", ""),
                    item.get("reason", ""),
                    item.get("source_path", ""),
                ),
            )
        self.queue_count_var.set(f"{len(items)} item(s) need attention")

    def _selected_queue_item(self) -> dict[str, Any] | None:
        selected = self.queue_tree.selection()
        return self.queue_items.get(selected[0]) if selected else None

    def _queue_selected(self, _event: Any = None) -> None:
        item = self._selected_queue_item()
        if not item:
            return
        self.artist_var.set(str(item.get("artist") or ""))
        self.title_var.set(str(item.get("title") or ""))
        self.album_var.set(str(item.get("album") or ""))
        self.reason_var.set(str(item.get("reason") or "human-reviewed identity"))

    def _play_queue_file(self) -> None:
        item = self._selected_queue_item()
        if item:
            self._open_path(str(item.get("source_path") or ""))

    def _find_queue_association(self) -> None:
        item = self._selected_queue_item()
        if not item:
            return
        path = str(item.get("source_path") or "")

        def show(rows: list[dict[str, Any]]) -> None:
            if not rows:
                messagebox.showinfo("No existing association", "This file is not yet stored in the local fingerprint database.", parent=self.root)
                return
            row = rows[0]
            self.search_var.set(str(row.get("recording_id") or ""))
            self.tabs.select(self.database_tab)
            self.refresh_recordings()

        self._run("Finding current association…", lambda: self.controller.find_path(path), show)

    def _apply_queue_identity(self) -> None:
        item = self._selected_queue_item()
        if not item:
            messagebox.showwarning("Select an item", "Select a REVIEW or REJECT item first.", parent=self.root)
            return
        path = str(item.get("source_path") or "")
        artist, title, album = self.artist_var.get(), self.title_var.get(), self.album_var.get()
        reason = self.reason_var.get()
        if not messagebox.askyesno(
            "Apply verified identity",
            f"Store this human-verified identity?\n\n{artist} — {title}\n{path}\n\nA backup and undo entry will be created.",
            parent=self.root,
        ):
            return

        def operation() -> dict[str, Any]:
            rows = self.controller.find_path(path)
            if rows:
                return self.controller.reassign(
                    int(rows[0]["id"]),
                    artist=artist,
                    title=title,
                    album=album,
                    reason=reason,
                )
            return self.controller.learn_rejected_file(
                path,
                artist=artist,
                title=title,
                album=album,
                reason=reason,
            )

        self._run("Applying verified identity…", operation, self._after_mutation)

    def refresh_recordings(self) -> None:
        query = self.search_var.get().strip()
        status = self.recording_status_var.get().strip()
        self._run("Searching local database…", lambda: self.controller.search(query, status=status), self._show_recordings)

    def _show_recordings(self, rows: list[dict[str, Any]]) -> None:
        for item in self.recording_tree.get_children():
            self.recording_tree.delete(item)
        self.recordings.clear()
        for row in rows:
            key = str(row["id"])
            self.recordings[key] = dict(row)
            self.recording_tree.insert(
                "",
                "end",
                iid=key,
                values=(row.get("status", ""), row.get("artist", ""), row.get("title", ""), row.get("album", ""), row.get("audio_files", 0), row.get("id", "")),
            )

    def _selected_recording_id(self) -> str:
        selected = self.recording_tree.selection()
        return selected[0] if selected else ""

    def _recording_selected(self, _event: Any = None) -> None:
        recording_id = self._selected_recording_id()
        if recording_id:
            self._run("Loading recording detail…", lambda: self.controller.detail(recording_id), self._show_recording_detail)

    def _show_recording_detail(self, detail: dict[str, Any]) -> None:
        for item in self.audio_tree.get_children():
            self.audio_tree.delete(item)
        self.audio_items.clear()
        self.artist_var.set(str(detail.get("artist") or ""))
        self.title_var.set(str(detail.get("title") or ""))
        self.album_var.set(str(detail.get("album") or ""))
        for audio in detail.get("audio_files") or []:
            key = str(audio["id"])
            self.audio_items[key] = dict(audio)
            self.audio_tree.insert(
                "",
                "end",
                iid=key,
                values=(audio.get("id"), audio.get("duration_seconds", ""), audio.get("fingerprints", 0), audio.get("segments", 0), audio.get("source_path", "")),
            )

    def _selected_audio(self) -> dict[str, Any] | None:
        selected = self.audio_tree.selection()
        return self.audio_items.get(selected[0]) if selected else None

    def _audio_selected(self, _event: Any = None) -> None:
        return

    def _play_selected_audio(self) -> None:
        audio = self._selected_audio()
        if audio:
            self._open_path(str(audio.get("source_path") or ""))

    def _reassign_selected_audio(self) -> None:
        audio = self._selected_audio()
        if not audio:
            messagebox.showwarning("Select audio", "Select one physical audio file first.", parent=self.root)
            return
        artist, title, album = self.artist_var.get(), self.title_var.get(), self.album_var.get()
        if not messagebox.askyesno(
            "Reassign audio",
            f"Move this audio fingerprint association to:\n\n{artist} — {title}\n\nThe music file itself will not change.",
            parent=self.root,
        ):
            return
        self._run(
            "Reassigning audio…",
            lambda: self.controller.reassign(int(audio["id"]), artist=artist, title=title, album=album, reason=self.reason_var.get()),
            self._after_mutation,
        )

    def _revoke_selected_recording(self) -> None:
        recording_id = self._selected_recording_id()
        row = self.recordings.get(recording_id)
        if not row:
            return
        if not messagebox.askyesno(
            "Revoke recording",
            f"Disable this recording from future full and partial matches?\n\n{row.get('artist')} — {row.get('title')}\n\nNo evidence will be deleted and Undo is available.",
            parent=self.root,
        ):
            return
        self._run(
            "Revoking recording…",
            lambda: self.controller.revoke(recording_id, reason=self.reason_var.get()),
            self._after_mutation,
        )

    def _merge_selected_recording(self) -> None:
        source = self._selected_recording_id()
        target = self.merge_target_var.get().strip()
        if not source or not target:
            messagebox.showwarning("Select source and target", "Select a source recording and enter the target recording ID.", parent=self.root)
            return
        if not messagebox.askyesno(
            "Merge recordings",
            f"Move all audio encodings, fingerprints, segments and external IDs from:\n{source}\n\ninto:\n{target}\n\nA backup and Undo entry will be created.",
            parent=self.root,
        ):
            return
        self._run(
            "Merging recordings…",
            lambda: self.controller.merge(source, target, reason=self.reason_var.get()),
            self._after_mutation,
        )

    def refresh_history(self) -> None:
        self._run("Loading audit history…", lambda: self.controller.history(limit=300), self._show_history)

    def _show_history(self, rows: list[dict[str, Any]]) -> None:
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)
        self.history_items.clear()
        for row in rows:
            key = str(row["id"])
            self.history_items[key] = dict(row)
            self.history_tree.insert(
                "",
                "end",
                iid=key,
                values=(row.get("status", ""), row.get("action_type", ""), row.get("reviewer", ""), row.get("reason", ""), row.get("created_at", ""), row.get("source_recording_id", ""), row.get("target_recording_id", ""), row.get("id", "")),
            )

    def _history_selected(self, _event: Any = None) -> None:
        selected = self.history_tree.selection()
        item = self.history_items.get(selected[0]) if selected else None
        self.audit_log.configure(state="normal")
        self.audit_log.delete("1.0", "end")
        if item:
            self.audit_log.insert("end", json.dumps(item, ensure_ascii=False, indent=2, sort_keys=True))
        self.audit_log.configure(state="disabled")

    def _undo_selected(self) -> None:
        selected = self.history_tree.selection()
        action_id = selected[0] if selected else ""
        if not action_id:
            messagebox.showwarning("Select an action", "Select an applied audit action first.", parent=self.root)
            return
        self._confirm_undo(action_id)

    def _undo_latest(self) -> None:
        self._confirm_undo("")

    def _confirm_undo(self, action_id: str) -> None:
        if not messagebox.askyesno(
            "Undo review action",
            "Restore the previous database associations for this action?\n\nThe audio files themselves will not change.",
            parent=self.root,
        ):
            return
        self._run("Undoing review action…", lambda: self.controller.undo(action_id), self._after_mutation)

    def _after_mutation(self, result: dict[str, Any]) -> None:
        messagebox.showinfo("Review action completed", json.dumps(result, ensure_ascii=False, indent=2), parent=self.root)
        self.refresh_queue()
        self.refresh_recordings()
        self.refresh_history()

    def _open_path(self, value: str) -> None:
        try:
            open_local_path(value)
        except Exception as exc:
            messagebox.showerror("Could not open path", str(exc), parent=self.root)

    def _open_backup_folder(self) -> None:
        self._open_path(str(self.controller.db_path.parent / "review_backups"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Open the Avachin Windows Review Center.")
    parser.add_argument("--db", type=Path)
    parser.add_argument("--report", default="")
    args = parser.parse_args()
    root = tk.Tk()
    ReviewCenterApp(root, controller=ReviewController(db_path=args.db), initial_report=args.report)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
