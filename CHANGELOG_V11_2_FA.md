# Smart Music Organizer v11.2 — Reliability Gate

این نسخه برای خطاهای واقعی آرشیوهای فارسی ساخته شد؛ مخصوصاً حالتی که سیستم برای هر تک‌آهنگ یک فولدر آلبوم می‌ساخت.

## تغییرات اصلی

- اضافه شدن Album Trust Gate.
- ساخت فولدر آلبوم فقط وقتی انجام می‌شود که آلبوم واقعاً قابل اعتماد باشد.
- اگر Provider یک آهنگ را به شکل one-track release یا single برگرداند، مسیر به `Artist/Singles` می‌رود.
- اگر نام آلبوم شبیه نام آهنگ باشد، به‌صورت پیش‌فرض به `Singles` منتقل می‌شود؛ مگر اینکه همان آلبوم چند ترک معتبر داشته باشد.
- اگر چند فایل در همان آرشیو با یک آلبوم مشترک پیدا شود، آن آلبوم به‌عنوان فولدر معتبر حفظ می‌شود.
- برای MusicBrainz release type و track count خوانده می‌شود و برای Apple/Spotify نیز تعداد ترک و نوع release در evidence ذخیره می‌شود.
- برای چارتار seed اولیه Artist و چند Track رایج اضافه شد تا `Chaartaar` به شکل یک گروه معتبر تشخیص داده شود و تک‌آهنگ‌ها زیر `Singles` بروند.

## تنظیمات جدید

```json
{
  "album_trust_gate_enabled": true,
  "album_folder_min_tracks": 2,
  "album_title_similarity_single_threshold": 88.0,
  "trust_single_track_musicbrainz_album": true,
  "trust_single_track_local_registry_album": true
}
```

## خروجی درست برای نمونه چارتار

```text
Chaartaar/
└── Singles/
    ├── Baaraan Toee - Chaartaar.mp3
    ├── Darya Kojaast - Chaartaar.mp3
    └── Jaade Miraghsad - Chaartaar.mp3
```

نه:

```text
Chaartaar/
├── Baaraan Toee/
├── Darya Kojaast/
└── Jaade Miraghsad/
```
