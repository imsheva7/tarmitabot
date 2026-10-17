"""Seven-day alert delivery with no real network and no open connection during I/O."""
import asyncio
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
import jdatetime
from erpbot.services import insurance
from erpbot.scheduler.insurance import deliver_alerts


def save(db,third,body='-'):
    with db.connection() as conn:
        insurance.save(conn,101,'CAR <A>','Car','Plate','Company & A',third,body)


def test_only_seven_day_expiries_are_selected_and_bad_legacy_dates_are_skipped(assets_db):
    save(assets_db,'1405/08/01','1405/08/02')
    save(assets_db,'1405/07/30','1405/07/20')
    with assets_db.connection() as conn:
        conn.execute("INSERT INTO vehicle_insurances(third_party_date,body_date) VALUES('invalid',NULL)")
        alerts=insurance.due_alerts(conn,jdatetime.date(1405,7,24))
    assert len(alerts)==1 and alerts[0].due=='1405/08/01'


def test_leap_year_boundary_and_two_due_policies(assets_db):
    save(assets_db,'1404/01/01','1404/01/01')
    with assets_db.connection() as conn:
        assert len(insurance.due_alerts(conn,jdatetime.date(1403,12,24)))==2


def test_alerts_only_go_to_active_connected_main_admins(assets_db):
    save(assets_db,'1405/08/01')
    bot=SimpleNamespace(send_message=AsyncMock())
    asyncio.run(deliver_alerts(assets_db.connection,bot,jdatetime.datetime(1405,7,24,12,30)))
    bot.send_message.assert_awaited_once()
    kwargs=bot.send_message.await_args.kwargs
    assert kwargs['chat_id']==101 and 'CAR &lt;A&gt;' in kwargs['text'] and 'Company &amp; A' in kwargs['text']


def test_failed_recipient_does_not_prevent_other_main_admins(assets_db):
    save(assets_db,'1405/08/01')
    with assets_db.connection() as conn:
        conn.execute("UPDATE staff_mapping SET role='main_admin' WHERE staff_id=4")
    bot=SimpleNamespace(send_message=AsyncMock(side_effect=[RuntimeError('offline'),True]))
    asyncio.run(deliver_alerts(assets_db.connection,bot,jdatetime.datetime(1405,7,24)))
    assert bot.send_message.await_count==2


def test_role_revocation_is_rechecked_before_each_send(assets_db):
    save(assets_db,'1405/08/01')
    with assets_db.connection() as conn:
        conn.execute("UPDATE staff_mapping SET role='main_admin' WHERE staff_id=4")
    async def send(**kwargs):
        with assets_db.connection() as conn:
            conn.execute("UPDATE staff_mapping SET role='staff' WHERE staff_id=4")
    bot=SimpleNamespace(send_message=AsyncMock(side_effect=send))
    asyncio.run(deliver_alerts(assets_db.connection,bot,jdatetime.datetime(1405,7,24)))
    bot.send_message.assert_awaited_once()


def test_connections_close_before_insurance_send(assets_db):
    save(assets_db,'1405/08/01')
    opened=0
    @contextmanager
    def connection():
        nonlocal opened
        with assets_db.connection() as conn:
            opened+=1
            try: yield conn
            finally: opened-=1
    async def send(**kwargs): assert opened==0
    asyncio.run(deliver_alerts(connection,SimpleNamespace(send_message=send),jdatetime.datetime(1405,7,24)))


def test_background_scheduler_checks_insurance_once_per_day(assets_db):
    from erpbot.scheduler.jobs import background_schedulers
    save(assets_db,'1405/07/21')
    save(assets_db,'1405/07/22')
    dates=iter([jdatetime.datetime(1405,7,14,12),jdatetime.datetime(1405,7,14,12,1),jdatetime.datetime(1405,7,15,12)])
    current=[None]
    async def sleep(seconds):
        assert seconds==60
        try: current[0]=next(dates)
        except StopIteration: raise asyncio.CancelledError
    bot=SimpleNamespace(send_message=AsyncMock())
    import pytest
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(background_schedulers(assets_db.connection,bot,lambda:current[0],assets_db.path,sleep=sleep))
    assert bot.send_message.await_count==2
