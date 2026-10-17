"""Reminder parsing, persistence and Jalali scheduling rules on synthetic data."""
from contextlib import contextmanager
from types import SimpleNamespace
import asyncio
import sqlite3
from unittest.mock import AsyncMock
import jdatetime
import pytest
from erpbot.core.database import connect
from erpbot.services import reminders as service
from erpbot.scheduler.reminders import deliver_due

NOW = jdatetime.datetime(1405,7,24,9,0)


@pytest.fixture
def reminders_db(tmp_path):
    path=tmp_path/'reminders-only.db'
    def connection():
        return connect(path)
    with connection() as conn:
        conn.executescript("""
            CREATE TABLE staff_mapping(staff_id INTEGER PRIMARY KEY,telegram_user_id INTEGER,staff_name TEXT,is_active INTEGER);
            INSERT INTO staff_mapping VALUES(1,101,'کاربر <الف>',1),(2,202,'غیرفعال',0);
            CREATE TABLE reminders(id INTEGER PRIMARY KEY,chat_id INTEGER,message_thread_id INTEGER,
                telegram_user_id INTEGER,user_name TEXT,remind_type TEXT,day_of_week TEXT,day_of_month INTEGER,
                remind_time TEXT,remind_at TEXT,text_content TEXT,is_sent INTEGER DEFAULT 0,last_fired TEXT);
        """)
    def save(kind='once',when='1405/07/24',time='10:30',content='متن <الف>',actor=101,now=NOW):
        spec=service.build_spec(kind,when,time,content,now)
        with connection() as conn:
            return service.register(conn,actor,-100999,38,spec,now)
    return SimpleNamespace(connection=connection,save=save,path=path)


@pytest.mark.parametrize('text,kind,when,time',[
    ('#یادآوری فردا ساعت ۱۰:۳۰ جلسه','once','1405/07/25','10:30'),
    ('#یادآوری پس‌فردا 9:00 متن','once','1405/07/26','09:00'),
    ('#یادآوری امروز 10:00 متن','once','1405/07/24','10:00'),
    ('#یادآوری ۱۴۰۵/۷/۲۵ ٠٩:٣٠ متن','once','1405/07/25','09:30'),
    ('#یادآوری هر سه‌شنبه ساعت 9:30 متن\nخط دوم','weekly','Tuesday','09:30'),
    ('#یادآوری روز اول هر ماه 08:00 متن','monthly',1,'08:00'),
    ('#یادآوری روز یک هر ماه ساعت 09:00 متن','monthly',1,'09:00'),
    ('#یادآوری روز ۳۱ هر ماه 21:00 متن','monthly',31,'21:00'),
])
def test_persian_command_patterns(text,kind,when,time):
    spec=service.parse_group(text,NOW)
    assert (spec.kind,spec.when,spec.time)==(kind,when,time)
    assert spec.content.strip()


@pytest.mark.parametrize('text',[
    '#یادآوری امروز 09:00 متن','#یادآوری امروز 08:59 متن',
    '#یادآوری فردا 24:00 متن','#یادآوری فردا 10:60 متن',
    '#یادآوری روز ۰ هر ماه 10:00 متن','#یادآوری روز ۳۲ هر ماه 10:00 متن',
    '#یادآوری 1405/12/30 10:00 متن','#یادآوری هر نادرست 10:00 متن',
    '#یادآوری متن نامعتبر','#یادآوری فردا 10:00   ',
])
def test_invalid_or_past_commands_are_rejected(text):
    with pytest.raises(service.ReminderError):
        service.parse_group(text,NOW)


@pytest.mark.parametrize('payload',[
    'reminder_bad_None','reminder_123_None','reminder_-100_0',
    'reminder_-100_-1','reminder_-100_999999999999999999999999999',
    'reminder_-9999999999999999999999999_None','reminder_-100_None_extra',
])
def test_malformed_deep_links_are_bounded(payload):
    with pytest.raises(service.ReminderError):
        service.parse_link(payload)


def test_old_deep_link_formats_still_work():
    assert service.parse_link('reminder_-100999_None')==(-100999,None)
    assert service.parse_link('reminder_-100999_38')==(-100999,38)


@pytest.mark.parametrize('actor',[202,999])
def test_register_rechecks_active_staff(reminders_db,actor):
    with pytest.raises(service.ReminderError):
        reminders_db.save(actor=actor)
    with reminders_db.connection() as conn:
        assert conn.execute('SELECT COUNT(*) FROM reminders').fetchone()[0]==0


@pytest.mark.parametrize('year,month,last_day',[(1405,7,30),(1405,12,29),(1403,12,30),(1405,6,31)])
def test_month_end_folds_missing_days_to_last_jalali_day(reminders_db,year,month,last_day):
    now=jdatetime.datetime(year,month,last_day,10,30)
    for day in (29,30,31):
        reminders_db.save('monthly',day)
    with reminders_db.connection() as conn:
        due=service.due(conn,now)
    assert len(due)==32-last_day


def test_midmonth_does_not_send_later_days(reminders_db):
    reminders_db.save('monthly',24)
    reminders_db.save('monthly',25)
    with reminders_db.connection() as conn:
        assert len(service.due(conn,jdatetime.datetime(1405,7,24,10,30)))==1


def test_all_kinds_persist_delivery_markers_and_do_not_resend(reminders_db):
    reminders_db.save()
    reminders_db.save('weekly','Friday')
    reminders_db.save('monthly',24)
    bot=SimpleNamespace(send_message=AsyncMock())
    now=jdatetime.datetime(1405,7,24,10,30)
    asyncio.run(deliver_due(reminders_db.connection,bot,now))
    assert bot.send_message.await_count==3
    for call in bot.send_message.await_args_list:
        assert call.kwargs['chat_id']==-100999 and call.kwargs['message_thread_id']==38
        assert 'کاربر &lt;الف&gt;' in call.kwargs['text'] and 'متن &lt;الف&gt;' in call.kwargs['text']
    # A new cycle uses new database connections, as after a scheduler restart.
    asyncio.run(deliver_due(reminders_db.connection,bot,now))
    assert bot.send_message.await_count==3
    with reminders_db.connection() as conn:
        rows=conn.execute('SELECT is_sent,last_fired FROM reminders ORDER BY id').fetchall()
    assert [tuple(row) for row in rows]==[(1,None),(0,'1405/07/24'),(0,'1405/07/24')]


def test_recurring_failures_are_retryable_and_other_reminders_continue(reminders_db):
    reminders_db.save('weekly','Friday')
    reminders_db.save('monthly',24)
    bot=SimpleNamespace(send_message=AsyncMock(side_effect=[RuntimeError('offline'),True]))
    now=jdatetime.datetime(1405,7,24,10,30)
    asyncio.run(deliver_due(reminders_db.connection,bot,now))
    with reminders_db.connection() as conn:
        assert [row[0] for row in conn.execute('SELECT last_fired FROM reminders ORDER BY id')]==[None,'1405/07/24']
    bot.send_message.side_effect=None
    asyncio.run(deliver_due(reminders_db.connection,bot,now))
    assert bot.send_message.await_count==3


@pytest.mark.parametrize('kind,when,next_date',[
    ('weekly','Friday',(1405,8,1)), ('monthly',24,(1405,8,24)),
])
def test_recurring_reminders_become_due_again_in_next_period(reminders_db,kind,when,next_date):
    reminders_db.save(kind,when)
    bot=SimpleNamespace(send_message=AsyncMock())
    asyncio.run(deliver_due(reminders_db.connection,bot,jdatetime.datetime(1405,7,24,10,30)))
    asyncio.run(deliver_due(reminders_db.connection,bot,jdatetime.datetime(*next_date,10,30)))
    assert bot.send_message.await_count==2


def test_delivery_holds_no_connection_during_network_call(reminders_db):
    reminders_db.save()
    opened=0
    @contextmanager
    def connection():
        nonlocal opened
        with reminders_db.connection() as conn:
            opened+=1
            try:
                yield conn
            finally:
                opened-=1
    async def send(**kwargs):
        assert opened==0
    asyncio.run(deliver_due(connection,SimpleNamespace(send_message=send),jdatetime.datetime(1405,7,24,10,30)))
    with reminders_db.connection() as conn:
        assert conn.execute('SELECT is_sent FROM reminders').fetchone()[0]==1


def test_failed_marker_update_does_not_claim_delivery_in_database(reminders_db):
    reminders_db.save()
    with reminders_db.connection() as conn:
        conn.execute("CREATE TRIGGER fail_marker BEFORE UPDATE ON reminders BEGIN SELECT RAISE(ABORT,'failed marker'); END")
    bot=SimpleNamespace(send_message=AsyncMock())
    asyncio.run(deliver_due(reminders_db.connection,bot,jdatetime.datetime(1405,7,24,10,30)))
    with reminders_db.connection() as conn:
        assert conn.execute('SELECT is_sent FROM reminders').fetchone()[0]==0
    bot.send_message.assert_awaited_once()
