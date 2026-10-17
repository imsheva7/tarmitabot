# اصلاح مرحله ۲ — رفع خطای get_connection

این سند شرح اصلاح تاریخی است. محدودیت import و نیاز به توکن که در ادامه
ذکر شده، با راه‌اندازی صریح در نسخه فعلی رفع شده است؛ جزئیات در
[ARCHITECTURE_FA.md](ARCHITECTURE_FA.md) آمده است. شمار تست فعلی ۸۵۳ است.

- تابع `get_connection` از `handlers/001_misc.py` به `core/runtime.py` و قبل از `init_db` منتقل شد.
- اجرای مستقیم `init_db()` در زمان import حذف شد؛ در `erpbot/main.py` پیش از ثبت Handlerها اجرا می‌شود.
- تست‌های Windows با UTF-8 اصلاح شدند و سه تست رگرسیون اضافه شد.

**محدودیت مهم:** این بسته صرفاً مشکل شناخته‌شده را برطرف می‌کند. معماری runtime هنوز یکپارچه است و import همچنان به BOT_TOKEN و مدیریت کلید نیاز دارد. تست‌های استاتیک موفقیت اجرای واقعی یا سازگاری کامل Handlerها را تضمین نمی‌کنند. از توکن آزمایشی و دیتابیس خالی استفاده کنید؛ روی Railway فعلی مستقر نکنید.

دستورات:
```powershell
cd C:\ERP-Bot
.\.venv\Scripts\python.exe -m pytest -v
$env:BOT_TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk"
.\.venv\Scripts\python.exe -c "import erpbot.loader; print('LOADER IMPORT OK')"
```
