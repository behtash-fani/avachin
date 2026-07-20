#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Responsive Home and Preview page."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from tools.persian_ui_common import PALETTE
from tools.persian_ui_home import HomePageMixin
from tools.persian_ui_textbox import build_scrollable_text


class HomePageV2Mixin(HomePageMixin):
    def _build_home_page(self, page: tk.Frame) -> None:
        self._section_intro(
            page,
            "پیش‌نمایش آرشیو موسیقی",
            "پوشه را انتخاب کنید؛ آواچین فقط نتیجه پیشنهادی و گزارش می‌سازد و فایل‌ها را تغییر نمی‌دهد.",
        )

        status_grid = tk.Frame(page, bg=PALETTE["background"])
        status_grid.pack(fill="x")
        for column in range(2):
            status_grid.grid_columnconfigure(column, weight=1, uniform="status")
        self.status_value_labels: dict[str, tk.Label] = {}
        status_defs = (
            ("fingerprint", "ابزار تشخیص"),
            ("repair", "تعمیر فایل صوتی"),
            ("database", "بانک محلی"),
            ("budget", "سهمیه آنلاین"),
        )
        for index, (key, title) in enumerate(status_defs):
            row, column = divmod(index, 2)
            card = self._card(status_grid)
            card.grid(row=row, column=1 - column, sticky="nsew", padx=5, pady=5)
            inner = tk.Frame(card, bg=PALETTE["surface"])
            inner.pack(fill="both", expand=True, padx=16, pady=14)
            tk.Label(
                inner,
                text=title,
                bg=PALETTE["surface"],
                fg=PALETTE["muted"],
                font=(self.font_family, 9),
                anchor="e",
            ).pack(fill="x")
            label = tk.Label(
                inner,
                text="در حال بررسی…",
                bg=PALETTE["surface"],
                fg=PALETTE["text"],
                font=(self.font_family, 12, "bold"),
                anchor="e",
            )
            label.pack(fill="x", pady=(6, 0))
            self.status_value_labels[key] = label

        choose_card = self._card(page)
        choose_card.pack(fill="x", pady=(12, 0))
        choose_inner = tk.Frame(choose_card, bg=PALETTE["surface"])
        choose_inner.pack(fill="x", padx=18, pady=16)
        tk.Label(
            choose_inner,
            text="پوشه موسیقی",
            bg=PALETTE["surface"],
            fg=PALETTE["text"],
            font=(self.font_family, 11, "bold"),
            anchor="e",
        ).pack(fill="x")
        tk.Label(
            choose_inner,
            text="برای آزمایش اولیه بهتر است ابتدا یک پوشه کوچک را انتخاب کنید.",
            bg=PALETTE["surface"],
            fg=PALETTE["muted"],
            font=(self.font_family, 9),
            anchor="e",
        ).pack(fill="x", pady=(3, 10))

        folder_row = tk.Frame(choose_inner, bg=PALETTE["surface"])
        folder_row.pack(fill="x")
        self._flat_button(folder_row, "انتخاب پوشه", self._browse_folder).pack(side="right")
        self.folder_entry = ttk.Entry(folder_row, textvariable=self.folder_var, justify="left")
        self.folder_entry.pack(side="right", fill="x", expand=True, padx=(0, 10))

        options = tk.Frame(choose_inner, bg=PALETTE["surface"])
        options.pack(fill="x", pady=(12, 0))
        ttk.Checkbutton(
            options,
            text="حالت آفلاین؛ فقط بانک محلی استفاده شود",
            variable=self.offline_var,
        ).pack(side="right")
        self._flat_button(options, "به‌روزرسانی وضعیت", self._load_runtime_status).pack(side="left")

        action_card = self._card(page)
        action_card.pack(fill="x", pady=(12, 0))
        action_inner = tk.Frame(action_card, bg=PALETTE["surface"])
        action_inner.pack(fill="x", padx=16, pady=14)
        self.start_preview_button = self._flat_button(
            action_inner,
            "شروع پیش‌نمایش",
            self._start_preview,
            kind="primary",
        )
        self.start_preview_button.pack(side="right")
        self.cancel_preview_button = self._flat_button(
            action_inner,
            "توقف امن",
            self._cancel_preview,
            kind="danger",
        )
        self.cancel_preview_button.pack(side="right", padx=(0, 8))
        self.cancel_preview_button.configure(state="disabled")
        tk.Label(
            action_inner,
            textvariable=self.preview_status_var,
            bg=PALETTE["surface"],
            fg=PALETTE["cyan"],
            font=(self.font_family, 10, "bold"),
            anchor="w",
        ).pack(side="left")

        progress_inner = tk.Frame(action_card, bg=PALETTE["surface"])
        progress_inner.pack(fill="x", padx=16, pady=(0, 14))
        self.preview_progress = ttk.Progressbar(progress_inner, mode="determinate", maximum=100)
        self.preview_progress.pack(fill="x")
        tk.Label(
            progress_inner,
            textvariable=self.preview_progress_var,
            bg=PALETTE["surface"],
            fg=PALETTE["muted"],
            font=(self.font_family, 9),
            anchor="e",
        ).pack(fill="x", pady=(7, 0))

        report_card = self._card(page)
        report_card.pack(fill="x", pady=(12, 0))
        report_inner = tk.Frame(report_card, bg=PALETTE["surface"])
        report_inner.pack(fill="x", padx=16, pady=14)
        tk.Label(
            report_inner,
            text="گزارش‌های آخرین اجرا",
            bg=PALETTE["surface"],
            fg=PALETTE["text"],
            font=(self.font_family, 11, "bold"),
            anchor="e",
        ).pack(fill="x")
        self.artifact_frame = tk.Frame(report_inner, bg=PALETTE["surface"])
        self.artifact_frame.pack(fill="x", pady=(8, 0))
        self.no_artifact_label = tk.Label(
            self.artifact_frame,
            text="پس از پایان پیش‌نمایش، دکمه‌های گزارش در این بخش ظاهر می‌شوند.",
            bg=PALETTE["surface"],
            fg=PALETTE["muted"],
            font=(self.font_family, 9),
            justify="right",
            anchor="e",
        )
        self.no_artifact_label.pack(fill="x")

        log_card = self._card(page)
        log_card.pack(fill="both", expand=True, pady=(12, 18))
        log_inner = tk.Frame(log_card, bg=PALETTE["surface"])
        log_inner.pack(fill="both", expand=True, padx=16, pady=14)
        tk.Label(
            log_inner,
            text="جزئیات اجرای پیش‌نمایش",
            bg=PALETTE["surface"],
            fg=PALETTE["text"],
            font=(self.font_family, 11, "bold"),
            anchor="e",
        ).pack(fill="x")
        text_frame, self.preview_log = build_scrollable_text(log_inner, height=11, wrap="none")
        self.preview_log.configure(font=(self.font_family, 9))
        text_frame.pack(fill="both", expand=True, pady=(8, 0))
