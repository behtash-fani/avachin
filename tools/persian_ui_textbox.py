#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Themed text area with horizontal and vertical scrolling."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from tools.persian_ui_common import PALETTE


def build_scrollable_text(
    parent: tk.Misc,
    *,
    height: int = 10,
    wrap: str = "none",
) -> tuple[tk.Frame, tk.Text]:
    frame = tk.Frame(parent, bg=PALETTE["surface"])
    frame.grid_rowconfigure(0, weight=1)
    frame.grid_columnconfigure(1, weight=1)
    text = tk.Text(
        frame,
        wrap=wrap,
        height=height,
        state="disabled",
        bg=PALETTE["black"],
        fg=PALETTE["text"],
        insertbackground=PALETTE["text"],
        selectbackground=PALETTE["primary_dark"],
        relief="flat",
        bd=0,
        padx=12,
        pady=10,
        undo=False,
    )
    ybar = ttk.Scrollbar(
        frame,
        orient="vertical",
        command=text.yview,
        style="Avachin.Vertical.TScrollbar",
    )
    xbar = ttk.Scrollbar(
        frame,
        orient="horizontal",
        command=text.xview,
        style="Avachin.Horizontal.TScrollbar",
    )
    text.configure(yscrollcommand=ybar.set, xscrollcommand=xbar.set)
    text.tag_configure("rtl", justify="right")
    text.tag_configure("ltr", justify="left")
    ybar.grid(row=0, column=0, sticky="ns")
    text.grid(row=0, column=1, sticky="nsew")
    xbar.grid(row=1, column=1, sticky="ew")
    return frame, text
