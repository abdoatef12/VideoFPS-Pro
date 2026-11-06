# VideoFPS Pro

![VideoFPS Pro](docs/banner.png)

تطبيق أندرويد لتحويل الفيديوهات إلى 60 / 90 / 120 fps باستخدام FFmpeg `minterpolate`.

## كيف يشتغل

التطبيق بيفتح واجهة VideoFPS الموجودة على سيرفر Python بيشتغل في Termux على نفس الموبايل (`127.0.0.1:5000`).

1. ثبّت Termux وشغّل السيرفر: `python VideoFPS_Pro.py`
2. افتح تطبيق VideoFPS Pro
3. ارفع الفيديو واختار معدل الفريمات

## تحميل التطبيق

ادخل تبويب **Actions** في الريبو، واختار آخر Build ناجح، وحمّل ملف `VideoFPS-Pro-debug` (بيحتوي على `app-debug.apk`).

أو من تبويب **Releases** لو فيه نسخة منشورة.

## البناء يدوياً

```bash
gradle :app:assembleDebug
```

الـ APK هيطلع في `app/build/outputs/apk/debug/app-debug.apk`.

## المتطلبات

- Android 7.0 (API 24) أو أحدث
- Termux مع Python و FFmpeg
