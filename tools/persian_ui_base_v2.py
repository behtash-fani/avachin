#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Responsive shell for the Persian Avachin user application."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from tools.persian_ui_base import PersianUIBase
from tools.persian_ui_common import PALETTE
from tools.persian_ui_widgets import ScrollablePage
from tools.version import AVACHIN_VERSION


class ResponsivePersianUIBase(PersianUIBase):
    """Adds page scrolling, themed scrollbars and RTL navigation order."""

    def _configure_styles(self) -> None:
        super()._configure_styles()
        style = ttk.Style(self.root)
        for name, orientation in (
            ("Avachin.Vertical.TScrollbar", "vertical"),
            ("Avachin.Horizontal.TScrollbar", "horizontal"),
        ):
            style.configure(
                name,
                background=PALETTE["card"],
                troughcolor=PALETTE["black"],
                bordercolor=PALETTE["border"],
                arrowcolor=PALETTE["text"],
                relief="flat",
                width=14,
            )
            style.map(
                name,
                background=[("active", PALETTE["primary_dark"])],
                arrowcolor=[("active", PALETTE["text"])],
            )

    def _build_shell(self) -> None:
        self.page_scrolls: dict[str, ScrollablePage] = {}
        self.active_page_key = "home"

        shell = tk.Frame(self.root, bg=PALETTE["background"])
        shell.pack(fill="both", expand=True)

        sidebar = tk.Frame(shell, bg=PALETTE["black"], width=228)
        sidebar.pack(side="right", fill="y")
        sidebar.pack_propagate(False)

        brand = tk.Frame(sidebar, bg=PALETTE["black"])
        brand.pack(fill="x", padx=18, pady=(24, 18))
        tk.Label(
            brand,
            text="آواچین",
            bg=PALETTE["black"],
            fg=PALETTE["primary"],
            font=(self.font_family, 24, "bold"),
            anchor="e",
        ).pack(fill="x")
        tk.Label(
            brand,
            text="مدیریت هوشمند موسیقی",
            bg=PALETTE["black"],
            fg=PALETTE["muted"],
            font=(self.font_family, 9),
            anchor="e",
        ).pack(fill="x", pady=(2, 0))
        tk.Label(
            brand,
            text=f"نسخه {AVACHIN_VERSION}",
            bg=PALETTE["black"],
            fg=PALETTE["cyan"],
            font=(self.font_family, 9),
            anchor="e",
        ).pack(fill="x", pady=(5, 0))

        nav_items = (
            ("home", "خانه و پیش‌نمایش"),
            ("review", "بررسی آهنگ‌ها"),
            ("aliases", "نام‌های هنرمند"),
            ("history", "تاریخچه و بازگشت"),
        )
        nav = tk.Frame(sidebar, bg=PALETTE["black"])
        nav.pack(fill="x", padx=10)
        for number, (key, title) in enumerate(nav_items, start=1):
            button = tk.Button(
                nav,
                text=title,
                command=lambda value=key: self._show_page(value),
                anchor="e",
                justify="right",
                relief="flat",
                bd=0,
                padx=16,
                pady=13,
                cursor="hand2",
                font=(self.font_family, 10, "bold"),
                bg=PALETTE["black"],
                fg=PALETTE["muted"],
                activebackground=PALETTE["card"],
                activeforeground=PALETTE["text"],
            )
            button.pack(fill="x", pady=3)
            self.nav_buttons[key] = button
            self.root.bind(f"<Control-Key-{number}>", lambda _event, value=key: self._show_page(value))

        tk.Label(
            sidebar,
            text="نسخه اولیه امن\nدر این مرحله فایل‌های موسیقی\nحذف یا جابه‌جا نمی‌شوند.",
            bg=PALETTE["black"],
            fg=PALETTE["success"],
            font=(self.font_family, 9, "bold"),
            justify="right",
            anchor="e",
        ).pack(side="bottom", fill="x", padx=18, pady=20)

        content = tk.Frame(shell, bg=PALETTE["background"])
        content.pack(side="left", fill="both", expand=True)

        header = tk.Frame(content, bg=PALETTE["background"], height=68)
        header.pack(fill="x", padx=24, pady=(14, 0))
        header.pack_propagate(False)
        self.page_title = tk.Label(
            header,
            text="",
            bg=PALETTE["background"],
            fg=PALETTE["text"],
            font=(self.font_family, 20, "bold"),
            anchor="e",
        )
        self.page_title.pack(side="right", fill="x", expand=True)
        tk.Label(
            header,
            textvariable=self.global_status_var,
            bg=PALETTE["surface"],
            fg=PALETTE["cyan"],
            font=(self.font_family, 9, "bold"),
            padx=13,
            pady=7,
        ).pack(side="left")

        self.page_host = tk.Frame(content, bg=PALETTE["background"])
        self.page_host.pack(fill="both", expand=True, padx=(18, 24), pady=(4, 18))

        for key in ("home", "review", "aliases", "history"):
            page = ScrollablePage(self.page_host)
            page.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.pages[key] = page
            self.page_scrolls[key] = page

        self._build_home_page(self.page_scrolls["home"].content)
        self._build_review_page(self.page_scrolls["review"].content)
        self._build_alias_page(self.page_scrolls["aliases"].content)
        self._build_history_page(self.page_scrolls["history"].content)

        self.root.bind_all("<MouseWheel>", self._route_mousewheel, add="+")
        self.root.bind_all("<Button-4>", lambda event: self._route_linux_wheel(event, -1), add="+")
        self.root.bind_all("<Button-5>", lambda event: self._route_linux_wheel(event, 1), add="+")

    def _show_page(self, key: str) -> None:
        titles = {
            "home": "خانه و پیش‌نمایش امن",
            "review": "بررسی و تأیید آهنگ‌ها",
            "aliases": "مدیریت نام‌های هنرمند",
            "history": "تاریخچه تغییرات و بازگشت",
        }
        self.active_page_key = key
        self.pages[key].tkraise()
        self.page_title.configure(text=titles[key])
        for name, button in self.nav_buttons.items():
            active = name == key
            button.configure(
                bg=PALETTE["card"] if active else PALETTE["black"],
                fg=PALETTE["text"] if active else PALETTE["muted"],
            )

    @staticmethod
    def _widget_handles_own_scroll(widget: tk.Misc) -> bool:
        current: tk.Misc | None = widget
        while current is not None:
            if isinstance(current, (ttk.Treeview, tk.Text, tk.Listbox)):
                return True
            current = getattr(current, "master", None)
        return False

    def _route_mousewheel(self, event: tk.Event) -> str | None:
        if self._widget_handles_own_scroll(event.widget):
            return None
        delta = int(getattr(event, "delta", 0))
        if delta:
            self.page_scrolls[self.active_page_key].scroll_units(-1 if delta > 0 else 1)
            return "break"
        return None

    def _route_linux_wheel(self, event: tk.Event, direction: int) -> str | None:
        if self._widget_handles_own_scroll(event.widget):
            return None
        self.page_scrolls[self.active_page_key].scroll_units(direction)
        return "break"
