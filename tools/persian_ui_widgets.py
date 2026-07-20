#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reusable layout primitives for the Persian Avachin desktop UI."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from tools.persian_ui_common import PALETTE


class ScrollablePage(tk.Frame):
    """A vertically scrollable page that tracks the available width."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, bg=PALETTE["background"])
        self.canvas = tk.Canvas(
            self,
            bg=PALETTE["background"],
            highlightthickness=0,
            bd=0,
        )
        self.scrollbar = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
            style="Avachin.Vertical.TScrollbar",
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.scrollbar.pack(side="left", fill="y")
        self.canvas.pack(side="right", fill="both", expand=True)
        self.content = tk.Frame(self.canvas, bg=PALETTE["background"])
        self.window_id = self.canvas.create_window((0, 0), window=self.content, anchor="ne")
        self.content.bind("<Configure>", self._sync_scrollregion, add="+")
        self.canvas.bind("<Configure>", self._sync_width, add="+")

    def _sync_scrollregion(self, _event: object = None) -> None:
        bbox = self.canvas.bbox("all")
        if bbox:
            self.canvas.configure(scrollregion=bbox)

    def _sync_width(self, event: tk.Event) -> None:
        width = max(1, int(event.width))
        self.canvas.itemconfigure(self.window_id, width=width)
        self.canvas.coords(self.window_id, width, 0)

    def scroll_units(self, units: int) -> None:
        self.canvas.yview_scroll(units, "units")
