"""Reminder Router with injected storage, bot and clock."""
import html
from aiogram import Router, F, BaseMiddleware
from aiogram.filters import BaseFilter, Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from ..services import reminders as service


class Form(StatesGroup):
    interactive_reminder_type = State()
    interactive_reminder_date = State()
    interactive_reminder_time = State()
    interactive_reminder_text = State()


class ReminderStartFilter(BaseFilter):
    def __init__(self, *, include_reminder=True):
        self.include_reminder = include_reminder

    async def __call__(self, message, command: CommandObject):
        matches = bool(command.args and command.args.startswith("reminder_"))
        return matches == self.include_reminder


class ReminderAccess(BaseMiddleware):
    def __init__(self, connection_factory):
        self.connection_factory = connection_factory

    async def __call__(self, handler, event, data):
        try:
            with self.connection_factory() as conn:
                service.active_staff_name(conn,event.from_user.id)
            return await handler(event,data)
        except service.ReminderError as exc:
            if isinstance(event,CallbackQuery):
                await event.answer(str(exc),show_alert=True)
            else:
                await event.answer(str(exc))


def create_router(get_connection, bot, clock):
    router = Router(name="reminders")
    access = ReminderAccess(get_connection)
    router.message.middleware(access)
    router.callback_query.middleware(access)

    def save(actor, chat, thread, spec):
        with get_connection() as conn:
            service.register(conn,actor,chat,thread,spec,clock())

    def confirmation(spec):
        if spec.kind == "once":
            return f"✅ یادآوری برای تاریخ <b>{spec.when}</b> ساعت <b>{spec.time}</b> ثبت گردید."
        if spec.kind == "weekly":
            return f"✅ یادآوری هفتگی برای ساعت <b>{spec.time}</b> ثبت گردید."
        return f"✅ یادآوری ماهانه برای روز <b>{spec.when}</b> ساعت <b>{spec.time}</b> ثبت گردید."

    def menu():
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='➕ یادآور جدید',callback_data='remmanage_new')],
            [InlineKeyboardButton(text='📋 یادآورهای من در این مقصد',callback_data='remmanage_list_0')]])

    @router.callback_query(F.data.startswith('remmanage_'))
    async def manage_reminders(callback: CallbackQuery, state: FSMContext):
        if callback.message.chat.type != 'private':
            raise service.ReminderError('مدیریت یادآورها را در چت خصوصی انجام دهید.')
        data=await state.get_data()
        chat,thread=service.target(data.get('remind_chat_id'),data.get('remind_thread_id'))
        action=callback.data.removeprefix('remmanage_')
        if action=='new':
            await state.set_state(Form.interactive_reminder_type)
            keyboard=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=text,callback_data='rem_type_'+kind)] for text,kind in
                [('📌 تاریخ مشخص','once'),('🔄 هفتگی','weekly'),('🗓️ ماهانه','monthly')]])
            await callback.message.answer('نوع یادآور را انتخاب کنید:',reply_markup=keyboard)
        else:
            parts=action.split('_')
            try:
                operation=parts[0]
                number=int(parts[1]) if len(parts)==2 else -1
            except ValueError:
                raise service.ReminderError('دکمه نامعتبر است.') from None
            if operation not in ('list','view','delete','confirm'):
                raise service.ReminderError('دکمه نامعتبر است.')
            with get_connection() as conn:
                rows=service.manage(conn,callback.from_user.id,chat,thread,
                    page=number if operation=='list' else 0,
                    reminder_id=None if operation=='list' else number,delete=operation=='confirm')
            await state.set_state(None)
            if operation=='list':
                buttons=[[InlineKeyboardButton(text=str(row[6])[:40] or 'بدون عنوان',
                    callback_data=f'remmanage_view_{row[0]}')] for row in rows[:5]]
                if number>0:
                    buttons.append([InlineKeyboardButton(text='صفحه قبل',callback_data=f'remmanage_list_{number-1}')])
                if len(rows)>5:
                    buttons.append([InlineKeyboardButton(text='صفحه بعد',callback_data=f'remmanage_list_{number+1}')])
                buttons.extend(menu().inline_keyboard)
                await callback.message.answer('یادآورهای شما در همین گروه/تاپیک:' if rows else 'در این گروه/تاپیک یادآوری ندارید.',
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
            elif operation=='confirm':
                await callback.message.answer('✅ یادآور حذف شد.',reply_markup=menu())
            else:
                rid,kind,weekday,monthday,time,when,content,sent=rows
                schedule=when if kind=='once' else (f'هر {next((fa for fa,en in service.DAY_MAP.items() if en==weekday),weekday)} ساعت {time}'
                    if kind=='weekly' else f'روز {monthday} هر ماه ساعت {time}')
                text=f'{html.escape(content[:500])}\n⏰ {html.escape(str(schedule))} (به وقت تهران)'
                if kind=='once' and sent:
                    text+='\n✅ ارسال شده'
                if operation=='delete':
                    text+='\nاین یادآور حذف شود؟'
                buttons=[[InlineKeyboardButton(text='تأیید حذف' if operation=='delete' else '🗑 حذف',
                    callback_data=f'remmanage_{"confirm" if operation=="delete" else "delete"}_{rid}')],
                    [InlineKeyboardButton(text='بازگشت به فهرست',callback_data='remmanage_list_0')]]
                await callback.message.answer(text,parse_mode='HTML',reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        await callback.answer()

    @router.message(Command("start"), ReminderStartFilter())
    async def start_reminder(message: Message, command: CommandObject, state: FSMContext):
        if message.chat.type != "private":
            raise service.ReminderError("تنظیم تعاملی یادآوری را در پی‌وی ربات انجام دهید.")
        chat,thread = service.parse_link(command.args)
        await state.clear()
        await state.update_data(remind_chat_id=chat,remind_thread_id=thread)
        await state.set_state(Form.interactive_reminder_type)
        await message.answer('⏰ ساخت و مدیریت یادآور\nیادآورها در گروه/تاپیکی که از آن وارد شدی ارسال می‌شوند. زمان‌ها به وقت تهران هستند.',reply_markup=menu())

    @router.message(F.text.contains("#یادآوری") | (F.text.strip() == 'یادآوری'))
    async def handle_group_reminder(message: Message, state: FSMContext):
        if message.chat.type not in ("group","supergroup"):
            await message.answer("⚠️ دستور یادآوری باید در گروه‌های کاری استفاده شود.")
            return
        text = message.text.strip()
        if text in ("#یادآوری", "یادآوری"):
            info = await bot.get_me()
            payload = f"reminder_{message.chat.id}_{message.message_thread_id or 'None'}"
            keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="⏰ ساخت و مدیریت یادآور",url=f"https://t.me/{info.username}?start={payload}")
            ]])
            await message.reply("⏰ یادآورت را در چت خصوصی تنظیم کن؛ در همین گروه/تاپیک ارسال می‌شود.",reply_markup=keyboard)
            return
        spec = service.parse_group(text,clock())
        save(message.from_user.id,message.chat.id,message.message_thread_id,spec)
        await message.reply(confirmation(spec),parse_mode="HTML")

    @router.callback_query(F.data.startswith("rem_type_"))
    async def process_reminder_type_selected(callback: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        service.target(data.get("remind_chat_id"),data.get("remind_thread_id"))
        kind = callback.data.removeprefix("rem_type_")
        if kind not in ("once","weekly","monthly"):
            raise service.ReminderError("❌ نوع یادآوری نامعتبر است.")
        await state.update_data(rem_type=kind,rem_date=None,rem_time=None)
        await state.set_state(Form.interactive_reminder_date)
        keyboard = None
        if kind == "once":
            text = "📅 <b>مرحله ۱ از ۳:</b> تاریخ یادآوری را وارد کنید (<code>YYYY/MM/DD</code> یا مثلاً <code>فردا</code> / <code>پس‌فردا</code>):"
        elif kind == "weekly":
            buttons = [InlineKeyboardButton(text=fa,callback_data="remday_"+en) for fa,en in service.DAY_MAP.items()]
            keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons[i:i+2] for i in range(0,len(buttons),2)])
            text = "📅 <b>مرحله ۱ از ۳:</b> روز هفته را انتخاب کنید:"
        else:
            text = "📅 <b>مرحله ۱ از ۳:</b> شماره روز ماه را وارد کنید (مثلاً ۱ یا ۱۵):"
        await callback.message.edit_text(text,reply_markup=keyboard,parse_mode="HTML")
        await callback.answer()

    @router.message(Form.interactive_reminder_date)
    async def process_reminder_date_text(message: Message, state: FSMContext):
        if not message.text:
            raise service.ReminderError("❌ لطفاً متن معتبر ارسال کنید.")
        data = await state.get_data()
        when = service.reminder_date(data.get("rem_type"),message.text,clock())
        await state.update_data(rem_date=when)
        await state.set_state(Form.interactive_reminder_time)
        await message.answer("⏰ <b>مرحله ۲ از ۳:</b> ساعت یادآوری را وارد کنید (مثلاً 09:30):",parse_mode="HTML")

    @router.callback_query(Form.interactive_reminder_date, F.data.startswith("remday_"))
    async def process_reminder_date_callback(callback: CallbackQuery, state: FSMContext):
        data = await state.get_data()
        if data.get("rem_type") != "weekly":
            raise service.ReminderError("❌ روز هفته متعلق به این فرم نیست.")
        when = service.reminder_date("weekly",callback.data.removeprefix("remday_"),clock())
        await state.update_data(rem_date=when)
        await state.set_state(Form.interactive_reminder_time)
        await callback.message.edit_text("⏰ <b>مرحله ۲ از ۳:</b> ساعت یادآوری را وارد کنید (مثلاً 09:30):",parse_mode="HTML")
        await callback.answer()

    @router.message(Form.interactive_reminder_time)
    async def process_reminder_time_selected(message: Message, state: FSMContext):
        time = service.normalized_time(message.text or "")
        await state.update_data(rem_time=time)
        await state.set_state(Form.interactive_reminder_text)
        await message.answer("📝 <b>مرحله ۳ از ۳:</b> متن یا عنوان یادآوری را بنویسید:",parse_mode="HTML")

    @router.message(Form.interactive_reminder_text)
    async def process_reminder_text_final(message: Message, state: FSMContext):
        data = await state.get_data()
        spec = service.build_spec(data.get("rem_type"),data.get("rem_date"),data.get("rem_time") or "",message.text,clock())
        save(message.from_user.id,data.get("remind_chat_id"),data.get("remind_thread_id"),spec)
        await state.clear()
        await message.answer(confirmation(spec),parse_mode="HTML")

    return router
