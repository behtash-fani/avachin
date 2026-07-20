#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Responsive Artist Alias page."""

from __future__ import annotations

import tkinter as tk

from tools.persian_ui_alias import AliasPageMixin
from tools.persian_ui_common import PALETTE
from tools.persian_ui_textbox import build_scrollable_text
from tools.persian_ui_widgets import build_scrollable_tree


class AliasPageV2Mixin(AliasPageMixin):
    def _build_alias_page(self, page: tk.Frame) -> None:
        self._section_intro(
            page,
            "یکسان‌سازی نام هنرمندان",
            "نام‌های دارای فاصله، نیم‌فاصله یا املای متفاوت را زیر یک نام اصلی قرار دهید.",
        )

        info = self._card(page)
        info.pack(fill="x")
        info_inner = tk.Frame(info, bg=PALETTE["surface"])
        info_inner.pack(fill="x", padx=16, pady=13)
        tk.Label(
            info_inner,
            text="این عملیات فقط بانک محلی را اصلاح می‌کند؛ پوشه‌ها و فایل‌های موسیقی جابه‌جا نمی‌شوند.",
            bg=PALETTE["surface"],
            fg=PALETTE["success"],
            font=(self.font_family, 10, "bold"),
            justify="right",
            anchor="e",
        ).pack(fill="x")
        tk.Label(
            info_inner,
            text="نمونه:  Moein Z  و  MoeinZ",
            bg=PALETTE["surface"],
            fg=PALETTE["muted"],
            font=(self.font_family, 9),
            justify="right",
            anchor="e",
        ).pack(fill="x", pady=(5, 0))
        tk.Label(
            info_inner,
            textvariable=self.alias_status_var,
            bg=PALETTE["surface"],
            fg=PALETTE["cyan"],
            font=(self.font_family, 9),
            anchor="e",
        ).pack(fill="x", pady=(5, 0))

        list_card = self._card(page)
        list_card.pack(fill="both", expand=True, pady=(12, 0))
        list_inner = tk.Frame(list_card, bg=PALETTE["surface"])
        list_inner.pack(fill="both", expand=True, padx=12, pady=12)
        self._flat_button(
            list_inner,
            "جست‌وجوی دوباره نام‌های مشابه",
            self.refresh_alias_groups,
        ).pack(anchor="e", pady=(0, 10))

        columns = ("canonical", "variants", "recordings", "audio")
        headers = {
            "canonical": "نام اصلی پیشنهادی",
            "variants": "نام‌های مشابه",
            "recordings": "رکورد",
            "audio": "فایل",
        }
        widths = {
            "canonical": 220,
            "variants": 520,
            "recordings": 100,
            "audio": 90,
        }
        tree_frame, self.alias_tree = build_scrollable_tree(
            list_inner,
            columns=columns,
            headings=headers,
            widths=widths,
            anchors={"recordings": "center", "audio": "center"},
            displaycolumns=("audio", "recordings", "variants", "canonical"),
            height=10,
        )
        tree_frame.pack(fill="both", expand=True)
        self.alias_tree.bind("<<TreeviewSelect>>", self._alias_selected)

        form_card = self._card(page)
        form_card.pack(fill="x", pady=(12, 18))
        form_inner = tk.Frame(form_card, bg=PALETTE["surface"])
        form_inner.pack(fill="x", padx=16, pady=14)

        for label, variable in (
            ("نام اصلی هنرمند", self.alias_canonical_var),
            ("نام‌های دیگر؛ با ویرگول جدا شوند", self.alias_variants_var),
            ("دلیل این ادغام", self.alias_reason_var),
        ):
            tk.Label(
                form_inner,
                text=label,
                bg=PALETTE["surface"],
                fg=PALETTE["muted"],
                font=(self.font_family, 9),
                anchor="e",
            ).pack(fill="x", pady=(10 if label != "نام اصلی هنرمند" else 0, 0))
            tk.Entry(
                form_inner,
                textvariable=variable,
                justify="right",
                bg=PALETTE["card"],
                fg=PALETTE["text"],
                insertbackground=PALETTE["text"],
                relief="flat",
                bd=0,
                font=(self.font_family, 10),
            ).pack(fill="x", ipady=9, pady=(5, 0))

        actions = tk.Frame(form_inner, bg=PALETTE["surface"])
        actions.pack(fill="x", pady=(14, 0))
        self._flat_button(
            actions,
            "ثبت نام‌ها در بانک محلی",
            self._apply_aliases,
            kind="success",
        ).pack(side="right")
        self._flat_button(
            actions,
            "پیش‌نمایش ادغام",
            self._preview_aliases,
            kind="primary",
        ).pack(side="right", padx=(0, 8))

        tk.Label(
            form_inner,
            text="نتیجه پیش‌نمایش",
            bg=PALETTE["surface"],
            fg=PALETTE["text"],
            font=(self.font_family, 11, "bold"),
            anchor="e",
        ).pack(fill="x", pady=(14, 0))
        text_frame, self.alias_preview = build_scrollable_text(form_inner, height=12, wrap="none")
        self.alias_preview.configure(font=(self.font_family, 9))
        text_frame.pack(fill="both", expand=True, pady=(8, 0))

    def _show_alias_preview(self, payload: dict[str, object]) -> None:
        folders = list(payload.get("source_folders") or [])
        conflicts = list(payload.get("conflicts") or [])
        summary = [
            f"نام اصلی: {payload.get('canonical_artist', '')}",
            f"نام‌های ثبت‌شونده: {'، '.join(payload.get('aliases') or [])}",
            "",
            f"رکوردهای تحت تأثیر: {payload.get('recordings_affected', 0)}",
            f"فایل‌های صوتی در بانک: {payload.get('audio_files_affected', 0)}",
            "درخواست اینترنتی: صفر",
            "تغییر فایل موسیقی: خیر",
        ]
        if conflicts:
            summary.extend(("", "تعارض: یکی از نام‌ها قبلاً به هنرمند دیگری متصل شده است."))
        self.alias_preview.configure(state="normal")
        self.alias_preview.delete("1.0", "end")
        self.alias_preview.insert("end", "\n".join(summary) + "\n\n", "rtl")
        self.alias_preview.insert("end", "Current folders:\n", "ltr")
        if folders:
            for folder in folders:
                self.alias_preview.insert("end", f"- {folder}\n", "ltr")
        else:
            self.alias_preview.insert("end", "- no physical folder recorded\n", "ltr")
        self.alias_preview.configure(state="disabled")
