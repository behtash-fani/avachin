# Music Organizer v11 — Automatic Learning Registry Prototype

این نسخه نمونهٔ اولیهٔ موتور یادگیری خودکار را اضافه می‌کند.

## تغییرات اصلی

- اضافه شدن دیتابیس محلی `learning_registry.sqlite3` داخل AppData کاربر.
- برنامه در هر Preview/Apply قبل از مرتب‌سازی، از ساختار فولدرهای فعلی و تگ‌ها یاد می‌گیرد.
- Aliasهای تکراری مثل `Arman Garshasbi~ UpMusic`، `arman_garshasbi` و شکل‌های مشابه در صورت داشتن شواهد کافی به یک Artist canonical وصل می‌شوند.
- دیتای JSON قبلی همچنان پایهٔ اصلی است و موتور یادگیری فقط آن را کامل‌تر می‌کند.
- موارد یادگرفته‌شده در همان اجرای فعلی هم برای تصمیم‌گیری استفاده می‌شوند.
- برای هر اجرا فایل‌های زیر ساخته می‌شود:
  - `learning_report.json`
  - `contributions/artists.learned.jsonl`
  - `contributions/artist_aliases.learned.jsonl`
  - `contributions/recordings.learned.jsonl`
- مسیر یادگیری کاملاً local-first است؛ هیچ اطلاعاتی خودکار به سرور یا دیتابیس آنلاین ارسال نمی‌شود.

## فلسفه تصمیم‌گیری

سیستم فقط وقتی چیزی را به دیتابیس قابل‌استفاده اضافه می‌کند که چند نشانه داشته باشد؛ مثل فولدر موجود، تگ Artist/Album Artist، دیتای JSON محلی یا تعداد آهنگ کافی. موارد ضعیف فقط در گزارش یادگیری می‌آیند و باعث ساخت فولدر اشتباه نمی‌شوند.

## اجرای پیشنهادی

```powershell
.\run_reference_check.bat
.\run_preview.bat
```

بعد از بررسی گزارش:

```powershell
.\run_apply.bat
```
