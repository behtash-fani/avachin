#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Home and Preview page for the Persian Avachin UI."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from typing import Any

from tools.avachin_operation import OperationEvent
from tools.persian_ui_common import PALETTE, clean_text


class HomePageMixin:
    def _build_home_page(self, page: tk.Frame) -> None:
        self._section_intro(
            page,
            "پیش‌نمایش آرشیو موسیقی",
            "پوشه را انتخاب کنید؛ آواچین فقط نتیجه پیشنهادی و گزارش می‌سازد و فایل‌ها را تغییر نمی‌دهد.",
        )

        status_row = tk.Frame(page, bg=PALETTE["background"])
        status_row.pack(fill="x")
        self.status_value_labels: dict[str, tk.Label] = {}
        status_defs = (
            ("fingerprint", "ابزار تشخیص"),
            ("repair", "تعمیر صدای خراب"),
            ("database", "بانک محلی"),
            ("budget", "سهمیه آنلاین"),
        )
        for index, (key, title) in enumerate(status_defs):
            card = self._card(status_row)
            card.pack(side="right", fill="x", expand=True, padx=(8 if index else 0, 0))
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
        choose_card.pack(fill="x", pady=(14, 0))
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
            text="پوشه اصلی آرشیو یا یک پوشه آزمایشی کوچک را انتخاب کنید.",
            bg=PALETTE["surface"],
            fg=PALETTE["muted"],
            font=(self.font_family, 9),
            anchor="e",
        ).pack(fill="x", pady=(3, 10))

        folder_row = tk.Frame(choose_inner, bg=PALETTE["surface"])
        folder_row.pack(fill="x")
        self._flat_button(folder_row, "انتخاب پوشه", self._browse_folder).pack(side="right")
        self.folder_entry = ttk.Entry(folder_row, textvariable=self.folder_var, justify="right")
        self.folder_entry.pack(side="right", fill="x", expand=True, padx=(0, 10))

        options = tk.Frame(choose_inner, bg=PALETTE["surface"])
        options.pack(fill="x", pady=(12, 0))
        ttk.Checkbutton(
            options,
            text="حالت آفلاین؛ فقط بانک محلی استفاده شود (پیشنهادشده)",
            variable=self.offline_var,
        ).pack(side="right")
        self._flat_button(options, "به‌روزرسانی وضعیت", self._load_runtime_status).pack(side="left")

        action_row = tk.Frame(page, bg=PALETTE["background"])
        action_row.pack(fill="x", pady=(14, 0))
        self.start_preview_button = self._flat_button(
            action_row, "شروع پیش‌نمایش", self._start_preview, kind="primary"
        )
        self.start_preview_button.pack(side="right")
        self.cancel_preview_button = self._flat_button(
            action_row, "توقف امن", self._cancel_preview, kind="danger"
        )
        self.cancel_preview_button.pack(side="right", padx=(0, 10))
        self.cancel_preview_button.configure(state="disabled")
        tk.Label(
            action_row,
            textvariable=self.preview_status_var,
            bg=PALETTE["background"],
            fg=PALETTE["cyan"],
            font=(self.font_family, 10, "bold"),
            anchor="w",
        ).pack(side="left")

        progress_card = self._card(page)
        progress_card.pack(fill="x", pady=(14, 0))
        progress_inner = tk.Frame(progress_card, bg=PALETTE["surface"])
        progress_inner.pack(fill="x", padx=18, pady=14)
        self.preview_progress = ttk.Progressbar(progress_inner, mode="determinate", maximum=100)
        self.preview_progress.pack(fill="x")
        tk.Label(
            progress_inner,
            textvariable=self.preview_progress_var,
            bg=PALETTE["surface"],
            fg=PALETTE["muted"],
            font=(self.font_family, 9),
            anchor="e",
        ).pack(fill="x", pady=(8, 0))

        bottom = tk.PanedWindow(
            page,
            orient="horizontal",
            sashwidth=6,
            bg=PALETTE["background"],
            bd=0,
            relief="flat",
        )
        bottom.pack(fill="both", expand=True, pady=(14, 0))

        report_card = self._card(bottom)
        report_inner = tk.Frame(report_card, bg=PALETTE["surface"])
        report_inner.pack(fill="both", expand=True, padx=16, pady=14)
        tk.Label(
            report_inner,
            text="گزارش‌های آخرین اجرا",
            bg=PALETTE["surface"],
            fg=PALETTE["text"],
            font=(self.font_family, 11, "bold"),
            anchor="e",
        ).pack(fill="x")
        self.artifact_frame = tk.Frame(report_inner, bg=PALETTE["surface"])
        self.artifact_frame.pack(fill="both", expand=True, pady=(10, 0))
        self.no_artifact_label = tk.Label(
            self.artifact_frame,
            text="پس از پایان پیش‌نمایش، دکمه‌های گزارش اینجا ظاهر می‌شوند.",
            bg=PALETTE["surface"],
            fg=PALETTE["muted"],
            font=(self.font_family, 9),
            justify="right",
            anchor="e",
        )
        self.no_artifact_label.pack(fill="x")

        log_card = self._card(bottom)
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
        self.preview_log = ScrolledText(
            log_inner,
            wrap="word",
            height=10,
            state="disabled",
            bg=PALETTE["black"],
            fg=PALETTE["text"],
            insertbackground=PALETTE["text"],
            selectbackground=PALETTE["primary_dark"],
            relief="flat",
            bd=0,
            padx=10,
            pady=10,
            font=(self.font_family, 9),
        )
        self.preview_log.pack(fill="both", expand=True, pady=(10, 0))
        bottom.add(report_card, minsize=320)
        bottom.add(log_card, minsize=430)

    def _load_runtime_status(self) -> None:
        def done(status: dict[str, Any]) -> None:
            tools = status.get("tools") or {}
            fpcalc_ready = bool((tools.get("fpcalc") or {}).get("available"))
            ffmpeg_ready = bool((tools.get("ffmpeg") or {}).get("available"))
            fingerprints = status.get("fingerprints") or {}
            budget = status.get("audd_budget") or {}
            self.status_value_labels["fingerprint"].configure(
                text="آماده" if fpcalc_ready else "نصب نشده",
                fg=PALETTE["success"] if fpcalc_ready else PALETTE["danger"],
            )
            self.status_value_labels["repair"].configure(
                text="آماده" if ffmpeg_ready else "نصب نشده",
                fg=PALETTE["success"] if ffmpeg_ready else PALETTE["warning"],
            )
            if fingerprints.get("exists") and not fingerprints.get("error"):
                value = f"{fingerprints.get('recordings', 0)} آهنگ"
                color = PALETTE["success"]
            else:
                value = "هنوز آماده نیست"
                color = PALETTE["warning"]
            self.status_value_labels["database"].configure(text=value, fg=color)
            self.status_value_labels["budget"].configure(
                text=f"{budget.get('remaining', 0)} درخواست باقی‌مانده",
                fg=PALETTE["cyan"],
            )
            warnings = status.get("warnings") or []
            self.global_status_var.set("آماده" if not warnings else f"آماده با {len(warnings)} هشدار")
            for warning in warnings:
                self._append_preview_log(f"هشدار: {warning}")

        self._run_async("در حال بررسی وضعیت…", self.preview_controller.status, done)

    def _browse_folder(self) -> None:
        initial = self.folder_var.get().strip()
        selected = filedialog.askdirectory(
            title="انتخاب پوشه موسیقی",
            initialdir=initial if Path(initial).is_dir() else str(Path.home()),
        )
        if selected:
            self.folder_var.set(selected)

    def _start_preview(self) -> None:
        folder = self.folder_var.get().strip()
        if not folder:
            messagebox.showwarning("پوشه انتخاب نشده", "ابتدا پوشه موسیقی را انتخاب کنید.", parent=self.root)
            return
        if not Path(folder).is_dir():
            messagebox.showerror("پوشه نامعتبر", "مسیر انتخاب‌شده وجود ندارد یا پوشه نیست.", parent=self.root)
            return

        self._clear_preview_log()
        self._reset_artifacts()
        self.preview_progress.configure(value=0)
        self.preview_progress_var.set("در حال آماده‌سازی پیش‌نمایش…")
        self.preview_status_var.set("در حال اجرا")
        self.global_status_var.set("در حال پیش‌نمایش")
        self.start_preview_button.configure(state="disabled")
        self.cancel_preview_button.configure(state="normal")
        self.folder_entry.configure(state="disabled")
        try:
            self.preview_controller.start_preview(
                folder,
                offline=self.offline_var.get(),
                event_callback=lambda event: self.preview_events.put(("event", event)),
                completion_callback=lambda result: self.preview_events.put(("completed", result)),
            )
        except Exception as exc:
            self._finish_preview_controls()
            messagebox.showerror("شروع پیش‌نمایش ناموفق بود", str(exc), parent=self.root)

    def _cancel_preview(self) -> None:
        if self.preview_controller.cancel():
            self.preview_status_var.set("در حال توقف امن…")
            self.cancel_preview_button.configure(state="disabled")
            self._append_preview_log("درخواست توقف ثبت شد؛ پردازش جداگانه با ایمنی متوقف می‌شود.")

    def _handle_preview_event(self, event: OperationEvent) -> None:
        if event.event_type == "artifact" and event.path:
            self._add_artifact(event.key, event.path)
            filename = Path(event.path).name.casefold()
            if filename in {"detection-report.json", "detection_report.json"}:
                self.latest_detection_report = event.path
                self.report_var.set(event.path)

        if event.current is not None and event.total:
            percent = max(0.0, min(100.0, event.current / event.total * 100.0))
            self.preview_progress.configure(value=percent)
            self.preview_progress_var.set(f"در حال پردازش فایل {event.current} از {event.total}")
        elif event.event_type == "phase":
            self.preview_progress_var.set(event.message or "در حال پردازش…")

        if event.message and event.event_type in {
            "phase", "progress", "warning", "error", "audio-repair", "summary",
            "started", "cancelling", "cancelled", "completed", "failed",
        }:
            self._append_preview_log(event.message)

    def _handle_preview_completed(self, result: dict[str, Any]) -> None:
        status = clean_text(result.get("status")) or "failed"
        if status == "completed":
            self.preview_progress.configure(value=100)
            self.preview_progress_var.set("پیش‌نمایش کامل شد؛ موارد نامطمئن را در بخش «بررسی آهنگ‌ها» ببینید.")
            self.preview_status_var.set("پیش‌نمایش با موفقیت تمام شد")
            self.global_status_var.set("پیش‌نمایش کامل شد")
            self.refresh_review_queue()
            messagebox.showinfo(
                "پیش‌نمایش کامل شد",
                "هیچ فایل موسیقی تغییر نکرد.\n\nبرای دیدن موارد نامطمئن وارد بخش «بررسی آهنگ‌ها» شوید.",
                parent=self.root,
            )
        elif status == "cancelled":
            self.preview_progress_var.set("پیش‌نمایش بدون تغییر فایل‌ها متوقف شد.")
            self.preview_status_var.set("متوقف شد")
            self.global_status_var.set("آماده")
        else:
            message = clean_text(result.get("error")) or "پیش‌نمایش ناموفق بود."
            self.preview_progress_var.set(message)
            self.preview_status_var.set("ناموفق")
            self.global_status_var.set("خطا")
        self._finish_preview_controls()

    def _finish_preview_controls(self) -> None:
        self.start_preview_button.configure(state="normal")
        self.cancel_preview_button.configure(state="disabled")
        self.folder_entry.configure(state="normal")

    def _append_preview_log(self, text: str) -> None:
        self.preview_log.configure(state="normal")
        self.preview_log.insert("end", clean_text(text) + "\n")
        self.preview_log.see("end")
        self.preview_log.configure(state="disabled")

    def _clear_preview_log(self) -> None:
        self.preview_log.configure(state="normal")
        self.preview_log.delete("1.0", "end")
        self.preview_log.configure(state="disabled")

    def _reset_artifacts(self) -> None:
        for button in self.artifact_buttons:
            button.destroy()
        self.artifact_buttons.clear()
        self.no_artifact_label.pack(fill="x")

    def _add_artifact(self, key: str, path: str) -> None:
        self.no_artifact_label.pack_forget()
        filename = Path(path).name.casefold()
        if filename in {"detection-report.json", "detection_report.json"}:
            title = "بازکردن گزارش شناسایی"
        elif filename.endswith(".csv"):
            title = "بازکردن گزارش CSV"
        elif "operation" in filename:
            title = "بازکردن گزارش عملیات"
        else:
            title = f"بازکردن {Path(path).name}"
        button = self._flat_button(self.artifact_frame, title, lambda value=path: self._open_path(value))
        button.pack(fill="x", pady=4)
        self.artifact_buttons.append(button)
        parent = str(Path(path).expanduser().resolve().parent)
        if not any(str(item.cget("text")) == "بازکردن پوشه گزارش‌ها" for item in self.artifact_buttons):
            folder_button = self._flat_button(
                self.artifact_frame,
                "بازکردن پوشه گزارش‌ها",
                lambda value=parent: self._open_path(value),
            )
            folder_button.pack(fill="x", pady=4)
            self.artifact_buttons.append(folder_button)
