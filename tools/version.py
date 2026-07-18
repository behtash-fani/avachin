#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Single source of truth for Avachin's public version."""

from __future__ import annotations

AVACHIN_VERSION = "12.8"


def display_version() -> str:
    return f"Avachin v{AVACHIN_VERSION}"
