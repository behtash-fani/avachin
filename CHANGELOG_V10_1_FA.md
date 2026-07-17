# Music Organizer v10.1 — اصلاح رفتار Singles، Duplicate و نقش خواننده

## تغییرات

- فولدر تک‌آهنگ‌ها از `_Singles` به `Singles` تغییر کرد.
- Releaseهایی که عملاً تک‌آهنگ هستند، دیگر برای هر آهنگ فولدر جدا نمی‌سازند و داخل `Singles` می‌روند.
- آلبوم‌هایی با الگوی `Track Name`, `Track Name (Single)`, `Track Name - Single`, `Track Name EP` به‌عنوان Single تشخیص داده می‌شوند.
- `_Duplicates` به‌صورت پیش‌فرض حذف شد. فایل‌های تکراری Exact یا Audio-Equivalent در حالت Apply حذف می‌شوند و در حالت Copy فقط Skip می‌شوند.
- فایل‌هایی که هم‌نام‌اند ولی واقعاً یکسان نیستند به `Conflicts` می‌روند تا اشتباهاً حذف نشوند.
- پسوندهای سایت‌های دانلود مثل `UpMusic` بهتر از نام آرتیست پاک می‌شوند.
- Registry نقش‌ها جدی‌تر شد: آرتیست‌هایی که فقط Composer/Pianist/Instrumentalist هستند، تا وقتی خوانندهٔ معتبر پیدا نشود به فولدر خواننده تبدیل نمی‌شوند و به `Review - Non Vocal Artists` می‌روند.
- Alias اولیه برای `Arman Garshasbi`، `Anoushiravan Rohani` و `Dang Show` اضافه شد.

## نکته

دقت نهایی برای موسیقی ایرانی وابسته به کامل شدن `reference_data/artists/iranian.json` است. نسخهٔ v10.1 ساختار درست را آماده کرده، اما دیتاست ایرانی باید مرحله‌به‌مرحله و جامعه‌محور تکمیل شود.
