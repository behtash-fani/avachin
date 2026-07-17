# Validation Report — v11.3

## بررسی‌ها

- Python compile: OK
- Spotify enricher compile: OK
- JSON parse برای config و registry: OK
- Unit tests: 39/39 OK

## نتیجه

نسخه v11.3 آماده تست است. Spotify در این نسخه اجباری نیست و فقط در صورت تنظیم Credential و فعال‌کردن provider استفاده می‌شود.

## اجرای Enricher

```powershell
setx SPOTIFY_CLIENT_ID "YOUR_CLIENT_ID"
setx SPOTIFY_CLIENT_SECRET "YOUR_CLIENT_SECRET"
```

بعد یک PowerShell جدید باز کن و اجرا کن:

```powershell
.\run_spotify_enrich.bat
```

خروجی گزارش:

```text
reports/spotify_enrichment_report.csv
```
