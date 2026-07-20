#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Application composition for the Persian Avachin desktop UI."""

from __future__ import annotations

import queue
import tkinter as tk
from typing import Any

from tools.artist_alias_controller import ArtistAliasController
from tools.gui_controller import PreviewController
from tools.persian_ui_alias import AliasPageMixin
from tools.persian_ui_base import PersianUIBase
from tools.persian_ui_common import PALETTE, choose_persian_font, clean_text
from tools.persian_ui_history import HistoryPageMixin
from tools.persian_ui_home import HomePageMixin
from tools.persian_ui_review import ReviewPageMixin
from tools.version import AVACHIN_VERSION


class PersianMaterialApp(
    HomePageMixin,
    ReviewPageMixin,
    AliasPageMixin,
    HistoryPageMixin,
    PersianUIBase,
):
    def __init__(
        self,
        root: tk.Tk,
        *,
        preview_controller: PreviewController | None = None,
        review_controller: ArtistAliasController | None = None,
        initial_folder: str = "",
        initial_report: str = "",
    ) -> None:
        self.root = root
        self.preview_controller = preview_controller or PreviewController()
        self.controller = review_controller or ArtistAliasController()
        self.font_family = choose_persian_font(root)

        self.worker_events: queue.Queue[tuple[str, Any, Any]] = queue.Queue()
        self.preview_events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.pages: dict[str, tk.Frame] = {}
        self.nav_buttons: dict[str, tk.Button] = {}
        self.review_items: dict[str, dict[str, Any]] = {}
        self.alias_groups: dict[str, dict[str, Any]] = {}
        self.history_items: dict[str, dict[str, Any]] = {}
        self.artifact_buttons: list[tk.Button] = []
        self.latest_detection_report = clean_text(initial_report)

        self.folder_var = tk.StringVar(value=initial_folder)
        self.offline_var = tk.BooleanVar(value=True)
        self.global_status_var = tk.StringVar(value="آماده")
        self.preview_status_var = tk.StringVar(value="هنوز پیش‌نمایشی اجرا نشده است")
        self.preview_progress_var = tk.StringVar(value="برای شروع، پوشه موسیقی را انتخاب کنید")
        self.report_var = tk.StringVar(value=initial_report)
        self.review_count_var = tk.StringVar(value="در حال بارگذاری صف بررسی…")
        self.artist_var = tk.StringVar()
        self.title_var = tk.StringVar()
        self.album_var = tk.StringVar()
        self.reason_var = tk.StringVar(value="تأیید دستی کاربر")
        self.alias_canonical_var = tk.StringVar()
        self.alias_variants_var = tk.StringVar()
        self.alias_reason_var = tk.StringVar(value="یکسان‌سازی نام‌های مختلف یک هنرمند")
        self.alias_status_var = tk.StringVar(value="در حال جست‌وجوی نام‌های مشابه…")

        self.root.title(f"آواچین {AVACHIN_VERSION} — مدیریت هوشمند موسیقی")
        self.root.geometry("1320x840")
        self.root.minsize(1080, 700)
        self.root.configure(bg=PALETTE["background"])
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.option_add("*Font", (self.font_family, 10))
        self.root.option_add("*tearOff", False)

        self._configure_styles()
        self._install_clipboard_support()
        self._build_shell()
        self._show_page("home")
        self.root.after(100, self._drain_worker_events)
        self.root.after(100, self._drain_preview_events)
        self._load_runtime_status()
        self.refresh_review_queue()
        self.refresh_alias_groups()
        self.refresh_history()
