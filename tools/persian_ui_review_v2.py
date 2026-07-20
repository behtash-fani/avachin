#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Responsive Review Queue page."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from tools.persian_ui_common import PALETTE
from tools.persian_ui_review import ReviewPageMixin
from tools.persian_ui_widgets import build_scrollable_tree


class ReviewPageV2Mixin(ReviewPageMixin):
    def _build_review_page(self, page: tk.Frame) -> None:
        self._section_intro(
            page,
            "موارد نیازمند بررسی",
            "نتیجه آنلاین فقط پیشنهاد است؛ پس از پخش فایل و تأیید شما در بانک محلی ثبت می‌شود.",
        )

        report_card = self._card(page)
        report_card.pack(fill="x")
        report_inner = tk.Frame(report_card, bg=PALETTE["surface"])
        report_inner.pack(fill="x", padx=16, pady=14)
        tk.Label(
            report_inner,
            textvariable=self.review_count_var,
            bg=PALETTE["surface"],
            fg=PALETTE["cyan"],
            font=(self.font_family, 9, "bold"),
            anchor="e",
        ).pack(fill="x", pady=(0, 8))
        report_path_row = tk.Frame(report_inner, bg=PALETTE["surface"])
        report_path_row.pack(fill="x")
        self._flat_button(report_path_row, "به‌روزرسانی", self.refresh_review_queue).pack(side="right")
        self._flat_button(report_path_row, "انتخاب گزارش", self._browse_report).pack(side="right", padx=(0, 8))
        ttk.Entry(report_path_row, textvariable=self.report_var, justify="left").pack(
            side="right", fill="x", expand=True, padx=(0, 10)
        )

        table_card = self._card(page)
        table_card.pack(fill="both", expand=True, pady=(12, 0))
        table_inner = tk.Frame(table_card, bg=PALETTE["surface"])
        table_inner.pack(fill="both", expand=True, padx=12, pady=12)
        columns = ("decision", "artist", "title", "confidence", "provider", "path")
        headers = {
            "decision": "وضعیت",
            "artist": "هنرمند",
            "title": "عنوان",
            "confidence": "اطمینان",
            "provider": "منبع",
            "path": "مسیر فایل",
        }
        widths = {
            "decision": 120,
            "artist": 180,
            "title": 220,
            "confidence": 90,
            "provider": 130,
            "path": 520,
        }
        tree_frame, self.review_tree = build_scrollable_tree(
            table_inner,
            columns=columns,
            headings=headers,
            widths=widths,
            anchors={"path": "w", "provider": "w", "confidence": "center"},
            displaycolumns=("path", "provider", "confidence", "title", "artist", "decision"),
            height=12,
        )
        tree_frame.pack(fill="both", expand=True)
        self.review_tree.bind("<<TreeviewSelect>>", self._review_selected)

        form_card = self._card(page)
        form_card.pack(fill="x", pady=(12, 18))
        form_inner = tk.Frame(form_card, bg=PALETTE["surface"])
        form_inner.pack(fill="x", padx=16, pady=14)

        form_grid = tk.Frame(form_inner, bg=PALETTE["surface"])
        form_grid.pack(fill="x")
        for column in range(3):
            form_grid.grid_columnconfigure(column, weight=1, uniform="identity")
        fields = (
            ("هنرمند", self.artist_var, 2),
            ("عنوان آهنگ", self.title_var, 1),
            ("آلبوم", self.album_var, 0),
        )
        for label, variable, column in fields:
            cell = tk.Frame(form_grid, bg=PALETTE["surface"])
            cell.grid(row=0, column=column, sticky="ew", padx=5)
            tk.Label(
                cell,
                text=label,
                bg=PALETTE["surface"],
                fg=PALETTE["muted"],
                font=(self.font_family, 9),
                anchor="e",
            ).pack(fill="x")
            ttk.Entry(cell, textvariable=variable, justify="right").pack(fill="x", pady=(5, 0))

        tk.Label(
            form_inner,
            text="دلیل تأیید یا اصلاح",
            bg=PALETTE["surface"],
            fg=PALETTE["muted"],
            font=(self.font_family, 9),
            anchor="e",
        ).pack(fill="x", pady=(12, 0))
        ttk.Entry(form_inner, textvariable=self.reason_var, justify="right").pack(fill="x", pady=(5, 0))

        actions = tk.Frame(form_inner, bg=PALETTE["surface"])
        actions.pack(fill="x", pady=(14, 0))
        for column in range(2):
            actions.grid_columnconfigure(column, weight=1, uniform="review-actions")
        self._flat_button(
            actions,
            "تأیید و ثبت در بانک محلی",
            self._apply_review_identity,
            kind="success",
        ).grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        self._flat_button(
            actions,
            "شناسایی آنلاین این فایل",
            self._identify_selected_online,
            kind="primary",
        ).grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        self._flat_button(
            actions,
            "پخش فایل انتخاب‌شده",
            self._play_selected_review,
        ).grid(row=1, column=1, sticky="ew", padx=4, pady=4)
        self._flat_button(
            actions,
            "شناسایی آنلاین همه موارد",
            self._identify_all_online,
        ).grid(row=1, column=0, sticky="ew", padx=4, pady=4)
