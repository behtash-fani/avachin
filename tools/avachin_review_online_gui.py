#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Avachin Review Center with safe online identity suggestions.

The existing audited Review Center remains the write surface. This UI adds only
non-mutating provider lookups. A result fills the verification form and still
requires the user to press Apply verified identity before anything is learned.
"""

from __future__ import annotations

import argparse
import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.avachin_review_gui import ReviewCenterApp  # noqa: E402
from tools.review_online import OnlineReviewController, latest_real_detection_report  # noqa: E402
from tools.version import AVACHIN_VERSION  # noqa: E402


class OnlineReviewCenterApp(ReviewCenterApp):
    def __init__(
        self,
        root: tk.Tk,
        *,
        controller: OnlineReviewController | None = None,
        initial_report: str = "",
    ) -> None:
        super().__init__(
            root,
            controller=controller or OnlineReviewController(),
            initial_report=initial_report,
        )

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
        widths = {
            "decision": 80,
            "artist": 150,
            "title": 180,
            "confidence": 80,
            "provider": 110,
            "reason": 210,
            "path": 340,
        }
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
        ttk.Button(
            actions,
            text="Find current DB association",
            command=self._find_queue_association,
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            actions,
            text="Identify selected online",
            command=self._identify_selected_online,
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            actions,
            text="Identify all real items online",
            command=self._identify_all_online,
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            actions,
            text="Apply verified identity",
            command=self._apply_queue_identity,
        ).pack(side="right")
        self._build_identity_form(lower)

    def _show_queue(self, result: dict[str, Any]) -> None:
        super()._show_queue(result)
        if str(result.get("report_kind") or "") == "benchmark":
            self.queue_count_var.set(
                f"{len(result.get('items') or [])} benchmark item(s) — online lookup disabled"
            )
            messagebox.showwarning(
                "Benchmark report selected",
                "This report contains generated benchmark samples, not unresolved files from your music library. "
                "Online lookup is disabled for these items to protect provider quota. Choose a real Preview detection report instead.",
                parent=self.root,
            )

    def _selected_queue_key(self) -> str:
        selected = self.queue_tree.selection()
        return selected[0] if selected else ""

    def _apply_online_suggestion(self, key: str, suggestion: dict[str, Any]) -> bool:
        item = self.queue_items.get(key)
        if item is None or str(suggestion.get("status") or "") != "suggested":
            return False
        provider = str(suggestion.get("provider") or "online")
        confidence = float(suggestion.get("confidence") or 0.0)
        item.update(
            {
                "artist": str(suggestion.get("artist") or ""),
                "title": str(suggestion.get("title") or ""),
                "album": str(suggestion.get("album") or ""),
                "provider": provider,
                "overall_confidence": round(confidence, 2),
                "reason": f"online suggestion from {provider}; human confirmation required",
                "online_suggestion": dict(suggestion),
            }
        )
        self.queue_tree.item(
            key,
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
        if key == self._selected_queue_key():
            self.artist_var.set(str(item.get("artist") or ""))
            self.title_var.set(str(item.get("title") or ""))
            self.album_var.set(str(item.get("album") or ""))
            self.reason_var.set(str(item.get("reason") or ""))
        return True

    def _online_lookup_confirmation(self, count: int) -> bool:
        return messagebox.askyesno(
            "Identify online",
            "Avachin will try AcoustID first, then reliable free catalog hints, and AudD only when needed.\n\n"
            f"Selected real files: {count}\n"
            f"Maximum possible new AudD requests: {count}\n\n"
            "Results are suggestions only. Nothing is learned until you confirm Apply verified identity.",
            parent=self.root,
        )

    def _identify_selected_online(self) -> None:
        key = self._selected_queue_key()
        item = self.queue_items.get(key)
        if item is None:
            messagebox.showwarning("Select an item", "Select one REVIEW or REJECT item first.", parent=self.root)
            return
        if not bool(item.get("online_lookup_allowed")):
            messagebox.showwarning(
                "Online lookup unavailable",
                "This item is either a benchmark-generated sample or its source file no longer exists.",
                parent=self.root,
            )
            return
        if not self._online_lookup_confirmation(1):
            return
        path = str(item.get("source_path") or "")

        def done(result: dict[str, Any]) -> None:
            if self._apply_online_suggestion(key, result):
                messagebox.showinfo(
                    "Online suggestion found",
                    f"{result.get('artist')} — {result.get('title')}\n"
                    f"Provider: {result.get('provider')}\n"
                    f"Confidence: {float(result.get('confidence') or 0.0):.1f}%\n\n"
                    "Listen to the file, verify the identity, then press Apply verified identity.",
                    parent=self.root,
                )
            else:
                errors = "\n".join(str(value) for value in result.get("errors") or [])
                messagebox.showwarning(
                    "No online identity found",
                    "No trustworthy result was returned. The file remains unresolved."
                    + (f"\n\n{errors}" if errors else ""),
                    parent=self.root,
                )

        self._run(
            "Identifying selected file online…",
            lambda: self.controller.identify_online(path),
            done,
        )

    def _identify_all_online(self) -> None:
        targets = [
            (key, item)
            for key, item in self.queue_items.items()
            if bool(item.get("online_lookup_allowed"))
            and str((item.get("online_suggestion") or {}).get("status") or "") != "suggested"
        ]
        if not targets:
            messagebox.showinfo(
                "Nothing to identify",
                "There are no unresolved real files eligible for online lookup.",
                parent=self.root,
            )
            return
        if not self._online_lookup_confirmation(len(targets)):
            return

        def operation() -> list[tuple[str, dict[str, Any]]]:
            results: list[tuple[str, dict[str, Any]]] = []
            for key, item in targets:
                path = str(item.get("source_path") or "")
                try:
                    result = self.controller.identify_online(path)
                except Exception as exc:
                    result = {
                        "status": "failed",
                        "source_path": path,
                        "errors": [str(exc)],
                        "database_changed": False,
                        "learned": False,
                    }
                results.append((key, result))
            return results

        def done(results: list[tuple[str, dict[str, Any]]]) -> None:
            found = 0
            not_found = 0
            failed = 0
            for key, result in results:
                if self._apply_online_suggestion(key, result):
                    found += 1
                elif str(result.get("status") or "") == "failed":
                    failed += 1
                else:
                    not_found += 1
            messagebox.showinfo(
                "Online identification completed",
                f"Suggestions found: {found}\nNot found: {not_found}\nFailed safely: {failed}\n\n"
                "Each suggestion still requires listening and manual confirmation before it is learned.",
                parent=self.root,
            )

        self._run("Identifying review queue online…", operation, done)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Launch Avachin Review Center with safe online suggestions.")
    parser.add_argument("--report", default="", help="Optional DetectionResult JSON report")
    parser.add_argument("--check", action="store_true", help="Print readiness JSON without opening a window")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.check:
        latest = latest_real_detection_report()
        print(
            json.dumps(
                {
                    "version": AVACHIN_VERSION,
                    "latest_real_detection_report": str(latest or ""),
                    "online_suggestions_only": True,
                    "automatic_learning": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    root = tk.Tk()
    OnlineReviewCenterApp(root, initial_report=args.report)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
