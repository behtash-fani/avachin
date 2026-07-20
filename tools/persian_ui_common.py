#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared Persian Material UI constants and helpers."""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from typing import Any

PALETTE = {
    "background": "#282A36",
    "surface": "#303341",
    "card": "#44475A",
    "card_hover": "#4E5268",
    "primary": "#BD93F9",
    "primary_dark": "#9B6DD7",
    "secondary": "#FF79C6",
    "success": "#50FA7B",
    "warning": "#FFB86C",
    "danger": "#FF5555",
    "cyan": "#8BE9FD",
    "text": "#F8F8F2",
    "muted": "#B8BBC7",
    "border": "#5B6078",
    "black": "#1E1F29",
}

ACTION_LABELS = {
    "manual-learn": "ثبت اطلاعات تأییدشده",
    "reassign-audio": "اصلاح اتصال فایل",
    "merge-recordings": "ادغام رکوردها",
    "revoke-recording": "غیرفعال‌کردن رکورد",
    "canonicalize-artist": "یکسان‌سازی نام هنرمند",
}

DECISION_LABELS = {
    "LOCAL_MATCH": "شناسایی محلی",
    "AUTO_LEARN": "یادگیری مطمئن",
    "REVIEW": "نیازمند بررسی",
    "REJECT": "شناسایی نشد",
}


def open_local_path(value: str | Path) -> None:
    path = Path(value).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def choose_persian_font(root: tk.Misc) -> str:
    available = {name.casefold(): name for name in tkfont.families(root)}
    for candidate in ("Vazirmatn", "Vazir", "Vazir UI", "Tahoma", "Segoe UI"):
        found = available.get(candidate.casefold())
        if found:
            return found
    return "TkDefaultFont"


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())
