#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Avachin Review Center with a local-only Artist Alias Manager."""

from __future__ import annotations

import argparse
import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.artist_alias_controller import ArtistAliasController  # noqa: E402
from tools.avachin_review_desktop_gui import ReviewDesktopApp  # noqa: E402
from tools.review_online import latest_real_detection_report  # noqa: E402
from tools.version import AVACHIN_VERSION  # noqa: E402


class ArtistAliasReviewApp(ReviewDesktopApp):
    def __init__(
        self,
        root: tk.Tk,
        *,
        controller: ArtistAliasController | None = None,
        initial_report: str = "",
    ) -> None:
        super().__init__(
            root,
            controller=controller or ArtistAliasController(),
            initial_report=initial_report,
        )
        self.alias_groups: dict[str, dict[str, Any]] = {}
        self.alias_canonical_var = tk.StringVar()
        self.alias_variants_var = tk.StringVar()
        self.alias_reason_var = tk.StringVar(value="merge duplicate artist spellings")
        self.alias_status_var = tk.StringVar(value="No artist variants loaded")
        self.alias_tab = ttk.Frame(self.tabs, padding=10)
        self.tabs.add(self.alias_tab, text="Artist Aliases")
        self._build_alias_tab()
        self.refresh_alias_groups()

    @staticmethod
    def _parse_aliases(value: str) -> list[str]:
        normalized = value.replace("\n", ",").replace(";", ",")
        output: list[str] = []
        seen: set[str] = set()
        for part in normalized.split(","):
            text = " ".join(part.strip().split())
            key = text.casefold()
            if text and key not in seen:
                seen.add(key)
                output.append(text)
        return output

    def _build_alias_tab(self) -> None:
        info = ttk.LabelFrame(self.alias_tab, text="Local-only artist consolidation", padding=10)
        info.pack(fill="x")
        ttk.Label(
            info,
            text=(
                "Find spelling/spacing variants, choose one canonical artist, then consolidate local "
                "Recording identities. No AcoustID, AudD, MusicBrainz, Apple or Spotify request is sent."
            ),
            wraplength=1050,
        ).pack(anchor="w")
        ttk.Label(
            info,
            text=(
                "The fingerprint database is backed up and Undo is available. MP3 files and folders are "
                "not moved in this stage; their current folders are shown in Preview."
            ),
            wraplength=1050,
        ).pack(anchor="w", pady=(4, 0))

        body = ttk.Panedwindow(self.alias_tab, orient="horizontal")
        body.pack(fill="both", expand=True, pady=(10, 0))
        left = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(left, weight=2)
        body.add(right, weight=3)

        toolbar = ttk.Frame(left)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="Detect similar names", command=self.refresh_alias_groups).pack(side="left")
        ttk.Label(toolbar, textvariable=self.alias_status_var).pack(side="right")

        columns = ("canonical", "variants", "recordings", "audio", "key")
        self.alias_tree = ttk.Treeview(left, columns=columns, show="headings", selectmode="browse")
        widths = {"canonical": 150, "variants": 290, "recordings": 80, "audio": 65, "key": 130}
        headings = {
            "canonical": "Suggested canonical",
            "variants": "Detected variants",
            "recordings": "Recordings",
            "audio": "Audio",
            "key": "Compact key",
        }
        for column in columns:
            self.alias_tree.heading(column, text=headings[column])
            self.alias_tree.column(column, width=widths[column], anchor="w")
        alias_scroll = ttk.Scrollbar(left, orient="vertical", command=self.alias_tree.yview)
        self.alias_tree.configure(yscrollcommand=alias_scroll.set)
        self.alias_tree.pack(side="left", fill="both", expand=True, pady=(8, 0))
        alias_scroll.pack(side="right", fill="y", pady=(8, 0))
        self.alias_tree.bind("<<TreeviewSelect>>", self._alias_group_selected)

        form = ttk.LabelFrame(right, text="Canonical artist decision", padding=10)
        form.pack(fill="x")
        ttk.Label(form, text="Canonical artist").pack(anchor="w")
        ttk.Entry(form, textvariable=self.alias_canonical_var).pack(fill="x")
        ttk.Label(form, text="Aliases (comma separated; Persian and Latin forms may be entered together)").pack(
            anchor="w", pady=(7, 0)
        )
        ttk.Entry(form, textvariable=self.alias_variants_var).pack(fill="x")
        ttk.Label(form, text="Reason").pack(anchor="w", pady=(7, 0))
        ttk.Entry(form, textvariable=self.alias_reason_var).pack(fill="x")

        buttons = ttk.Frame(form)
        buttons.pack(fill="x", pady=(10, 0))
        ttk.Button(buttons, text="Preview consolidation", command=self._preview_aliases).pack(side="left")
        ttk.Button(buttons, text="Apply aliases to local DB", command=self._apply_aliases).pack(side="right")

        preview_box = ttk.LabelFrame(right, text="Preview — no files are changed", padding=8)
        preview_box.pack(fill="both", expand=True, pady=(10, 0))
        self.alias_preview = ScrolledText(preview_box, font=("Consolas", 9), state="disabled")
        self.alias_preview.pack(fill="both", expand=True)

    def refresh_alias_groups(self) -> None:
        self._run("Detecting artist-name variants…", self.controller.artist_groups, self._show_alias_groups)

    def _show_alias_groups(self, groups: list[dict[str, Any]]) -> None:
        for item in self.alias_tree.get_children():
            self.alias_tree.delete(item)
        self.alias_groups.clear()
        for index, group in enumerate(groups):
            key = f"alias-{index}"
            self.alias_groups[key] = dict(group)
            self.alias_tree.insert(
                "",
                "end",
                iid=key,
                values=(
                    group.get("suggested_canonical", ""),
                    ", ".join(group.get("variants") or []),
                    group.get("recordings", 0),
                    group.get("audio_files", 0),
                    group.get("group_key", ""),
                ),
            )
        self.alias_status_var.set(f"{len(groups)} duplicate-name group(s) detected")

    def _alias_group_selected(self, _event: Any = None) -> None:
        selected = self.alias_tree.selection()
        group = self.alias_groups.get(selected[0]) if selected else None
        if not group:
            return
        canonical = str(group.get("suggested_canonical") or "")
        variants = [str(value) for value in group.get("variants") or []]
        self.alias_canonical_var.set(canonical)
        self.alias_variants_var.set(", ".join(value for value in variants if value.casefold() != canonical.casefold()))
        self.alias_reason_var.set("merge duplicate artist spellings detected in local library")
        self._preview_aliases()

    def _alias_inputs(self) -> tuple[str, list[str]]:
        canonical = " ".join(self.alias_canonical_var.get().strip().split())
        aliases = self._parse_aliases(self.alias_variants_var.get())
        if not canonical:
            raise ValueError("Canonical artist is required")
        if canonical.casefold() not in {value.casefold() for value in aliases}:
            aliases.insert(0, canonical)
        if len({value.casefold() for value in aliases}) < 2:
            raise ValueError("Enter at least one alias different from the canonical artist")
        return canonical, aliases

    def _write_alias_preview(self, payload: dict[str, Any]) -> None:
        self.alias_preview.configure(state="normal")
        self.alias_preview.delete("1.0", "end")
        self.alias_preview.insert("end", json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        self.alias_preview.configure(state="disabled")

    def _preview_aliases(self) -> None:
        try:
            canonical, aliases = self._alias_inputs()
        except Exception as exc:
            messagebox.showwarning("Alias input", str(exc), parent=self.root)
            return
        self._run(
            "Building local alias preview…",
            lambda: self.controller.preview_artist_aliases(canonical, aliases),
            self._after_alias_preview,
        )

    def _after_alias_preview(self, payload: dict[str, Any]) -> None:
        self._write_alias_preview(payload)
        if payload.get("conflicts"):
            messagebox.showwarning(
                "Alias conflict",
                "At least one alias is already assigned to a different canonical artist. Resolve that mapping before Apply.",
                parent=self.root,
            )

    def _apply_aliases(self) -> None:
        try:
            canonical, aliases = self._alias_inputs()
        except Exception as exc:
            messagebox.showwarning("Alias input", str(exc), parent=self.root)
            return
        try:
            preview = self.controller.preview_artist_aliases(canonical, aliases)
        except Exception as exc:
            messagebox.showerror("Could not preview aliases", str(exc), parent=self.root)
            return
        if preview.get("conflicts"):
            messagebox.showwarning("Alias conflict", "Apply is blocked because an alias has another owner.", parent=self.root)
            return
        folders = "\n".join(str(value) for value in preview.get("source_folders") or []) or "(no physical folders recorded)"
        if not messagebox.askyesno(
            "Apply artist aliases",
            f"Canonical artist: {canonical}\nAliases: {', '.join(aliases)}\n\n"
            f"Recordings affected: {preview.get('recordings_affected', 0)}\n"
            f"Audio files in DB: {preview.get('audio_files_affected', 0)}\n\n"
            f"Current artist folders (not moved now):\n{folders}\n\n"
            "A SQLite backup and one Undo action will be created. No network request and no MP3 change will occur.",
            parent=self.root,
        ):
            return
        reason = self.alias_reason_var.get().strip() or "artist alias consolidation"
        self._run(
            "Applying artist aliases locally…",
            lambda: self.controller.apply_artist_aliases(canonical, aliases, reason=reason),
            self._after_alias_apply,
        )

    def _after_alias_apply(self, result: dict[str, Any]) -> None:
        self._write_alias_preview(result)
        messagebox.showinfo(
            "Artist aliases applied",
            f"Canonical artist: {result.get('canonical_artist')}\n"
            f"Recordings merged: {result.get('recordings_merged', 0)}\n"
            f"Audio associations moved: {result.get('audio_files_moved', 0)}\n"
            "Network requests: 0\nMusic files changed: No\n\n"
            "Use Audit & Undo to reverse this operation.",
            parent=self.root,
        )
        self.refresh_alias_groups()
        self.refresh_recordings()
        self.refresh_history()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch Avachin Review Center with Artist Alias Manager.")
    parser.add_argument("--report", default="", help="Optional DetectionResult JSON report")
    parser.add_argument("--check", action="store_true", help="Print readiness JSON without opening a window")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.check:
        print(
            json.dumps(
                {
                    "version": AVACHIN_VERSION,
                    "latest_real_detection_report": str(latest_real_detection_report() or ""),
                    "artist_alias_manager": True,
                    "alias_runtime_hook": True,
                    "local_only": True,
                    "network_requests": 0,
                    "music_files_changed": False,
                    "backup_audit_undo": True,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    root = tk.Tk()
    ArtistAliasReviewApp(root, initial_report=args.report)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
