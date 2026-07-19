#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Avachin Review Center desktop UX fixes.

Adds Windows-friendly clipboard shortcuts and a context menu to every Entry,
shows manual edits immediately in the selected queue row, and uses persistent
human-review state so successfully verified rows disappear until Undo.
"""

from __future__ import annotations

import argparse
import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.avachin_review_online_gui import OnlineReviewCenterApp  # noqa: E402
from tools.review_online import latest_real_detection_report  # noqa: E402
from tools.review_queue_state import ResolvedQueueController  # noqa: E402
from tools.version import AVACHIN_VERSION  # noqa: E402


class ReviewDesktopApp(OnlineReviewCenterApp):
    """Review Center with reliable clipboard and honest queue state."""

    def __init__(
        self,
        root: tk.Tk,
        *,
        controller: ResolvedQueueController | None = None,
        initial_report: str = "",
    ) -> None:
        self._identity_sync_depth = 0
        self._entry_menu_target: Any | None = None
        self._entry_menu: tk.Menu | None = None
        super().__init__(
            root,
            controller=controller or ResolvedQueueController(),
            initial_report=initial_report,
        )
        self._install_clipboard_support()
        self._install_identity_traces()

    # ------------------------------------------------------------------
    # Clipboard support
    # ------------------------------------------------------------------
    def _selected_entry_text(self, widget: Any) -> str:
        try:
            if widget.selection_present():
                return str(widget.selection_get())
        except (AttributeError, tk.TclError):
            pass
        return ""

    def _delete_entry_selection(self, widget: Any) -> None:
        try:
            if widget.selection_present():
                widget.delete("sel.first", "sel.last")
        except (AttributeError, tk.TclError):
            pass

    def _copy_entry(self, widget: Any) -> str:
        selected = self._selected_entry_text(widget)
        if selected:
            self.root.clipboard_clear()
            self.root.clipboard_append(selected)
            self.root.update_idletasks()
        return "break"

    def _cut_entry(self, widget: Any) -> str:
        self._copy_entry(widget)
        self._delete_entry_selection(widget)
        return "break"

    def _paste_entry(self, widget: Any) -> str:
        try:
            value = self.root.clipboard_get()
        except tk.TclError:
            return "break"
        self._delete_entry_selection(widget)
        try:
            widget.insert("insert", value)
        except (AttributeError, tk.TclError):
            pass
        return "break"

    def _select_all_entry(self, widget: Any) -> str:
        try:
            widget.selection_range(0, "end")
            widget.icursor("end")
        except (AttributeError, tk.TclError):
            pass
        return "break"

    def _clipboard_keycode(self, event: tk.Event[Any]) -> str | None:
        # Windows virtual-key codes remain stable even when Persian keyboard
        # layout changes the produced keysym/character.
        action = {
            65: self._select_all_entry,  # A
            67: self._copy_entry,        # C
            86: self._paste_entry,       # V
            88: self._cut_entry,         # X
        }.get(int(getattr(event, "keycode", -1)))
        return action(event.widget) if action is not None else None

    def _show_entry_menu(self, event: tk.Event[Any]) -> str:
        self._entry_menu_target = event.widget
        if self._entry_menu is not None:
            self._entry_menu.tk_popup(event.x_root, event.y_root)
        return "break"

    def _menu_action(self, action: str) -> None:
        widget = self._entry_menu_target
        if widget is None:
            return
        {
            "cut": self._cut_entry,
            "copy": self._copy_entry,
            "paste": self._paste_entry,
            "select_all": self._select_all_entry,
        }[action](widget)

    def _install_clipboard_support(self) -> None:
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="Cut", command=lambda: self._menu_action("cut"))
        menu.add_command(label="Copy", command=lambda: self._menu_action("copy"))
        menu.add_command(label="Paste", command=lambda: self._menu_action("paste"))
        menu.add_separator()
        menu.add_command(label="Select All", command=lambda: self._menu_action("select_all"))
        self._entry_menu = menu

        for widget_class in ("TEntry", "Entry"):
            for sequence in ("<Control-v>", "<Control-V>", "<Shift-Insert>"):
                self.root.bind_class(
                    widget_class,
                    sequence,
                    lambda event: self._paste_entry(event.widget),
                )
            for sequence in ("<Control-c>", "<Control-C>"):
                self.root.bind_class(
                    widget_class,
                    sequence,
                    lambda event: self._copy_entry(event.widget),
                )
            for sequence in ("<Control-x>", "<Control-X>"):
                self.root.bind_class(
                    widget_class,
                    sequence,
                    lambda event: self._cut_entry(event.widget),
                )
            for sequence in ("<Control-a>", "<Control-A>"):
                self.root.bind_class(
                    widget_class,
                    sequence,
                    lambda event: self._select_all_entry(event.widget),
                )
            self.root.bind_class(
                widget_class,
                "<Control-KeyPress>",
                self._clipboard_keycode,
                add="+",
            )
            self.root.bind_class(
                widget_class,
                "<Button-3>",
                self._show_entry_menu,
            )

    # ------------------------------------------------------------------
    # Queue state and manual edit feedback
    # ------------------------------------------------------------------
    def _install_identity_traces(self) -> None:
        for variable in (
            self.artist_var,
            self.title_var,
            self.album_var,
            self.reason_var,
        ):
            variable.trace_add("write", self._identity_form_changed)

    def _suspend_identity_sync(self) -> None:
        self._identity_sync_depth += 1

    def _resume_identity_sync(self) -> None:
        self._identity_sync_depth = max(0, self._identity_sync_depth - 1)

    def _queue_selected(self, event: Any = None) -> None:
        self._suspend_identity_sync()
        try:
            super()._queue_selected(event)
        finally:
            self._resume_identity_sync()

    def _apply_online_suggestion(self, key: str, suggestion: dict[str, Any]) -> bool:
        self._suspend_identity_sync()
        try:
            return super()._apply_online_suggestion(key, suggestion)
        finally:
            self._resume_identity_sync()

    def _identity_form_changed(self, *_args: Any) -> None:
        if self._identity_sync_depth:
            return
        try:
            if self.tabs.select() != str(self.queue_tab):
                return
        except tk.TclError:
            return
        key = self._selected_queue_key()
        item = self.queue_items.get(key)
        if item is None:
            return

        artist = self.artist_var.get().strip()
        title = self.title_var.get().strip()
        album = self.album_var.get().strip()
        reason = self.reason_var.get().strip() or "manual correction pending confirmation"
        item.update(
            {
                "artist": artist,
                "title": title,
                "album": album,
                "provider": "manual-pending",
                "overall_confidence": "",
                "reason": reason,
                "manual_pending": True,
            }
        )
        if self.queue_tree.exists(key):
            self.queue_tree.item(
                key,
                values=(
                    item.get("decision", ""),
                    artist,
                    title,
                    "",
                    "manual-pending",
                    reason,
                    item.get("source_path", ""),
                ),
            )

    def _show_queue(self, result: dict[str, Any]) -> None:
        super()._show_queue(result)
        if str(result.get("report_kind") or "") != "real":
            return
        unresolved = len(result.get("items") or [])
        resolved = int(result.get("resolved_count") or 0)
        if resolved:
            self.queue_count_var.set(
                f"{unresolved} item(s) need attention — {resolved} verified item(s) hidden"
            )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Launch Avachin Review Center with clipboard and resolved-state fixes."
    )
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
                    "clipboard_shortcuts": True,
                    "right_click_paste": True,
                    "manual_pending_feedback": True,
                    "verified_rows_hidden": True,
                    "undo_reopens_rows": True,
                    "online_suggestions_only": True,
                    "automatic_learning": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    root = tk.Tk()
    ReviewDesktopApp(root, initial_report=args.report)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
