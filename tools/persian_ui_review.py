#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Review queue page for the Persian Avachin UI."""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any

from tools.persian_ui_common import DECISION_LABELS, PALETTE, clean_text


class ReviewPageMixin:
    def _build_review_page(self, page: tk.Frame) -> None:
        self._section_intro(
            page,
            "موارد نیازمند بررسی",
            "نتیجه آنلاین فقط پیشنهاد است؛ پس از گوش‌دادن و تأیید شما در بانک محلی ثبت می‌شود.",
        )

        report_card = self._card(page)
        report_card.pack(fill="x")
        report_inner = tk.Frame(report_card, bg=PALETTE["surface"])
        report_inner.pack(fill="x", padx=16, pady=14)
        self._flat_button(report_inner, "به‌روزرسانی", self.refresh_review_queue).pack(side="right")
        self._flat_button(report_inner, "انتخاب گزارش", self._browse_report).pack(side="right", padx=(0, 8))
        ttk.Entry(report_inner, textvariable=self.report_var, justify="right").pack(
            side="right", fill="x", expand=True, padx=(0, 10)
        )
        tk.Label(
            report_inner,
            textvariable=self.review_count_var,
            bg=PALETTE["surface"],
            fg=PALETTE["cyan"],
            font=(self.font_family, 9, "bold"),
            anchor="w",
        ).pack(side="left")

        body = tk.PanedWindow(
            page, orient="vertical", sashwidth=6, bg=PALETTE["background"], bd=0, relief="flat"
        )
        body.pack(fill="both", expand=True, pady=(14, 0))

        table_card = self._card(body)
        table_inner = tk.Frame(table_card, bg=PALETTE["surface"])
        table_inner.pack(fill="both", expand=True, padx=12, pady=12)
        columns = ("decision", "artist", "title", "confidence", "provider", "path")
        self.review_tree = ttk.Treeview(table_inner, columns=columns, show="headings", selectmode="browse")
        headers = {
            "decision": "وضعیت", "artist": "هنرمند", "title": "عنوان",
            "confidence": "اطمینان", "provider": "منبع", "path": "مسیر فایل",
        }
        widths = {
            "decision": 110, "artist": 160, "title": 190,
            "confidence": 80, "provider": 105, "path": 420,
        }
        for column in columns:
            self.review_tree.heading(column, text=headers[column], anchor="e")
            self.review_tree.column(column, width=widths[column], anchor="e")
        review_scroll = ttk.Scrollbar(table_inner, orient="vertical", command=self.review_tree.yview)
        self.review_tree.configure(yscrollcommand=review_scroll.set)
        review_scroll.pack(side="left", fill="y")
        self.review_tree.pack(side="right", fill="both", expand=True)
        self.review_tree.bind("<<TreeviewSelect>>", self._review_selected)

        form_card = self._card(body)
        form_inner = tk.Frame(form_card, bg=PALETTE["surface"])
        form_inner.pack(fill="both", expand=True, padx=16, pady=14)
        form_grid = tk.Frame(form_inner, bg=PALETTE["surface"])
        form_grid.pack(fill="x")
        fields = (("هنرمند", self.artist_var), ("عنوان آهنگ", self.title_var), ("آلبوم", self.album_var))
        for index, (label, variable) in enumerate(fields):
            cell = tk.Frame(form_grid, bg=PALETTE["surface"])
            cell.pack(side="right", fill="x", expand=True, padx=(0 if index == 0 else 10, 0))
            tk.Label(
                cell, text=label, bg=PALETTE["surface"], fg=PALETTE["muted"],
                font=(self.font_family, 9), anchor="e"
            ).pack(fill="x")
            ttk.Entry(cell, textvariable=variable, justify="right").pack(fill="x", pady=(5, 0))

        tk.Label(
            form_inner, text="دلیل تأیید یا اصلاح", bg=PALETTE["surface"],
            fg=PALETTE["muted"], font=(self.font_family, 9), anchor="e"
        ).pack(fill="x", pady=(10, 0))
        ttk.Entry(form_inner, textvariable=self.reason_var, justify="right").pack(fill="x", pady=(5, 0))

        actions = tk.Frame(form_inner, bg=PALETTE["surface"])
        actions.pack(fill="x", pady=(12, 0))
        self._flat_button(actions, "تأیید و ثبت در بانک محلی", self._apply_review_identity, kind="success").pack(side="right")
        self._flat_button(actions, "شناسایی آنلاین این فایل", self._identify_selected_online, kind="primary").pack(side="right", padx=(0, 8))
        self._flat_button(actions, "پخش فایل", self._play_selected_review).pack(side="right", padx=(0, 8))
        self._flat_button(actions, "شناسایی آنلاین همه", self._identify_all_online).pack(side="left")

        body.add(table_card, minsize=250)
        body.add(form_card, minsize=210)

    def _browse_report(self) -> None:
        selected = filedialog.askopenfilename(
            title="انتخاب گزارش شناسایی",
            filetypes=(("گزارش JSON", "*.json"), ("همه فایل‌ها", "*.*")),
        )
        if selected:
            self.report_var.set(selected)
            self.latest_detection_report = selected
            self.refresh_review_queue()

    def refresh_review_queue(self) -> None:
        report = self.report_var.get().strip() or self.latest_detection_report or None
        self._run_async("در حال بارگذاری صف بررسی…", lambda: self.controller.queue(report), self._show_review_queue)

    def _show_review_queue(self, result: dict[str, Any]) -> None:
        for item in self.review_tree.get_children():
            self.review_tree.delete(item)
        self.review_items.clear()
        report_path = clean_text(result.get("report_path"))
        if report_path:
            self.report_var.set(report_path)
            self.latest_detection_report = report_path

        items = list(result.get("items") or [])
        for index, raw in enumerate(items):
            item = dict(raw)
            key = f"review-{index}"
            self.review_items[key] = item
            decision = clean_text(item.get("decision")).upper()
            confidence = item.get("overall_confidence")
            confidence_text = "" if confidence in (None, "") else f"{float(confidence):.1f}%"
            self.review_tree.insert(
                "", "end", iid=key,
                values=(
                    DECISION_LABELS.get(decision, decision), clean_text(item.get("artist")),
                    clean_text(item.get("title")), confidence_text,
                    clean_text(item.get("provider")), clean_text(item.get("source_path")),
                ),
            )
        resolved = int(result.get("resolved_count") or 0)
        self.review_count_var.set(
            f"{len(items)} مورد نیازمند بررسی" + (f" — {resolved} مورد تأییدشده پنهان است" if resolved else "")
        )
        if items:
            first = self.review_tree.get_children()[0]
            self.review_tree.selection_set(first)
            self.review_tree.focus(first)
            self._review_selected()
        else:
            self.artist_var.set("")
            self.title_var.set("")
            self.album_var.set("")

    def _selected_review(self) -> tuple[str, dict[str, Any] | None]:
        selected = self.review_tree.selection()
        key = selected[0] if selected else ""
        return key, self.review_items.get(key)

    def _review_selected(self, _event: Any = None) -> None:
        _key, item = self._selected_review()
        if not item:
            return
        self.artist_var.set(clean_text(item.get("artist")))
        self.title_var.set(clean_text(item.get("title")))
        self.album_var.set(clean_text(item.get("album")))
        self.reason_var.set(clean_text(item.get("reason")) or "تأیید دستی پس از گوش‌دادن")

    def _play_selected_review(self) -> None:
        _key, item = self._selected_review()
        if not item:
            messagebox.showwarning("فایلی انتخاب نشده", "یک ردیف را از جدول انتخاب کنید.", parent=self.root)
            return
        self._open_path(clean_text(item.get("source_path")))

    def _identify_selected_online(self) -> None:
        key, item = self._selected_review()
        if not item:
            messagebox.showwarning("فایلی انتخاب نشده", "یک مورد را برای شناسایی انتخاب کنید.", parent=self.root)
            return
        if not bool(item.get("online_lookup_allowed")):
            messagebox.showwarning("شناسایی آنلاین در دسترس نیست", "فایل وجود ندارد یا نمونه آزمایشی Benchmark است.", parent=self.root)
            return
        if not messagebox.askyesno(
            "شناسایی آنلاین",
            "ابتدا AcoustID و منابع رایگان بررسی می‌شوند و AudD فقط در صورت نیاز استفاده می‌شود.\n\n"
            "نتیجه فقط پیشنهاد است و تا زمان تأیید شما ذخیره نمی‌شود.\n\nادامه می‌دهید؟",
            parent=self.root,
        ):
            return
        path = clean_text(item.get("source_path"))

        def done(result: dict[str, Any]) -> None:
            if clean_text(result.get("status")) != "suggested":
                errors = "\n".join(str(value) for value in result.get("errors") or [])
                messagebox.showwarning(
                    "نتیجه مطمئنی پیدا نشد",
                    "فایل همچنان در صف بررسی باقی می‌ماند." + (f"\n\n{errors}" if errors else ""),
                    parent=self.root,
                )
                return
            item.update({
                "artist": clean_text(result.get("artist")),
                "title": clean_text(result.get("title")),
                "album": clean_text(result.get("album")),
                "provider": clean_text(result.get("provider")),
                "overall_confidence": float(result.get("confidence") or 0.0),
                "online_suggestion": dict(result),
            })
            self.artist_var.set(item["artist"])
            self.title_var.set(item["title"])
            self.album_var.set(item["album"])
            self.reason_var.set(f"پیشنهاد آنلاین از {item['provider']}؛ تأیید پس از گوش‌دادن")
            self._update_review_row(key, item)
            messagebox.showinfo(
                "پیشنهاد آنلاین پیدا شد",
                f"{item['artist']} — {item['title']}\n\nمنبع: {item['provider']}\n"
                f"اطمینان: {float(item['overall_confidence']):.1f}%\n\n"
                "فایل را پخش کنید و فقط در صورت درست‌بودن، دکمه تأیید را بزنید.",
                parent=self.root,
            )

        self._run_async("در حال شناسایی آنلاین…", lambda: self.controller.identify_online(path), done)

    def _identify_all_online(self) -> None:
        targets = [
            (key, item) for key, item in self.review_items.items()
            if bool(item.get("online_lookup_allowed"))
            and clean_text((item.get("online_suggestion") or {}).get("status")) != "suggested"
        ]
        if not targets:
            messagebox.showinfo("موردی باقی نمانده", "هیچ فایل واقعیِ واجد شرایطی برای شناسایی آنلاین وجود ندارد.", parent=self.root)
            return
        if not messagebox.askyesno(
            "شناسایی گروهی",
            f"{len(targets)} فایل بررسی می‌شود.\n"
            "AudD فقط پس از شکست روش‌های رایگان و با سقف بودجه استفاده خواهد شد.\n\n"
            "هیچ نتیجه‌ای خودکار ذخیره نمی‌شود. ادامه می‌دهید؟",
            parent=self.root,
        ):
            return

        def operation() -> list[tuple[str, dict[str, Any]]]:
            results: list[tuple[str, dict[str, Any]]] = []
            for key, item in targets:
                try:
                    result = self.controller.identify_online(clean_text(item.get("source_path")))
                except Exception as exc:
                    result = {"status": "failed", "errors": [str(exc)]}
                results.append((key, result))
            return results

        def done(results: list[tuple[str, dict[str, Any]]]) -> None:
            found = 0
            failed = 0
            for key, result in results:
                item = self.review_items.get(key)
                if item is None:
                    continue
                if clean_text(result.get("status")) == "suggested":
                    item.update({
                        "artist": clean_text(result.get("artist")),
                        "title": clean_text(result.get("title")),
                        "album": clean_text(result.get("album")),
                        "provider": clean_text(result.get("provider")),
                        "overall_confidence": float(result.get("confidence") or 0.0),
                        "online_suggestion": dict(result),
                    })
                    self._update_review_row(key, item)
                    found += 1
                else:
                    failed += 1
            messagebox.showinfo(
                "شناسایی گروهی تمام شد",
                f"پیشنهاد پیدا شد: {found}\nبدون نتیجه یا ناموفق: {failed}\n\nهر مورد باید جداگانه پخش و تأیید شود.",
                parent=self.root,
            )

        self._run_async("در حال شناسایی گروهی…", operation, done)

    def _update_review_row(self, key: str, item: dict[str, Any]) -> None:
        if not self.review_tree.exists(key):
            return
        confidence = item.get("overall_confidence")
        confidence_text = "" if confidence in (None, "") else f"{float(confidence):.1f}%"
        decision = clean_text(item.get("decision")).upper()
        self.review_tree.item(
            key,
            values=(
                DECISION_LABELS.get(decision, decision), clean_text(item.get("artist")),
                clean_text(item.get("title")), confidence_text,
                clean_text(item.get("provider")), clean_text(item.get("source_path")),
            ),
        )

    def _apply_review_identity(self) -> None:
        _key, item = self._selected_review()
        if not item:
            messagebox.showwarning("فایلی انتخاب نشده", "یک مورد را برای تأیید انتخاب کنید.", parent=self.root)
            return
        path = clean_text(item.get("source_path"))
        artist = clean_text(self.artist_var.get())
        title = clean_text(self.title_var.get())
        album = clean_text(self.album_var.get())
        reason = clean_text(self.reason_var.get()) or "تأیید دستی کاربر"
        if not artist or not title:
            messagebox.showwarning("اطلاعات ناقص است", "نام هنرمند و عنوان آهنگ باید وارد شوند.", parent=self.root)
            return
        if not messagebox.askyesno(
            "تأیید اطلاعات آهنگ",
            f"هنرمند: {artist}\nعنوان: {title}\nآلبوم: {album or '—'}\n\n"
            "یک نسخه پشتیبان از بانک محلی ساخته می‌شود و امکان بازگشت وجود دارد.\n"
            "خود فایل موسیقی تغییر نمی‌کند.\n\nاطلاعات ثبت شود؟",
            parent=self.root,
        ):
            return

        def operation() -> dict[str, Any]:
            rows = self.controller.find_path(path)
            if rows:
                return self.controller.reassign(
                    int(rows[0]["id"]), artist=artist, title=title, album=album, reason=reason
                )
            return self.controller.learn_rejected_file(
                path, artist=artist, title=title, album=album, reason=reason
            )

        def done(_result: dict[str, Any]) -> None:
            messagebox.showinfo(
                "اطلاعات ثبت شد",
                "این فایل از صف بررسی خارج شد.\nپشتیبان بانک محلی و سابقه بازگشت نیز ساخته شد.",
                parent=self.root,
            )
            self.refresh_review_queue()
            self.refresh_alias_groups()
            self.refresh_history()

        self._run_async("در حال ثبت اطلاعات تأییدشده…", operation, done)
