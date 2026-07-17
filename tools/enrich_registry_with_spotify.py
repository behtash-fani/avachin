#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Optional Spotify registry enricher for Smart Music Organizer.

This tool is intentionally separate from the main organizer.  It uses Spotify as
an optional last-resort/catalog cross-check, not as the primary database.

Outputs only minimal local hints (spotify track id, ISRC, duration, confidence)
into the local JSON registry so the main app can resolve messy files more safely.
Do not use this to bulk-copy Spotify's catalog into a public standalone dataset.
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import sqlite3
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    import requests
except ImportError as exc:  # pragma: no cover
    print(f"Missing dependency: {exc}. Run setup.bat first.", file=sys.stderr)
    raise SystemExit(2)

try:
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover
    fuzz = None

SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_SEARCH_URL = "https://api.spotify.com/v1/search"
APP_NAME = "SmartMusicOrganizer"


@dataclass
class MatchResult:
    spotify_id: str
    spotify_title: str
    spotify_artist: str
    spotify_album: str
    isrc: Optional[str]
    duration_ms: Optional[int]
    confidence: float
    query: str
    reason: str


def app_data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / APP_NAME
    return Path.home() / ".smart_music_organizer"


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def compact_spaces(value: str) -> str:
    return " ".join(str(value or "").replace("_", " ").split())


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or ""))
    value = value.replace("ي", "ی").replace("ك", "ک")
    value = value.replace("\u200c", " ")
    value = value.lower()
    keep = []
    for ch in value:
        cat = unicodedata.category(ch)
        if cat.startswith("M"):
            continue
        if ch.isalnum() or ch.isspace():
            keep.append(ch)
        else:
            keep.append(" ")
    return compact_spaces("".join(keep))


def similarity(a: str, b: str) -> float:
    left = normalize_text(a)
    right = normalize_text(b)
    if not left and not right:
        return 100.0
    if not left or not right:
        return 0.0
    if fuzz is not None:
        return float(fuzz.token_set_ratio(left, right))
    import difflib
    return 100.0 * difflib.SequenceMatcher(None, left, right).ratio()


class SimpleCache:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS cache "
            "(key TEXT PRIMARY KEY, created_at REAL NOT NULL, payload TEXT NOT NULL)"
        )
        self.conn.commit()

    def get(self, key: str, max_age_days: int) -> Optional[Any]:
        row = self.conn.execute(
            "SELECT created_at, payload FROM cache WHERE key=?",
            (key,),
        ).fetchone()
        if not row:
            return None
        if time.time() - float(row[0]) > max_age_days * 86400:
            return None
        try:
            return json.loads(row[1])
        except json.JSONDecodeError:
            return None

    def set(self, key: str, payload: Any) -> None:
        self.conn.execute(
            "INSERT INTO cache(key, created_at, payload) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET "
            "created_at=excluded.created_at, payload=excluded.payload",
            (key, time.time(), json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


class SpotifyClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        cache: SimpleCache,
        market: str = "",
        cache_days: int = 30,
        timeout: int = 20,
    ) -> None:
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.cache = cache
        self.market = market.strip().upper()
        self.cache_days = max(1, int(cache_days or 30))
        self.timeout = timeout
        self.session = requests.Session()
        self.token: Optional[str] = None
        self.token_expire_at = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def get_token(self) -> str:
        if self.token and time.time() < self.token_expire_at - 60:
            return self.token
        raw = f"{self.client_id}:{self.client_secret}".encode("utf-8")
        auth = base64.b64encode(raw).decode("ascii")
        response = self.session.post(
            SPOTIFY_TOKEN_URL,
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        self.token = payload["access_token"]
        self.token_expire_at = time.time() + int(payload.get("expires_in", 3600))
        return self.token

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        cache_key = json.dumps({"q": query, "limit": limit, "market": self.market}, sort_keys=True)
        cached = self.cache.get(cache_key, self.cache_days)
        if cached is not None:
            return cached
        token = self.get_token()
        params: dict[str, Any] = {"q": query, "type": "track", "limit": max(1, min(50, limit))}
        if self.market:
            params["market"] = self.market
        for attempt in range(4):
            response = self.session.get(
                SPOTIFY_SEARCH_URL,
                headers={"Authorization": f"Bearer {token}"},
                params=params,
                timeout=self.timeout,
            )
            if response.status_code == 429:
                wait = int(response.headers.get("Retry-After", "2"))
                time.sleep(max(1, wait))
                continue
            if response.status_code in {500, 502, 503, 504} and attempt < 3:
                time.sleep(2 ** attempt)
                continue
            response.raise_for_status()
            payload = response.json().get("tracks", {}).get("items", []) or []
            self.cache.set(cache_key, payload)
            return payload
        return []


def build_artist_lookup(artists_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("id")): item
        for item in artists_payload.get("artists", [])
        if isinstance(item, dict) and item.get("id")
    }


def artist_name_for_track(track: dict[str, Any], artists_by_id: dict[str, dict[str, Any]]) -> str:
    artist_ids = track.get("artist_ids") or []
    if artist_ids:
        artist = artists_by_id.get(str(artist_ids[0])) or {}
        return str(
            artist.get("preferred_folder_name")
            or artist.get("canonical_name")
            or artist.get("native_name")
            or ""
        )
    return ""


def spotify_item_to_match(
    item: dict[str, Any],
    *,
    title: str,
    artist: str,
    album: str,
    query: str,
    reason: str,
) -> MatchResult:
    sp_title = str(item.get("name") or "")
    sp_artists = item.get("artists") or []
    sp_artist = str(sp_artists[0].get("name") if sp_artists else "")
    sp_album = str((item.get("album") or {}).get("name") or "")
    isrc = (item.get("external_ids") or {}).get("isrc")
    title_score = similarity(title, sp_title)
    artist_score = similarity(artist, sp_artist)
    album_score = similarity(album, sp_album) if album else 85.0
    confidence = 0.50 * title_score + 0.35 * artist_score + 0.15 * album_score
    if reason == "isrc":
        confidence = max(confidence, 98.0)
    return MatchResult(
        spotify_id=str(item.get("id") or ""),
        spotify_title=sp_title,
        spotify_artist=sp_artist,
        spotify_album=sp_album,
        isrc=isrc,
        duration_ms=item.get("duration_ms"),
        confidence=round(float(confidence), 2),
        query=query,
        reason=reason,
    )


def best_match_for_track(
    client: SpotifyClient,
    track: dict[str, Any],
    artists_by_id: dict[str, dict[str, Any]],
    limit: int,
) -> tuple[Optional[MatchResult], list[MatchResult]]:
    title = compact_spaces(str(track.get("canonical_title") or track.get("title") or ""))
    artist = artist_name_for_track(track, artists_by_id)
    album = compact_spaces(str(track.get("album") or ""))
    external = track.get("external_ids") if isinstance(track.get("external_ids"), dict) else {}
    isrc = compact_spaces(str(track.get("isrc") or external.get("isrc") or ""))
    queries: list[tuple[str, str]] = []
    if isrc:
        queries.append((f"isrc:{isrc}", "isrc"))
    if title and artist:
        q = f'track:"{title}" artist:"{artist}"'
        if album:
            q += f' album:"{album}"'
        queries.append((q, "title+artist+album" if album else "title+artist"))
    # Try a few aliases only when the canonical title search is weak/missing.
    for alias in track.get("aliases") or []:
        if not isinstance(alias, dict):
            continue
        alias_title = compact_spaces(str(alias.get("title") or ""))
        alias_artist = compact_spaces(str(alias.get("artist") or artist or ""))
        if alias_title and alias_artist and alias_title != title:
            queries.append((f'track:"{alias_title}" artist:"{alias_artist}"', "alias"))
        if len(queries) >= 5:
            break

    matches: list[MatchResult] = []
    for query, reason in queries:
        for item in client.search(query, limit=limit):
            if not item.get("id"):
                continue
            matches.append(
                spotify_item_to_match(
                    item,
                    title=title,
                    artist=artist,
                    album=album,
                    query=query,
                    reason=reason,
                )
            )
    matches.sort(key=lambda item: item.confidence, reverse=True)
    return (matches[0] if matches else None), matches[:5]


def enrich(args: argparse.Namespace) -> int:
    project = Path(args.project).resolve()
    config = read_json(project / "config.json", {})
    artists_path = project / args.artists
    tracks_path = project / args.tracks
    artists_payload = read_json(artists_path, {"artists": []})
    tracks_payload = read_json(tracks_path, {"tracks": []})
    artists_by_id = build_artist_lookup(artists_payload)

    client_id = args.client_id or os.environ.get("SPOTIFY_CLIENT_ID") or str(config.get("spotify_client_id") or "")
    client_secret = args.client_secret or os.environ.get("SPOTIFY_CLIENT_SECRET") or str(config.get("spotify_client_secret") or "")
    if not client_id or not client_secret:
        print("Spotify credentials not found. Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET or config.json.", file=sys.stderr)
        return 2

    cache = SimpleCache(app_data_dir() / "spotify_enricher_cache.sqlite3")
    client = SpotifyClient(
        client_id,
        client_secret,
        cache,
        market=args.market or str(config.get("spotify_market") or ""),
        cache_days=int(args.cache_days or config.get("spotify_cache_days", 30) or 30),
    )
    threshold = float(args.min_confidence)
    report_rows: list[dict[str, Any]] = []
    changed = 0
    reviewed = 0
    now = datetime.now(timezone.utc).isoformat()

    tracks = tracks_payload.get("tracks", [])
    for index, track in enumerate(tracks, 1):
        if not isinstance(track, dict):
            continue
        external = track.get("external_ids") if isinstance(track.get("external_ids"), dict) else {}
        if external.get("spotify") and not args.refresh:
            continue
        best, candidates = best_match_for_track(client, track, artists_by_id, int(args.limit))
        title = track.get("canonical_title") or track.get("title") or ""
        artist = artist_name_for_track(track, artists_by_id)
        row = {
            "track_id": track.get("id", ""),
            "title": title,
            "artist": artist,
            "album": track.get("album", ""),
            "status": "not-found",
            "confidence": "",
            "spotify_id": "",
            "spotify_title": "",
            "spotify_artist": "",
            "spotify_album": "",
            "query": "",
        }
        if best is not None:
            row.update({
                "status": "matched" if best.confidence >= threshold else "review",
                "confidence": best.confidence,
                "spotify_id": best.spotify_id,
                "spotify_title": best.spotify_title,
                "spotify_artist": best.spotify_artist,
                "spotify_album": best.spotify_album,
                "query": best.query,
            })
            if best.confidence >= threshold:
                ext = dict(external)
                ext["spotify"] = best.spotify_id
                if best.isrc:
                    ext["isrc"] = best.isrc
                    track["isrc"] = track.get("isrc") or best.isrc
                track["external_ids"] = ext
                if best.duration_ms:
                    track["duration_ms"] = best.duration_ms
                track["spotify_enrichment"] = {
                    "confidence": best.confidence,
                    "checked_at": now,
                    "query_reason": best.reason,
                    "safe_fallback_hint": True,
                }
                changed += 1
            else:
                reviewed += 1
        report_rows.append(row)
        if args.progress and (index <= 5 or index % args.progress == 0 or index == len(tracks)):
            print(f"[{index}/{len(tracks)}] {row['status']}: {title} - {artist}")

    report_path = project / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = [
            "track_id", "title", "artist", "album", "status", "confidence",
            "spotify_id", "spotify_title", "spotify_artist", "spotify_album", "query",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(report_rows)

    if args.in_place:
        backup = tracks_path.with_suffix(tracks_path.suffix + f".bak-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
        backup.write_text(tracks_path.read_text(encoding="utf-8"), encoding="utf-8")
        write_json(tracks_path, tracks_payload)
        out_path = tracks_path
    else:
        out_path = project / args.output
        write_json(out_path, tracks_payload)

    cache.close()
    print(f"Spotify enrichment done. matched={changed}, review={reviewed}, report={report_path}")
    print(f"Output: {out_path}")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Optional Spotify fallback/enrichment for local JSON registry")
    parser.add_argument("--project", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--artists", default="reference_data/artists/iranian.json")
    parser.add_argument("--tracks", default="reference_data/tracks/iranian.json")
    parser.add_argument("--output", default="reference_data/tracks/iranian.spotify.enriched.local.json")
    parser.add_argument("--report", default="reports/spotify_enrichment_report.csv")
    parser.add_argument("--client-id", default="")
    parser.add_argument("--client-secret", default="")
    parser.add_argument("--market", default="")
    parser.add_argument("--cache-days", type=int, default=30)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--min-confidence", type=float, default=92.0)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--progress", type=int, default=25)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    return enrich(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
