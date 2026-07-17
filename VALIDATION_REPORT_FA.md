# گزارش اعتبارسنجی Smart Music Organizer v8.2

## نتیجه

- Python compile: PASS
- Unit tests: 23 / 23 PASS
- Config consistency: PASS
- Flat Artist layout path test: PASS
- Default Artist/Album layout compatibility: PASS
- Sidecar destination compatibility: PASS
- Transaction / Undo / Crash Recovery tests: PASS

## تنظیم جدید بررسی‌شده

```json
"artist_subfolders_enabled": true
```

- `true` → `Artist / Album / Song.mp3`
- `false` → `Artist / Song.mp3`

در حالت `false` مقدار Album در Metadata فایل حفظ می‌شود و فقط مسیر فیزیکی تخت می‌شود.
