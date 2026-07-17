# گزارش اعتبارسنجی v10

- Python compile: OK
- Reference JSON validation: OK
- Unit tests: 35/35 OK
- ساختار خروجی پیش‌فرض: `Artist/Album/Title - Artist.mp3`
- Providerهای فعال پیش‌فرض: MusicBrainz، Apple iTunes Search، AcoustID در صورت کلید
- Providerهای غیرفعال پیش‌فرض: Spotify، Deezer
- Local fallback: `reference_data/artists/*.json` و `reference_data/tracks/*.json`
