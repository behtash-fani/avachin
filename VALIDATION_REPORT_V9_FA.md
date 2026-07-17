# گزارش اعتبارسنجی Smart Music Organizer v9.0

## نتیجه

**PASS**

## تست خودکار

```text
python -m unittest discover -s tests -v
Ran 29 tests
OK
```

## تست یکپارچهٔ واقعی

دو MP3 واقعی کوتاه ساخته و با ID3 زیر آزمایش شدند:

```text
Solo Song / Alireza Ghorbani
Duet Song / Alireza Ghorbani feat. Guest One & Guest Two
```

خروجی واقعی:

```text
alireza_ghorbani/
├── Solo Song - Alireza Ghorbani.mp3
└── Duet Song - Alireza Ghorbani (Guest One x Guest Two).mp3
```

در `report.csv` نیز فیلدهای زیر درست ثبت شدند:

```text
artist_folder = alireza_ghorbani
filename_artist = Alireza Ghorbani (Guest One x Guest Two)
```

## موارد بررسی‌شده

- ساختار فقط یک سطح Artist دارد.
- Album Tag حفظ می‌شود ولی Album Folder ساخته نمی‌شود.
- Collaboration پوشهٔ جدا نمی‌سازد.
- Filename دقیقاً از `Title - Artist.mp3` پیروی می‌کند.
- مهمان‌ها در پرانتز قرار می‌گیرند.
- Primary Artist نام فایل و پوشه از یک Resolver مشترک می‌آید.
- Group اتمی Provider شکسته نمی‌شود.
- Aliasهای فارسی/لاتین می‌توانند به Canonical MusicBrainz برسند.
- AcoustID برای نتیجهٔ نامطمئن قابل استفاده است.
- Fingerprint ضعیف زیر Threshold رد می‌شود.
- Collision، Duplicate، Undo و Crash Recovery تست‌های قبلی را پاس کرده‌اند.

## محدودیت آگاهانه

نسخهٔ فعلی فقط MP3 را به‌عنوان فایل صوتی پردازش و Tag نویسی می‌کند. FLAC، M4A، OGG و WAV فعلاً در شاخهٔ Other Files قرار می‌گیرند. متن ترانه نیز به‌دلیل احتمال Cover، اجرای متفاوت و تطبیق اشتباه، به‌صورت خودکار مبنای جابه‌جایی نیست.
