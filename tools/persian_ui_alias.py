#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Artist alias page for the Persian Avachin UI."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any

from tools.persian_ui_common import PALETTE, clean_text


class AliasPageMixin:
    def _build_alias_page(self, page: tk.Frame) -> None:
        self._section_intro(
            page,
            "یکسان‌سازی نام هنرمندان",
            "نام‌هایی مانند Moein Z و MoeinZ را بدون استفاده از اینترنت زیر یک نام اصلی قرار دهید.",
        )

        info = self._card(page)
        info.pack(fill="x")
        info_inner = tk.Frame(info, bg=PALETTE["surface"])
        info_inner.pack(fill="x", padx=16, pady=13)
        tk.Label(
            info_inner,
            text="این عملیات فقط بانک محلی را اصلاح می‌کند؛ پوشه‌ها و فایل‌های MP3 جابه‌جا نمی‌شوند.",
            bg=PALETTE["surface"], fg=PALETTE["success"],
            font=(self.font_family, 10, "bold"), justify="right", anchor="e",
        ).pack(fill="x")
        tk.Label(
            info_inner, textvariable=self.alias_status_var, bg=PALETTE["surface"],
            fg=PALETTE["cyan"], font=(self.font_family, 9), anchor="e",
        ).pack(fill="x", pady=(5, 0))

        body = tk.PanedWindow(
            page, orient="horizontal", sashwidth=6, bg=PALETTE["background"], bd=0, relief="flat"
        )
        body.pack(fill="both", expand=True, pady=(14, 0))

        list_card = self._card(body)
        list_inner = tk.Frame(list_card, bg=PALETTE["surface"])
        list_inner.pack(fill="both", expand=True, padx=12, pady=12)
        self._flat_button(list_inner, "جست‌وجوی دوباره نام‌های مشابه", self.refresh_alias_groups).pack(fill="x", pady=(0, 10))
        alias_columns = ("canonical", "variants", "recordings", "audio")
        self.alias_tree = ttk.Treeview(list_inner, columns=alias_columns, show="headings", selectmode="browse")
        alias_headers = {
            "canonical": "نام اصلی پیشنهادی", "variants": "نام‌های مشابه",
            "recordings": "رکورد", "audio": "فایل",
        }
        alias_widths = {"canonical": 165, "variants": 330, "recordings": 70, "audio": 65}
        for column in alias_columns:
            self.alias_tree.heading(column, text=alias_headers[column], anchor="e")
            self.alias_tree.column(column, width=alias_widths[column], anchor="e")
        alias_scroll = ttk.Scrollbar(list_inner, orient="vertical", command=self.alias_tree.yview)
        self.alias_tree.configure(yscrollcommand=alias_scroll.set)
        alias_scroll.pack(side="left", fill="y")
        self.alias_tree.pack(side="right", fill="both", expand=True)
        self.alias_tree.bind("<<TreeviewSelect>>", self._alias_selected)

        form_card = self._card(body)
        form_inner = tk.Frame(form_card, bg=PALETTE["surface"])
        form_inner.pack(fill="both", expand=True, padx=16, pady=14)

        for label, variable in (
            ("نام اصلی هنرمند", self.alias_canonical_var),
            ("نام‌های دیگر؛ با ویرگول جدا شوند", self.alias_variants_var),
            ("دلیل این ادغام", self.alias_reason_var),
        ):
            tk.Label(
                form_inner, text=label, bg=PALETTE["surface"], fg=PALETTE["muted"],
                font=(self.font_family, 9), anchor="e",
            ).pack(fill="x", pady=(8 if variable is not self.alias_canonical_var else 0, 0))
            ttk.Entry(form_inner, textvariable=variable, justify="right").pack(fill="x", pady=(5, 0))

        alias_actions = tk.Frame(form_inner, bg=PALETTE["surface"])
        alias_actions.pack(fill="x", pady=(12, 0))
        self._flat_button(alias_actions, "ثبت نام‌ها در بانک محلی", self._apply_aliases, kind="success").pack(side="right")
        self._flat_button(alias_actions, "پیش‌نمایش ادغام", self._preview_aliases, kind="primary").pack(side="right", padx=(0, 8))

        tk.Label(
            form_inner, text="نتیجه پیش‌نمایش", bg=PALETTE["surface"], fg=PALETTE["text"],
            font=(self.font_family, 11, "bold"), anchor="e",
        ).pack(fill="x", pady=(14, 0))
        self.alias_preview = ScrolledText(
            form_inner, wrap="word", height=12, state="disabled",
            bg=PALETTE["black"], fg=PALETTE["text"], insertbackground=PALETTE["text"],
            selectbackground=PALETTE["primary_dark"], relief="flat", bd=0,
            padx=10, pady=10, font=(self.font_family, 9),
        )
        self.alias_preview.pack(fill="both", expand=True, pady=(8, 0))
        self.alias_preview.tag_configure("rtl", justify="right")

        body.add(list_card, minsize=420)
        body.add(form_card, minsize=480)

    @staticmethod
    def _parse_aliases(value: str) -> list[str]:
        normalized = value.replace("\n", ",").replace(";", ",").replace("،", ",")
        output: list[str] = []
        seen: set[str] = set()
        for part in normalized.split(","):
            text = clean_text(part)
            key = text.casefold()
            if text and key not in seen:
                seen.add(key)
                output.append(text)
        return output

    def refresh_alias_groups(self) -> None:
        self._run_async("در حال پیدا کردن نام‌های مشابه…", self.controller.artist_groups, self._show_alias_groups)

    def _show_alias_groups(self, groups: list[dict[str, Any]]) -> None:
        for item in self.alias_tree.get_children():
            self.alias_tree.delete(item)
        self.alias_groups.clear()
        for index, group in enumerate(groups):
            key = f"alias-{index}"
            self.alias_groups[key] = dict(group)
            self.alias_tree.insert(
                "", "end", iid=key,
                values=(
                    clean_text(group.get("suggested_canonical")),
                    "، ".join(str(value) for value in group.get("variants") or []),
                    group.get("recordings", 0), group.get("audio_files", 0),
                ),
            )
        self.alias_status_var.set(
            f"{len(groups)} گروه با نام مشابه در بانک محلی پیدا شد"
            if groups else "نام تکراری خودکاری پیدا نشد؛ می‌توانید نام‌ها را دستی وارد کنید."
        )
        if groups:
            first = self.alias_tree.get_children()[0]
            self.alias_tree.selection_set(first)
            self.alias_tree.focus(first)
            self._alias_selected()

    def _alias_selected(self, _event: Any = None) -> None:
        selected = self.alias_tree.selection()
        group = self.alias_groups.get(selected[0]) if selected else None
        if not group:
            return
        canonical = clean_text(group.get("suggested_canonical"))
        variants = [clean_text(value) for value in group.get("variants") or []]
        self.alias_canonical_var.set(canonical)
        self.alias_variants_var.set(
            "، ".join(value for value in variants if value.casefold() != canonical.casefold())
        )
        self.alias_reason_var.set("ادغام نام‌های مختلف یک هنرمند در آرشیو محلی")
        self._preview_aliases()

    def _alias_inputs(self) -> tuple[str, list[str]]:
        canonical = clean_text(self.alias_canonical_var.get())
        aliases = self._parse_aliases(self.alias_variants_var.get())
        if not canonical:
            raise ValueError("نام اصلی هنرمند را وارد کنید.")
        if canonical.casefold() not in {value.casefold() for value in aliases}:
            aliases.insert(0, canonical)
        if len({value.casefold() for value in aliases}) < 2:
            raise ValueError("حداقل یک نام دیگر برای این هنرمند وارد کنید.")
        return canonical, aliases

    def _preview_aliases(self) -> None:
        try:
            canonical, aliases = self._alias_inputs()
        except Exception as exc:
            messagebox.showwarning("اطلاعات نام هنرمند", str(exc), parent=self.root)
            return
        self._run_async(
            "در حال ساخت پیش‌نمایش ادغام…",
            lambda: self.controller.preview_artist_aliases(canonical, aliases),
            self._show_alias_preview,
        )

    def _show_alias_preview(self, payload: dict[str, Any]) -> None:
        folders = list(payload.get("source_folders") or [])
        conflicts = list(payload.get("conflicts") or [])
        lines = [
            f"نام اصلی: {payload.get('canonical_artist', '')}",
            f"نام‌های ثبت‌شونده: {'، '.join(payload.get('aliases') or [])}",
            "",
            f"رکوردهای تحت تأثیر: {payload.get('recordings_affected', 0)}",
            f"فایل‌های صوتی در بانک: {payload.get('audio_files_affected', 0)}",
            "درخواست اینترنتی: صفر",
            "تغییر فایل موسیقی: خیر",
            "",
            "پوشه‌های فعلی:",
        ]
        lines.extend(f"• {folder}" for folder in folders)
        if not folders:
            lines.append("• پوشه‌ای در بانک ثبت نشده است")
        if conflicts:
            lines.extend(("", "تعارض: یکی از نام‌ها قبلاً به هنرمند دیگری متصل شده است."))
        self.alias_preview.configure(state="normal")
        self.alias_preview.delete("1.0", "end")
        self.alias_preview.insert("end", "\n".join(lines), "rtl")
        self.alias_preview.configure(state="disabled")

    def _apply_aliases(self) -> None:
        try:
            canonical, aliases = self._alias_inputs()
            preview = self.controller.preview_artist_aliases(canonical, aliases)
        except Exception as exc:
            messagebox.showerror("پیش‌نمایش ناموفق بود", str(exc), parent=self.root)
            return
        if preview.get("conflicts"):
            messagebox.showwarning(
                "تعارض نام هنرمند",
                "یکی از نام‌ها قبلاً به هنرمند دیگری متصل شده و عملیات متوقف شد.",
                parent=self.root,
            )
            return
        if not messagebox.askyesno(
            "ثبت نام‌های هنرمند",
            f"نام اصلی: {canonical}\nنام‌های دیگر: {'، '.join(aliases)}\n\n"
            f"رکوردهای تحت تأثیر: {preview.get('recordings_affected', 0)}\n"
            f"فایل‌های ثبت‌شده: {preview.get('audio_files_affected', 0)}\n\n"
            "یک نسخه پشتیبان و امکان بازگشت ساخته می‌شود.\n"
            "هیچ درخواست اینترنتی یا تغییر MP3 انجام نمی‌شود.\n\nادامه می‌دهید؟",
            parent=self.root,
        ):
            return
        reason = clean_text(self.alias_reason_var.get()) or "یکسان‌سازی نام هنرمند"

        def done(result: dict[str, Any]) -> None:
            self._show_alias_preview({
                "canonical_artist": result.get("canonical_artist"),
                "aliases": aliases,
                "recordings_affected": result.get("recordings_merged", 0),
                "audio_files_affected": result.get("audio_files_moved", 0),
                "source_folders": result.get("source_folders") or [],
                "conflicts": [],
            })
            messagebox.showinfo(
                "نام‌ها یکسان شدند",
                f"نام اصلی: {result.get('canonical_artist')}\n"
                f"رکوردهای ادغام‌شده: {result.get('recordings_merged', 0)}\n"
                f"اتصال فایل‌های منتقل‌شده: {result.get('audio_files_moved', 0)}\n\n"
                "در بخش تاریخچه امکان بازگشت وجود دارد.",
                parent=self.root,
            )
            self.refresh_alias_groups()
            self.refresh_review_queue()
            self.refresh_history()

        self._run_async(
            "در حال یکسان‌سازی نام هنرمند…",
            lambda: self.controller.apply_artist_aliases(canonical, aliases, reason=reason),
            done,
        )
