#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit and Undo page for the Persian Avachin UI."""

from __future__ import annotations

import json
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any

from tools.persian_ui_common import ACTION_LABELS, PALETTE, clean_text


class HistoryPageMixin:
    def _build_history_page(self, page: tk.Frame) -> None:
        self._section_intro(
            page,
            "تغییرات قابل بازگشت",
            "همه اصلاحات انسانی همراه با دلیل و نسخه پشتیبان ثبت می‌شوند.",
        )

        toolbar = tk.Frame(page, bg=PALETTE["background"])
        toolbar.pack(fill="x", pady=(0, 12))
        self._flat_button(toolbar, "به‌روزرسانی تاریخچه", self.refresh_history).pack(side="right")
        self._flat_button(toolbar, "بازگشت عملیات انتخاب‌شده", self._undo_selected, kind="danger").pack(side="right", padx=(0, 8))
        self._flat_button(toolbar, "بازگشت آخرین عملیات", self._undo_latest).pack(side="left")

        body = tk.PanedWindow(
            page, orient="vertical", sashwidth=6, bg=PALETTE["background"], bd=0, relief="flat"
        )
        body.pack(fill="both", expand=True)

        history_card = self._card(body)
        history_inner = tk.Frame(history_card, bg=PALETTE["surface"])
        history_inner.pack(fill="both", expand=True, padx=12, pady=12)
        columns = ("status", "type", "reason", "created", "id")
        self.history_tree = ttk.Treeview(history_inner, columns=columns, show="headings", selectmode="browse")
        headers = {
            "status": "وضعیت", "type": "نوع عملیات", "reason": "دلیل",
            "created": "زمان", "id": "شناسه",
        }
        widths = {"status": 90, "type": 210, "reason": 390, "created": 180, "id": 250}
        for column in columns:
            self.history_tree.heading(column, text=headers[column], anchor="e")
            self.history_tree.column(column, width=widths[column], anchor="e")
        history_scroll = ttk.Scrollbar(history_inner, orient="vertical", command=self.history_tree.yview)
        self.history_tree.configure(yscrollcommand=history_scroll.set)
        history_scroll.pack(side="left", fill="y")
        self.history_tree.pack(side="right", fill="both", expand=True)
        self.history_tree.bind("<<TreeviewSelect>>", self._history_selected)

        detail_card = self._card(body)
        detail_inner = tk.Frame(detail_card, bg=PALETTE["surface"])
        detail_inner.pack(fill="both", expand=True, padx=14, pady=12)
        tk.Label(
            detail_inner, text="جزئیات عملیات", bg=PALETTE["surface"], fg=PALETTE["text"],
            font=(self.font_family, 11, "bold"), anchor="e",
        ).pack(fill="x")
        self.history_detail = ScrolledText(
            detail_inner, wrap="word", height=10, state="disabled",
            bg=PALETTE["black"], fg=PALETTE["text"], insertbackground=PALETTE["text"],
            selectbackground=PALETTE["primary_dark"], relief="flat", bd=0,
            padx=10, pady=10, font=(self.font_family, 9),
        )
        self.history_detail.pack(fill="both", expand=True, pady=(8, 0))
        self.history_detail.tag_configure("rtl", justify="right")

        body.add(history_card, minsize=300)
        body.add(detail_card, minsize=180)

    def refresh_history(self) -> None:
        self._run_async("در حال بارگذاری تاریخچه…", lambda: self.controller.history(limit=300), self._show_history)

    def _show_history(self, rows: list[dict[str, Any]]) -> None:
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)
        self.history_items.clear()
        for row in rows:
            key = clean_text(row.get("id"))
            if not key:
                continue
            self.history_items[key] = dict(row)
            status = "انجام‌شده" if clean_text(row.get("status")) == "applied" else "بازگردانده‌شده"
            action = ACTION_LABELS.get(clean_text(row.get("action_type")), clean_text(row.get("action_type")))
            self.history_tree.insert(
                "", "end", iid=key,
                values=(status, action, clean_text(row.get("reason")), clean_text(row.get("created_at")), key),
            )
        if rows:
            first = self.history_tree.get_children()[0]
            self.history_tree.selection_set(first)
            self.history_tree.focus(first)
            self._history_selected()

    def _history_selected(self, _event: Any = None) -> None:
        selected = self.history_tree.selection()
        item = self.history_items.get(selected[0]) if selected else None
        lines: list[str] = []
        if item:
            action = ACTION_LABELS.get(clean_text(item.get("action_type")), clean_text(item.get("action_type")))
            lines = [
                f"نوع عملیات: {action}",
                f"وضعیت: {'انجام‌شده' if item.get('status') == 'applied' else 'بازگردانده‌شده'}",
                f"دلیل: {clean_text(item.get('reason'))}",
                f"زمان: {clean_text(item.get('created_at'))}",
                f"شناسه: {clean_text(item.get('id'))}",
                "", "جزئیات فنی:",
                json.dumps(
                    {"before": item.get("before"), "after": item.get("after")},
                    ensure_ascii=False, indent=2, sort_keys=True,
                ),
            ]
        self.history_detail.configure(state="normal")
        self.history_detail.delete("1.0", "end")
        self.history_detail.insert("end", "\n".join(lines), "rtl")
        self.history_detail.configure(state="disabled")

    def _undo_selected(self) -> None:
        selected = self.history_tree.selection()
        action_id = selected[0] if selected else ""
        if not action_id:
            messagebox.showwarning("عملیاتی انتخاب نشده", "یک عملیات انجام‌شده را انتخاب کنید.", parent=self.root)
            return
        item = self.history_items.get(action_id) or {}
        if clean_text(item.get("status")) != "applied":
            messagebox.showinfo("قبلاً بازگردانده شده", "این عملیات قبلاً Undo شده است.", parent=self.root)
            return
        self._confirm_undo(action_id)

    def _undo_latest(self) -> None:
        self._confirm_undo("")

    def _confirm_undo(self, action_id: str) -> None:
        if not messagebox.askyesno(
            "بازگشت تغییر",
            "بانک محلی به وضعیت قبل از این عملیات برگردد؟\n\nفایل‌های موسیقی تغییری نمی‌کنند.",
            parent=self.root,
        ):
            return

        def done(_result: dict[str, Any]) -> None:
            messagebox.showinfo("عملیات بازگردانده شد", "اتصال‌های قبلی بانک محلی بازیابی شدند.", parent=self.root)
            self.refresh_review_queue()
            self.refresh_alias_groups()
            self.refresh_history()

        self._run_async("در حال بازگرداندن تغییر…", lambda: self.controller.undo(action_id), done)
