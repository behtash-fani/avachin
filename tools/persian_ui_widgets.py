#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reusable layout primitives for the Persian Avachin desktop UI."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Mapping, Sequence

from tools.persian_ui_common import PALETTE


class ScrollablePage(tk.Frame):
    """A vertically scrollable page that tracks the available width."""

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent, bg=PALETTE["background"])
        self.canvas = tk.Canvas(self, bg=PALETTE["background"], highlightthickness=0, bd=0)
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


def build_scrollable_tree(
    parent: tk.Misc,
    *,
    columns: Sequence[str],
    headings: Mapping[str, str],
    widths: Mapping[str, int],
    anchors: Mapping[str, str] | None = None,
    displaycolumns: Sequence[str] | None = None,
    height: int = 11,
) -> tuple[tk.Frame, ttk.Treeview]:
    frame = tk.Frame(parent, bg=PALETTE["surface"])
    frame.grid_rowconfigure(0, weight=1)
    frame.grid_columnconfigure(1, weight=1)
    tree = ttk.Treeview(frame, columns=tuple(columns), show="headings", selectmode="browse", height=height)
    if displaycolumns is not None:
        tree.configure(displaycolumns=tuple(displaycolumns))
    anchors = anchors or {}
    for column in columns:
        anchor = anchors.get(column, "e")
        tree.heading(column, text=headings[column], anchor=anchor)
        tree.column(column, width=int(widths[column]), minwidth=70, anchor=anchor, stretch=False)
    ybar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview, style="Avachin.Vertical.TScrollbar")
    xbar = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview, style="Avachin.Horizontal.TScrollbar")
    tree.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
    ybar.grid(row=0, column=0, sticky="ns")
    tree.grid(row=0, column=1, sticky="nsew")
    xbar.grid(row=1, column=1, sticky="ew")
    return frame, tree
