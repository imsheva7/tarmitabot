# پروژه ماژولار ربات ERP

وضعیت فعلی فاز ۵B و دستور تست با محیط جدید `.venv312` در
[PHASE5B_STATUS_FA.md](PHASE5B_STATUS_FA.md) ثبت شده است.

راهنمای نامزد انتشار همین نسخه در [RELEASE_CANDIDATE_FA.md](RELEASE_CANDIDATE_FA.md)
و نتیجه آزمون کپی محلی در [MIGRATION_REHEARSAL_FA.md](MIGRATION_REHEARSAL_FA.md) است.

این نسخه از `bot_integrated_review.py` استخراج شده و اکنون ۱۷۳ هندلر دارد:
هر ۱۷۳ هندلر در نوزده Router مستقل ثبت می‌شوند؛ ماژول‌های قدیمی بارگذاری نمی‌شوند.
این Routerها واحدها، عضویت، نقش‌ها، مشاهده پرسنل، مرخصی، یادآورها، اموال، خرید، مالی، گزارش‌ها، مأموریت، بیمه، مدیریت پرسنل، تعطیلات، پنل مدیریت، تصمیم مشترک درخواست‌ها، ورود، ناوبری و پاکسازی امن را پوشش می‌دهند.
وضعیت بازآرایی و مراحل بعد در [ARCHITECTURE_FA.md](ARCHITECTURE_FA.md) آمده است.

## اجرا

1. Python 3.11 یا 3.12 نصب کنید.
2. `pip install -r requirements.txt`
3. متغیر محیطی `BOT_TOKEN` را تنظیم کنید.
4. **ابتدا فقط روی کپی دیتابیس** اجرا کنید: `python main.py`
5. وابستگی‌های توسعه: `pip install -r requirements-dev.txt`.
6. اجرای تست‌ها: `python -m pytest -q` (شامل تست رفتاری و یکپارچه آفلاین).

## معماری

- `erpbot/bootstrap.py`: ساخت صریح Bot، Dispatcher و کلید، و بستن منابع
- `erpbot/core/runtime.py`: نمای سازگاری، مدل وضعیت، schema و توابع مشترک قدیمی
- `erpbot/core/settings.py`: بارگذاری صریح تنظیمات، مستقل از راه‌اندازی ربات
- `erpbot/core/database.py`: اتصال SQLite با commit، rollback و بستن خودکار
- `erpbot/core/encryption.py`: بارگذاری صریح کلید و رمزنگاری متن
- `erpbot/handlers/`: دسته‌های متوالی Handler، به ترتیب دقیق ثبت در نسخه اولیه
- `erpbot/handlers/unit_staff.py`: Router مستقل مشاهده پرسنل با وابستگی صریح
- `erpbot/services/staff_directory.py`: کاربردهای مشاهده پرسنل و کنترل دسترسی
- `erpbot/repositories/staff_directory.py`: کوئری‌های فقط‌خواندنی پرسنل و واحد
- `erpbot/handlers/organization_units.py`: Router مستقل مدیریت واحدها و حالت ثبت نام
- `erpbot/services/organization_units.py`: قواعد واحدها و کنترل مجوز مدیر اصلی
- `erpbot/repositories/organization_units.py`: SQL واحدها و ثبت audit
- `erpbot/handlers/organization_memberships.py`: Router مستقل عضویت و `/myunits`
- `erpbot/handlers/organization_roles.py`: Router مستقل نقش و مجوز
- `erpbot/services/organization_memberships.py` و `organization_roles.py`: قواعد و عملیات مدیریت
- `erpbot/repositories/organization_memberships.py` و `organization_roles.py`: SQL عضویت و نقش‌ها
- `erpbot/repositories/audit.py`: ثبت audit در تراکنش فراخواننده
- `erpbot/handlers/leave.py`: Router مستقل ثبت، جانشین، تصمیم و لغو مرخصی
- `erpbot/services/leave_workflow.py` و `leave_approval.py`: قواعد و تصمیم‌های اتمیک مرخصی
- `erpbot/repositories/leave.py`: SQL گردش مرخصی
- `erpbot/handlers/request_delivery.py`: ارسال درخواست‌ها با حفظ نمای سازگاری قدیمی
- `erpbot/services/requests.py` و `repositories/requests.py`: ثبت مشترک درخواست‌ها
- `erpbot/core/dates.py`: تاریخ شمسی و تبدیل ارقام بدون راه‌اندازی برنامه
- `erpbot/handlers/reminders.py`: دستور گروهی، لینک خصوصی و فرم تعاملی یادآوری
- `erpbot/services/reminders.py` و `repositories/reminders.py`: قواعد و SQL یادآورها
- `erpbot/scheduler/reminders.py`: زمان‌بند مستقل با ذخیره نتیجه پس از ارسال موفق
- `erpbot/handlers/assets_employee.py` و `assets_admin.py`: گردش پرسنلی و مدیریت اموال
- `erpbot/services/assets.py`: مالکیت، مجوز و تغییرات اتمیک اموال و درخواست آن
- `erpbot/repositories/assets.py`: SQL اموال و تأیید درخواست اموال
- `erpbot/handlers/finance_forms.py` و `finance_decisions.py`: فرم‌ها و تصمیم‌های مالی و خرید
- `erpbot/services/finance.py`: سقف مساعده، نقش‌ها و تغییرات اتمیک وضعیت مالی
- `erpbot/repositories/finance.py`: SQL مالی و خرید
- `erpbot/handlers/reports.py`: گزارش‌های شخصی و مدیریتی و ارسال اکسل
- `erpbot/services/reports.py` و `repositories/reports.py`: مجوزها، محاسبه آمار و خواندن داده گزارش
- `erpbot/reporting/`: مدل مستقل، ستون‌های ثابت و ساخت XLSX در حافظه
- `erpbot/handlers/missions.py` و `insurance.py`: فرم و تصمیم مأموریت و ثبت بیمه
- `erpbot/services/missions.py` و `insurance.py`: قواعد، نقش‌ها و تاریخ‌های مأموریت و بیمه
- `erpbot/repositories/missions.py` و `insurance.py`: SQL مأموریت و بیمه
- `erpbot/scheduler/insurance.py`: بررسی مستقل سررسید هفت‌روزه و ارسال به مدیران اصلی فعال
- `erpbot/scheduler/jobs.py`: زمان‌بند مستقل گزارش فردا، اعلان تأمین اجتماعی و پشتیبان هفتگی
- `erpbot/core/backup.py`: snapshot موقت SQLite شامل WAL با پاک‌سازی خودکار فایل
- `erpbot/handlers/admin_console.py` و `services/admin_console.py`: پنل مدیریت و پشتیبان دستی با بررسی مجوز
- `erpbot/handlers/request_decisions.py`، `services/request_decisions.py` و `repositories/request_decisions.py`: تصمیم و لغو اتمی مشترک درخواست‌ها
- `erpbot/handlers/navigation.py`، `services/navigation.py` و `repositories/navigation.py`: اتصال اتمی حساب، ورود و منوهای مشترک
- `erpbot/handlers/maintenance.py`، `services/maintenance.py` و `repositories/maintenance.py`: پاکسازی اتمی با پشتیبان اجباری و تأیید یک‌بارمصرف
- `erpbot/services/scheduled_reports.py` و `repositories/scheduled_reports.py`: گزارش خودکار فردا
- `erpbot/loader.py`: ترکیب Routerها با وابستگی صریح؛ بدون import ماژول‌های شماره‌دار و تزریق namespace
- `erpbot/main.py`: راه‌اندازی و خاتمه تمیز

## محدودیت مهم

تمام Routerها مستقل ثبت می‌شوند. schema، middlewareهای دسترسی و بعضی نماهای
سازگاری هنوز در `runtime.py` هستند؛ بررسی مهاجرت و آزمون زنده نسخه جدید باقی است.
تنظیمات، اتصال دیتابیس و رمزنگاری جدا شده‌اند. import کردن runtime، main
و loader به توکن نیاز ندارد و منابع یا فایل ایجاد نمی‌کند. شروع از
`python main.py` همچنان به BOT_TOKEN معتبر نیاز دارد. برای استفاده مستقیم
از ثبت Routerها، ابتدا `erpbot.bootstrap.initialize_runtime()` را فراخوانی
کنید؛ وابستگی‌های schedulerها پس از همین مرحله به آن‌ها داده می‌شوند.
نتیجه آخرین تست کامل در [ARCHITECTURE_FA.md](ARCHITECTURE_FA.md) ثبت شده است.
آزمون زنده فاز ۵B پیش از بازآرایی موفق بوده؛ نسخه بازآرایی‌شده با تست خودکار
بررسی شده و هنوز روی ربات اصلی یا دیتابیس واقعی اجرا نشده است.
