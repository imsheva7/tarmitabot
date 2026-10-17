"""Reminder Router through real FSM and legacy /start, without Telegram network."""
import os
from pathlib import Path
import subprocess
import sys


def test_reminders_end_to_end_with_legacy_start_and_scheduler(tmp_path):
    script=r'''
import asyncio
import sqlite3
from pathlib import Path
import jdatetime
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage, GetMe
from aiogram.types import Message, Update, User
from cryptography.fernet import Fernet
from erpbot.bootstrap import initialize_runtime
from erpbot.core import runtime
from erpbot.core.settings import Settings
from erpbot.loader import register_handlers
from erpbot.scheduler.reminders import deliver_due

class OfflineSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls=[]
        self.last_confirmed_count=0
    async def close(self):
        pass
    async def make_request(self,bot,method,timeout=None):
        if isinstance(method,GetMe):
            return bot._me
        self.calls.append(method)
        if isinstance(method,AnswerCallbackQuery):
            return True
        assert isinstance(method,(SendMessage,EditMessageText)),type(method)
        if isinstance(method,SendMessage) and 'ثبت گردید' in method.text:
            # Telegram success acknowledgement must follow committed persistence.
            with runtime.get_connection() as conn:
                saved_count=conn.execute('SELECT COUNT(*) FROM reminders').fetchone()[0]
                assert saved_count>self.last_confirmed_count
                self.last_confirmed_count=saved_count
        return Message(message_id=100+len(self.calls),date=0,
                       chat={'id':method.chat_id,'type':'private'},text=method.text)
    async def stream_content(self,*args,**kwargs):
        raise AssertionError('No network')
        yield b''

async def main():
    app=initialize_runtime(Settings.from_env({
        'BOT_TOKEN':'123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk',
        'FERNET_KEY':Fernet.generate_key().decode(),'GROUP_ID':'-100999',
    },data_directory=Path.cwd()),configure_logging=False)
    runtime.init_db()
    runtime.get_current_tehran_time=lambda:jdatetime.datetime(1405,7,24,9,0)
    with runtime.get_connection() as conn:
        conn.execute("INSERT INTO staff_mapping(staff_name,telegram_user_id,role) VALUES('Test staff',202,'staff')")
    register_handlers()
    session=OfflineSession()
    app.bot.session=session
    app.bot._me=User(id=123456789,is_bot=True,first_name='Test Bot',username='test_bot')
    sequence=0
    async def send(text,user=202,chat=None,thread=None):
        nonlocal sequence
        sequence+=1
        session.calls.clear()
        message={'message_id':sequence,'date':0,
                 'chat':{'id':chat or user,'type':'supergroup' if chat else 'private'},
                 'from':{'id':user,'is_bot':False,'first_name':'Test'},'text':text}
        if thread:
            message['message_thread_id']=thread
        if text.startswith('/start'):
            message['entities']=[{'type':'bot_command','offset':0,'length':6}]
        await app.dispatcher.feed_update(app.bot,Update.model_validate({'update_id':sequence,'message':message}))
    async def click(data):
        nonlocal sequence
        sequence+=1
        session.calls.clear()
        query={'id':str(sequence),'from':{'id':202,'is_bot':False,'first_name':'Test'},
            'chat_instance':'test','data':data,'message':{'message_id':10,'date':0,
            'chat':{'id':202,'type':'private'},'text':'Menu'}}
        await app.dispatcher.feed_update(app.bot,Update.model_validate({'update_id':sequence,'callback_query':query}))
    def rows():
        with runtime.get_connection() as conn:
            return conn.execute('SELECT * FROM reminders ORDER BY id').fetchall()
    context=app.dispatcher.fsm.get_context(bot=app.bot,chat_id=202,user_id=202)
    await send('/start')
    assert 'سامانه جامع' in session.calls[0].text
    await send('#یادآوری',chat=-100999,thread=38)
    link=session.calls[0].reply_markup.inline_keyboard[0][0].url
    assert link=='https://t.me/test_bot?start=reminder_-100999_38'
    await send('یادآوری',chat=-100999,thread=38)
    assert session.calls[0].reply_markup.inline_keyboard[0][0].url==link
    await send('این یک یادآوری برای جلسه است',chat=-100999)
    assert session.calls==[]
    await send('#یادآوری فردا ساعت ۱۰:۳۰ جلسه',chat=-100999,thread=38)
    assert rows()[0]['remind_at']=='1405/07/25 10:30'
    assert rows()[0]['message_thread_id']==38
    await send('#یادآوری هر جمعه 10:30 جلسه هفتگی',chat=-100999)
    assert rows()[1]['day_of_week']=='Friday'
    await send('#یادآوری روز ۳۱ هر ماه 10:30 ماهانه',chat=-100999)
    assert rows()[2]['day_of_month']==31
    before=len(rows())
    await send('#یادآوری امروز 08:00 گذشته',chat=-100999)
    await send('#یادآوری فردا 10:30 ناشناس',user=999,chat=-100999)
    assert len(rows())==before
    await send('/start reminder_-100999_38')
    assert await context.get_state()=='Form:interactive_reminder_type'
    assert session.calls[0].reply_markup.inline_keyboard[0][0].callback_data=='remmanage_new'
    await click('remmanage_list_0')
    assert session.calls[0].reply_markup.inline_keyboard[0][0].callback_data=='remmanage_view_1'
    await click('remmanage_view_2')
    assert session.calls[0].show_alert  # Same owner, different topic.
    await click('remmanage_view_1')
    assert 'جلسه' in session.calls[0].text
    await click('remmanage_new')
    await click('rem_type_once')
    await send('فردا')
    await send('٠٩:٣٠')
    assert await context.get_state()=='Form:interactive_reminder_text'
    with runtime.get_connection() as conn:
        conn.execute('UPDATE staff_mapping SET is_active=0 WHERE telegram_user_id=202')
    await send('نباید ثبت شود')
    assert 'فعال' in session.calls[0].text and len(rows())==before
    with runtime.get_connection() as conn:
        conn.execute('UPDATE staff_mapping SET is_active=1 WHERE telegram_user_id=202')
        conn.execute("CREATE TRIGGER fail_reminder BEFORE INSERT ON reminders BEGIN SELECT RAISE(ABORT,'test failure'); END")
    try:
        await send('خطای دیتابیس')
    except sqlite3.IntegrityError:
        pass
    else:
        raise AssertionError('Expected failed insert')
    assert not session.calls and len(rows())==before
    assert await context.get_state()=='Form:interactive_reminder_text'
    with runtime.get_connection() as conn:
        conn.execute('DROP TRIGGER fail_reminder')
    await send('یادآور تعاملی <الف>')
    assert len(rows())==before+1 and await context.get_state() is None
    assert rows()[-1]['remind_at']=='1405/07/25 09:30'
    await send('/start reminder_-100999_None')
    await click('rem_type_weekly')
    await click('remday_invalid')
    assert session.calls[0].show_alert
    await click('remday_Friday')
    await send('10:30')
    await send('هفتگی تعاملی')
    assert rows()[-1]['day_of_week']=='Friday'
    await send('/start reminder_-100999_None')
    await click('rem_type_monthly')
    await send('۳۲')
    assert await context.get_state()=='Form:interactive_reminder_date'
    await click('remday_Friday')
    assert session.calls[0].show_alert
    await send('۲۴')
    await send('10:30')
    await send('ماهانه تعاملی')
    assert rows()[-1]['day_of_month']==24
    await click('rem_type_once')
    assert session.calls[0].show_alert  # Completed form has no target context.
    await send('/start reminder_notvalid_None')
    assert 'نامعتبر' in session.calls[0].text
    await send('/start')
    assert 'سامانه جامع' in session.calls[0].text
    session.calls.clear()
    await deliver_due(runtime.get_connection,app.bot,jdatetime.datetime(1405,7,24,10,30))
    assert len(session.calls)==3  # Two Friday reminders and one monthly reminder.
    session.calls.clear()
    await deliver_due(runtime.get_connection,app.bot,jdatetime.datetime(1405,7,24,10,30))
    assert session.calls==[]
    await send('/start reminder_-100999_38')
    await click('remmanage_delete_1')
    assert len(rows())==before+3  # Confirmation screen must not delete.
    await click('remmanage_confirm_1')
    assert len(rows())==before+2
    await click('remmanage_confirm_1')
    assert session.calls[0].show_alert
    await app.close()

asyncio.run(main())
'''
    root=Path(__file__).resolve().parents[1]
    env=dict(os.environ,PYTHONPATH=str(root),PYTHONIOENCODING='utf-8')
    result=subprocess.run([sys.executable,'-c',script],cwd=tmp_path,env=env,
                          capture_output=True,text=True,encoding='utf-8',timeout=45)
    assert result.returncode==0,result.stdout+result.stderr
