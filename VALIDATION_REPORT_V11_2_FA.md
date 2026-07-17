# Validation Report — v11.2

## وضعیت

- Python compile: OK
- Unit tests: 38/38 OK
- Reference data validation: OK

## تست‌های جدید

- تک‌آهنگ‌هایی که Album آن‌ها شبیه Title است به `Singles` می‌روند.
- آلبوم چندترکی واقعی فولدر خودش را حفظ می‌کند.
- Seed اولیه چارتار از دیتابیس محلی خوانده می‌شود و Trackهای رایج آن به `Chaartaar/Singles` می‌رسند.

## نکته اجرایی

قبل از Apply حتماً Preview گرفته شود:

```powershell
.\run_reference_check.bat
.\run_preview.bat
```
