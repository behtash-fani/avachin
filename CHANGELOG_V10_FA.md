# تغییرات v10 — Free-First Identity Engine Prototype

- اضافه‌شدن `reference_data/artists/*.json` برای یکسان‌سازی Aliasهای خواننده‌ها.
- اضافه‌شدن `reference_data/tracks/*.json` به‌عنوان fallback بعد از منابع آنلاین.
- اضافه‌شدن Registry ID پایدار مثل `registry:ir.alireza-ghorbani` برای جلوگیری از ساخت چند فولدر برای یک خواننده.
- تغییر پیش‌فرض به معماری Free-First.
- اضافه‌شدن تنظیم `online_providers` برای روشن/خاموش‌کردن Providerها.
- Spotify به‌صورت پیش‌فرض خاموش شد.
- Deezer در این Prototype فعال نیست و فقط برای فاز بعدی در طراحی باقی مانده است.
- اضافه‌شدن اعتبارسنج سادهٔ JSON برای Aliasهای تکراری و Trackهای دارای Artist نامعتبر.
- اضافه‌شدن تست‌های Registry و Local Track Fallback.
- تمام تست‌ها: ۳۵ مورد، بدون خطا.
