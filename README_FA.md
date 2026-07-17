# Smart Music Organizer v10 — نمونهٔ اولیه Free-First Identity Engine

این نسخه یک نمونهٔ اولیه از معماری قابل‌اتکا برای مرتب‌سازی آرشیوهای بزرگ موسیقی است. هدف این است که سیستم اول از منابع آنلاین رایگان/باز استفاده کند و اگر نتیجهٔ کافی نگرفت، به فایل‌های JSON محلی پروژه رجوع کند.

## ساختار خروجی

```text
Music Library/
└── Alireza Ghorbani/
    ├── Album Name/
    │   ├── Track One - Alireza Ghorbani.mp3
    │   └── Duet - Alireza Ghorbani (Guest Artist).mp3
    └── _Singles/
        └── Single - Alireza Ghorbani.mp3
```

- فولدر اول: خواننده یا هنرمند اصلی
- فولدر دوم: آلبوم
- نام فایل: `Title - Primary Artist (Guests).mp3`
- آهنگ بدون آلبوم معتبر: `_Singles`
- شاعر، ترانه‌سرا و آهنگساز به‌صورت پیش‌فرض مالک فولدر نمی‌شوند.

## ترتیب تشخیص در نسخهٔ v10

1. تگ‌های قطعی فایل مثل `ISRC` و `MusicBrainz ID`
2. MusicBrainz، Apple iTunes Search و AcoustID/Chromaprint در صورت داشتن کلید AcoustID
3. JSONهای محلی پروژه در `reference_data/`
4. تگ‌های فایل و نام فایل
5. فولدر `_Unknown Artist` برای مواردی که هنوز قابل‌اعتماد نیستند

## سیاست رایگان بودن

پیش‌فرض پروژه فقط روی منابع رایگان یا بدون هزینهٔ اجباری تنظیم شده است:

```json
"online_providers": {
  "musicbrainz": true,
  "apple_itunes": true,
  "acoustid": true,
  "spotify": false,
  "deezer": false
}
```

Spotify در این نمونه خاموش است، چون برای استفادهٔ عمومی GitHub نیاز به ساخت App و Client Credentials دارد. Deezer هم فعلاً فقط در طراحی آینده در نظر گرفته شده و در کد نمونه فعال نشده است.

## پایگاه دانش JSON

```text
reference_data/
├── artists/
│   ├── iranian.json
│   └── international.json
└── tracks/
    ├── iranian.json
    └── international.json
```

نمونهٔ Artist:

```json
{
  "id": "ir.alireza-ghorbani",
  "canonical_name": "Alireza Ghorbani",
  "preferred_folder_name": "Alireza Ghorbani",
  "native_name": "علیرضا قربانی",
  "roles": ["singer", "vocalist"],
  "aliases": [
    "علیرضا قربانی",
    "Alireza Ghorbani",
    "Alireza Qorbani",
    "alireza_ghorbani"
  ],
  "musicbrainz_id": "",
  "spotify_id": ""
}
```

تمام Aliasهای بالا به یک فولدر واحد می‌رسند:

```text
Alireza Ghorbani/
```

نمونهٔ Track:

```json
{
  "id": "ir.sample.alireza-ghorbani.demo",
  "canonical_title": "Demo Track",
  "artist_ids": ["ir.alireza-ghorbani"],
  "album": "_Singles",
  "aliases": [
    {"title": "demo track", "artist": "alireza_ghorbani"},
    {"title": "دمو", "artist": "علیرضا قربانی"}
  ]
}
```

Track Registry فقط fallback است؛ یعنی سیستم اول آنلاین را امتحان می‌کند و بعد سراغ JSON می‌آید.

## اجرای امن

اول نصب:

```powershell
.\setup.bat
```

بعد فقط Preview:

```powershell
.\run_preview.bat
```

بعد از بررسی گزارش:

```powershell
.\run_apply.bat
```

## بررسی سلامت JSONها

```powershell
.\run_reference_check.bat
```

## تست‌ها

```powershell
.\run_tests.bat
```

در این نسخه ۳۵ تست خودکار پاس شده‌اند.
