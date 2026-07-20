#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Responsive Audit and Undo page."""

from __future__ import annotations

import json
import tkinter as tk

from tools.persian_ui_common import ACTION_LABELS, PALETTE, clean_text
from tools.persian_ui_history import HistoryPageMixin
from tools.persian_ui_textbox import build_scrollable_text
from tools.persian_ui_widgets import build_scrollable_tree


class HistoryPageV2Mixin(HistoryPageMixin):
    def _build_history_page(self, page: tk.Frame) -> None:
        self._section_intro(
            page,
            "تغییرات قابل بازگشت",
            "همه اصلاحات انسانی همراه با دلیل و نسخه پشتیبان ثبت می‌شوند.",
        )

        toolbar_card = self._card(page)
        toolbar_card.pack(fill="x")
        toolbar = tk.Frame(toolbar_card, bg=PALETTE["surface"])
        toolbar.pack(fill="x", padx=14, pady=12)
        for column in range(3):
            toolbar.grid_columnconfigure(column, weight=1, uniform="history-actions")
        self._flat_button(
            toolbar,
            "به‌روزرسانی تاریخچه",
            self.refresh_history,
        ).grid(row=0, column=2, sticky="ew", padx=4)
        self._flat_button(
            toolbar,
            "بازگشت عملیات انتخاب‌شده",
            self._undo_selected,
            kind="danger",
        ).grid(row=0, column=1, sticky="ew", padx=4)
        self._flat_button(
            toolbar,
            "بازگشت آخرین عملیات",
            self._undo_latest,
        ).grid(row=0, column=0, sticky="ew", padx=4)

        table_card = self._card(page)
        table_card.pack(fill="both", expand=True, pady=(12, 0))
        table_inner = tk.Frame(table_card, bg=PALETTE["surface"])
        table_inner.pack(fill="both", expand=True, padx=12, pady=12)
        columns = ("status", "type", "reason", "created", "id")
        headers = {
            "status": "وضعیت",
            "type": "نوع عملیات",
            "reason": "دلیل",
            "created": "زمان",
            "id": "شناسه",
        }
        widths = {
            "status": 120,
            "type": 230,
            "reason": 500,
            "created": 220,
            "id": 300,
        }
        tree_frame, self.history_tree = build_scrollable_tree(
            table_inner,
            columns=columns,
            headings=headers,
            widths=widths,
            anchors={"created": "w", "id": "w"},
            displaycolumns=("id", "created", "reason", "type", "status"),
            height=11,
        )
        tree_frame.pack(fill="both", expand=True)
        self.history_tree.bind("<<TreeviewSelect>>", self._history_selected)

        detail_card = self._card(page)
        detail_card.pack(fill="both", expand=True, pady=(12, 18))
        detail_inner = tk.Frame(detail_card, bg=PALETTE["surface"])
        detail_inner.pack(fill="both", expand=True, padx=14, pady=12)
        tk.Label(
            detail_inner,
            text="جزئیات عملیات",
            bg=PALETTE["surface"],
            fg=PALETTE["text"],
            font=(self.font_family, 11, "bold"),
            anchor="e",
        ).pack(fill="x")
        text_frame, self.history_detail = build_scrollable_text(detail_inner, height=13, wrap="none")
        self.history_detail.configure(font=(self.font_family, 9))
        text_frame.pack(fill="both", expand=True, pady=(8, 0))

    def _history_selected(self, _event: object = None) -> None:
        selected = self.history_tree.selection()
        item = self.history_items.get(selected[0]) if selected else None
        self.history_detail.configure(state="normal")
        self.history_detail.delete("1.0", "end")
        if item:
            action = ACTION_LABELS.get(
                clean_text(item.get("action_type")),
                clean_text(item.get("action_type")),
            )
            status = "انجام‌شده" if item.get("status") == "applied" else "بازگردانده‌شده"
            summary = [
                f"نوع عملیات: {action}",
                f"وضعیت: {status}",
                f"دلیل: {clean_text(item.get('reason'))}",
                f"زمان: {clean_text(item.get('created_at'))}",
                f"شناسه: {clean_text(item.get('id'))}",
            ]
            self.history_detail.insert("end", "\n".join(summary) + "\n\n", "rtl")
            self.history_detail.insert("end", "Technical details\n", "ltr")
            self.history_detail.insert(
                "end",
                json.dumps(
                    {"before": item.get("before"), "after": item.get("after")},
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                ),
                "ltr",
            )
        self.history_detail.configure(state="disabled")
