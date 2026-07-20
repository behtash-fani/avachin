#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Base shell and shared behavior for the Persian Avachin UI."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

from tools.persian_ui_common import PALETTE, open_local_path
from tools.version import AVACHIN_VERSION


class PersianUIBase:
    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        regular = (self.font_family, 10)
        medium = (self.font_family, 10, "bold")
        heading = (self.font_family, 11, "bold")

        style.configure(
            ".",
            font=regular,
            background=PALETTE["background"],
            foreground=PALETTE["text"],
        )
        style.configure("TFrame", background=PALETTE["background"])
        style.configure("Card.TFrame", background=PALETTE["surface"])
        style.configure(
            "TLabel",
            background=PALETTE["background"],
            foreground=PALETTE["text"],
            anchor="e",
            justify="right",
        )
        style.configure(
            "Card.TLabel",
            background=PALETTE["surface"],
            foreground=PALETTE["text"],
            anchor="e",
            justify="right",
        )
        style.configure(
            "Muted.TLabel",
            background=PALETTE["background"],
            foreground=PALETTE["muted"],
            anchor="e",
            justify="right",
        )
        style.configure(
            "CardMuted.TLabel",
            background=PALETTE["surface"],
            foreground=PALETTE["muted"],
            anchor="e",
            justify="right",
        )
        style.configure(
            "Title.TLabel",
            background=PALETTE["background"],
            foreground=PALETTE["text"],
            font=(self.font_family, 22, "bold"),
            anchor="e",
        )
        style.configure(
            "Section.TLabel",
            background=PALETTE["background"],
            foreground=PALETTE["text"],
            font=(self.font_family, 15, "bold"),
            anchor="e",
        )
        style.configure(
            "CardTitle.TLabel",
            background=PALETTE["surface"],
            foreground=PALETTE["text"],
            font=heading,
            anchor="e",
        )
        style.configure(
            "Success.TLabel",
            background=PALETTE["surface"],
            foreground=PALETTE["success"],
            font=medium,
            anchor="e",
        )
        style.configure(
            "Warning.TLabel",
            background=PALETTE["surface"],
            foreground=PALETTE["warning"],
            font=medium,
            anchor="e",
        )
        style.configure(
            "TEntry",
            fieldbackground=PALETTE["card"],
            foreground=PALETTE["text"],
            insertcolor=PALETTE["text"],
            bordercolor=PALETTE["border"],
            lightcolor=PALETTE["border"],
            darkcolor=PALETTE["border"],
            padding=9,
        )
        style.map(
            "TEntry",
            bordercolor=[("focus", PALETTE["primary"])],
            lightcolor=[("focus", PALETTE["primary"])],
            darkcolor=[("focus", PALETTE["primary"])],
        )
        style.configure(
            "TCombobox",
            fieldbackground=PALETTE["card"],
            background=PALETTE["card"],
            foreground=PALETTE["text"],
            arrowcolor=PALETTE["text"],
            padding=8,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", PALETTE["card"])],
            selectbackground=[("readonly", PALETTE["card"])],
            selectforeground=[("readonly", PALETTE["text"])],
        )
        style.configure(
            "TCheckbutton",
            background=PALETTE["surface"],
            foreground=PALETTE["text"],
            focuscolor=PALETTE["surface"],
            anchor="e",
        )
        style.map(
            "TCheckbutton",
            background=[("active", PALETTE["surface"])],
            foreground=[("active", PALETTE["text"])],
            indicatorcolor=[
                ("selected", PALETTE["primary"]),
                ("!selected", PALETTE["card"]),
            ],
        )
        style.configure(
            "Treeview",
            background=PALETTE["surface"],
            fieldbackground=PALETTE["surface"],
            foreground=PALETTE["text"],
            bordercolor=PALETTE["border"],
            rowheight=34,
            font=regular,
        )
        style.map(
            "Treeview",
            background=[("selected", PALETTE["primary"])],
            foreground=[("selected", PALETTE["black"])],
        )
        style.configure(
            "Treeview.Heading",
            background=PALETTE["card"],
            foreground=PALETTE["text"],
            relief="flat",
            font=heading,
            padding=(8, 10),
        )
        style.map(
            "Treeview.Heading",
            background=[("active", PALETTE["card_hover"])],
        )
        style.configure(
            "Horizontal.TProgressbar",
            troughcolor=PALETTE["card"],
            background=PALETTE["primary"],
            bordercolor=PALETTE["surface"],
            lightcolor=PALETTE["primary"],
            darkcolor=PALETTE["primary"],
            thickness=12,
        )

    def _build_shell(self) -> None:
        shell = tk.Frame(self.root, bg=PALETTE["background"])
        shell.pack(fill="both", expand=True)

        sidebar = tk.Frame(shell, bg=PALETTE["black"], width=250)
        sidebar.pack(side="right", fill="y")
        sidebar.pack_propagate(False)

        brand = tk.Frame(sidebar, bg=PALETTE["black"])
        brand.pack(fill="x", padx=20, pady=(26, 20))
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
            font=(self.font_family, 10),
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
        nav.pack(fill="x", padx=12)
        for key, title in nav_items:
            button = tk.Button(
                nav,
                text=title,
                command=lambda value=key: self._show_page(value),
                anchor="e",
                justify="right",
                relief="flat",
                bd=0,
                padx=18,
                pady=13,
                cursor="hand2",
                font=(self.font_family, 11, "bold"),
                bg=PALETTE["black"],
                fg=PALETTE["muted"],
                activebackground=PALETTE["card"],
                activeforeground=PALETTE["text"],
            )
            button.pack(fill="x", pady=3)
            self.nav_buttons[key] = button

        safety = tk.Frame(sidebar, bg=PALETTE["black"])
        safety.pack(side="bottom", fill="x", padx=18, pady=20)
        tk.Label(
            safety,
            text="نسخه اولیه امن\nهیچ فایل موسیقی در این رابط\nحذف یا جابه‌جا نمی‌شود.",
            bg=PALETTE["black"],
            fg=PALETTE["success"],
            font=(self.font_family, 9, "bold"),
            justify="right",
            anchor="e",
        ).pack(fill="x")

        content = tk.Frame(shell, bg=PALETTE["background"])
        content.pack(side="left", fill="both", expand=True)

        header = tk.Frame(content, bg=PALETTE["background"], height=72)
        header.pack(fill="x", padx=28, pady=(18, 0))
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
            padx=14,
            pady=7,
        ).pack(side="left")

        self.page_host = tk.Frame(content, bg=PALETTE["background"])
        self.page_host.pack(fill="both", expand=True, padx=28, pady=(8, 24))

        for key in ("home", "review", "aliases", "history"):
            page = tk.Frame(self.page_host, bg=PALETTE["background"])
            page.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.pages[key] = page

        self._build_home_page(self.pages["home"])
        self._build_review_page(self.pages["review"])
        self._build_alias_page(self.pages["aliases"])
        self._build_history_page(self.pages["history"])

    def _show_page(self, key: str) -> None:
        titles = {
            "home": "خانه و پیش‌نمایش امن",
            "review": "بررسی و تأیید آهنگ‌ها",
            "aliases": "مدیریت نام‌های هنرمند",
            "history": "تاریخچه تغییرات و بازگشت",
        }
        page = self.pages[key]
        page.tkraise()
        self.page_title.configure(text=titles[key])
        for name, button in self.nav_buttons.items():
            active = name == key
            button.configure(
                bg=PALETTE["card"] if active else PALETTE["black"],
                fg=PALETTE["text"] if active else PALETTE["muted"],
            )

    def _card(self, parent: tk.Misc) -> tk.Frame:
        return tk.Frame(
            parent,
            bg=PALETTE["surface"],
            highlightthickness=1,
            highlightbackground=PALETTE["border"],
            bd=0,
        )

    def _flat_button(
        self,
        parent: tk.Misc,
        text: str,
        command: Callable[[], None],
        *,
        kind: str = "default",
        width: int | None = None,
    ) -> tk.Button:
        backgrounds = {
            "default": PALETTE["card"],
            "primary": PALETTE["primary"],
            "danger": PALETTE["danger"],
            "success": PALETTE["success"],
            "secondary": PALETTE["secondary"],
        }
        foregrounds = {
            "default": PALETTE["text"],
            "primary": PALETTE["black"],
            "danger": PALETTE["text"],
            "success": PALETTE["black"],
            "secondary": PALETTE["black"],
        }
        bg = backgrounds[kind]
        return tk.Button(
            parent,
            text=text,
            command=command,
            relief="flat",
            bd=0,
            padx=16,
            pady=10,
            cursor="hand2",
            width=width,
            bg=bg,
            fg=foregrounds[kind],
            activebackground=PALETTE["card_hover"] if kind == "default" else bg,
            activeforeground=foregrounds[kind],
            disabledforeground=PALETTE["muted"],
            font=(self.font_family, 10, "bold"),
        )

    def _section_intro(self, parent: tk.Misc, title: str, subtitle: str) -> None:
        wrapper = tk.Frame(parent, bg=PALETTE["background"])
        wrapper.pack(fill="x", pady=(0, 14))
        tk.Label(
            wrapper,
            text=title,
            bg=PALETTE["background"],
            fg=PALETTE["text"],
            font=(self.font_family, 15, "bold"),
            anchor="e",
        ).pack(fill="x")
        tk.Label(
            wrapper,
            text=subtitle,
            bg=PALETTE["background"],
            fg=PALETTE["muted"],
            font=(self.font_family, 10),
            justify="right",
            anchor="e",
        ).pack(fill="x", pady=(4, 0))

    def _run_async(
        self,
        label: str,
        function: Callable[[], Any],
        callback: Callable[[Any], None] | None = None,
    ) -> None:
        self.global_status_var.set(label)

        def worker() -> None:
            try:
                result = function()
                self.worker_events.put(("success", result, callback))
            except Exception as exc:
                self.worker_events.put(("error", exc, label))

        threading.Thread(target=worker, name="avachin-persian-ui-worker", daemon=True).start()

    def _drain_worker_events(self) -> None:
        while True:
            try:
                kind, payload, extra = self.worker_events.get_nowait()
            except queue.Empty:
                break
            if kind == "success":
                self.global_status_var.set("آماده")
                callback = extra
                if callback is not None:
                    try:
                        callback(payload)
                    except Exception as exc:
                        messagebox.showerror("نمایش نتیجه ناموفق بود", str(exc), parent=self.root)
            else:
                self.global_status_var.set("خطا")
                messagebox.showerror("عملیات ناموفق بود", str(payload), parent=self.root)
        self.root.after(100, self._drain_worker_events)

    def _drain_preview_events(self) -> None:
        while True:
            try:
                kind, payload = self.preview_events.get_nowait()
            except queue.Empty:
                break
            if kind == "event":
                self._handle_preview_event(payload)
            elif kind == "completed":
                self._handle_preview_completed(payload)
        self.root.after(100, self._drain_preview_events)

    def _open_path(self, value: str) -> None:
        try:
            open_local_path(value)
        except Exception as exc:
            messagebox.showerror("بازکردن مسیر ناموفق بود", str(exc), parent=self.root)

    def _install_clipboard_support(self) -> None:
        menu = tk.Menu(
            self.root,
            tearoff=False,
            bg=PALETTE["surface"],
            fg=PALETTE["text"],
            activebackground=PALETTE["primary"],
            activeforeground=PALETTE["black"],
        )
        target: dict[str, Any] = {"widget": None}

        def selected_text(widget: Any) -> str:
            try:
                return str(widget.selection_get()) if widget.selection_present() else ""
            except (AttributeError, tk.TclError):
                return ""

        def copy(widget: Any) -> str:
            value = selected_text(widget)
            if value:
                self.root.clipboard_clear()
                self.root.clipboard_append(value)
            return "break"

        def delete_selection(widget: Any) -> None:
            try:
                if widget.selection_present():
                    widget.delete("sel.first", "sel.last")
            except (AttributeError, tk.TclError):
                pass

        def cut(widget: Any) -> str:
            copy(widget)
            delete_selection(widget)
            return "break"

        def paste(widget: Any) -> str:
            try:
                value = self.root.clipboard_get()
            except tk.TclError:
                return "break"
            delete_selection(widget)
            try:
                widget.insert("insert", value)
            except (AttributeError, tk.TclError):
                pass
            return "break"

        def select_all(widget: Any) -> str:
            try:
                widget.selection_range(0, "end")
                widget.icursor("end")
            except (AttributeError, tk.TclError):
                pass
            return "break"

        def current() -> Any:
            return target["widget"]

        menu.add_command(label="برش", command=lambda: cut(current()))
        menu.add_command(label="کپی", command=lambda: copy(current()))
        menu.add_command(label="چسباندن", command=lambda: paste(current()))
        menu.add_separator()
        menu.add_command(label="انتخاب همه", command=lambda: select_all(current()))

        def show_menu(event: Any) -> str:
            target["widget"] = event.widget
            menu.tk_popup(event.x_root, event.y_root)
            return "break"

        def keycode(event: Any) -> str | None:
            action = {65: select_all, 67: copy, 86: paste, 88: cut}.get(
                int(getattr(event, "keycode", -1))
            )
            return action(event.widget) if action else None

        for widget_class in ("TEntry", "Entry"):
            for sequence in ("<Control-v>", "<Control-V>", "<Shift-Insert>"):
                self.root.bind_class(widget_class, sequence, lambda event: paste(event.widget))
            for sequence in ("<Control-c>", "<Control-C>"):
                self.root.bind_class(widget_class, sequence, lambda event: copy(event.widget))
            for sequence in ("<Control-x>", "<Control-X>"):
                self.root.bind_class(widget_class, sequence, lambda event: cut(event.widget))
            for sequence in ("<Control-a>", "<Control-A>"):
                self.root.bind_class(widget_class, sequence, lambda event: select_all(event.widget))
            self.root.bind_class(widget_class, "<Control-KeyPress>", keycode, add="+")
            self.root.bind_class(widget_class, "<Button-3>", show_menu)

    def _on_close(self) -> None:
        if self.preview_controller.running:
            close = messagebox.askyesno(
                "پیش‌نمایش در حال اجراست",
                "ابتدا درخواست توقف امن ارسال شود و برنامه بسته شود؟",
                parent=self.root,
            )
            if not close:
                return
            self.preview_controller.cancel()
        self.root.destroy()
