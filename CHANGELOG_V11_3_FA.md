# Smart Music Organizer v11.3 — Spotify Fallback + Registry Enricher

## هدف

این نسخه Spotify را به‌عنوان یک منبع اجباری وارد پروژه نمی‌کند. Spotify فقط به‌صورت اختیاری و محافظه‌کارانه استفاده می‌شود:

1. در خود Organizer فقط وقتی فعال می‌شود که کاربر `online_providers.spotify=true` و Credentialها را وارد کند.
2. با تنظیم `spotify_fallback_only=true`، Spotify در حالت عادی با MusicBrainz/Apple رقابت نمی‌کند و فقط وقتی منابع رایگان/اصلی نتیجه ندهند به‌عنوان fallback استفاده می‌شود.
3. ابزار جداگانه `tools/enrich_registry_with_spotify.py` برای به‌روزرسانی محلی `tracks/iranian.json` اضافه شد.

## فایل‌های جدید

- `tools/enrich_registry_with_spotify.py`
- `run_spotify_enrich.bat`

## تنظیمات جدید

```json
"spotify_fallback_only": true,
"spotify_safe_mode": true,
"spotify_min_confidence": 92.0,
"spotify_cache_days": 30,
"spotify_search_limit": 10,
"spotify_market": ""
```

## رفتار جدید

- Spotify پیش‌فرض خاموش است.
- اگر فعال شود، با `Client Credentials` کار می‌کند.
- پاسخ‌های Spotify در SQLite محلی cache می‌شوند.
- روی HTTP 429 از `Retry-After` پیروی می‌شود.
- ابزار Enricher فقط matchهای بالای threshold را مستقیم وارد JSON می‌کند.
- matchهای مشکوک وارد `reports/spotify_enrichment_report.csv` می‌شوند.

## اصلاح دیتابیس چارتار

ترک‌های نزدیک مثل این‌ها به یک عنوان Canonical نزدیک‌تر شدند:

- `Asemaan Ham Zamin Mikhorad`
- `Aseman Ham Zamin Mikhord`
- `Aseman Ham Zamin Mikhorad`

عنوان canonical اکنون `Aseman Ham Zamin Mikhorad` است و aliasهای قبلی همچنان حفظ شده‌اند.
