"""Offline scheduler tests with synthetic data and explicit dependencies."""
import asyncio
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import jdatetime
import pytest
from erpbot.scheduler import jobs
from erpbot.core import backup
from erpbot.services.scheduled_reports import tomorrow_report
from test_explicit_bootstrap import run_isolated


def test_scheduler_import_has_no_runtime_or_files(tmp_path):
    run_isolated(tmp_path, """
import sys
from pathlib import Path
from erpbot.scheduler import jobs
assert 'erpbot.core.runtime' not in sys.modules
assert list(Path.cwd().iterdir()) == []
""")


def test_report_matching_escape_and_legacy_dates(assets_db):
    with assets_db.connection() as conn:
        for name, status, start, end, first, second in [
            ('<Active>', '✅ تأیید شده قطعی', '1405/07/25', '1405/07/27', '<type>', None),
            ('Legacy', 'تأیید شده', None, None, '1405/07/25', 'x'),
            ('Pending', 'در انتظار', '1405/07/25', '1405/07/25', 'x', 'x'),
            ('Outside', 'تأیید شده', '1405/07/26', '1405/07/27', 'x', 'x')]:
            conn.execute('INSERT INTO requests(user_name,request_type,status,start_date,end_date,col1,col2) VALUES(?,?,?,?,?,?,?)',
                         (name,'مرخصی',status,start,end,first,second))
    with assets_db.connection() as conn:
        text=tomorrow_report(conn,jdatetime.datetime(1405,7,24,19))
        assert '&lt;Active&gt;' in text and '&lt;type&gt;' in text
        assert 'Legacy' in text and 'Pending' not in text and 'Outside' not in text
        assert tomorrow_report(conn,jdatetime.datetime(1405,8,1,19)) is None


@pytest.mark.parametrize('fails', [False, True])
def test_delivery_rechecks_roles_and_closes_connections(assets_db, fails):
    with assets_db.connection() as conn:
        conn.execute("UPDATE staff_mapping SET role='main_admin' WHERE telegram_user_id IN (202,303)")
    opened=0
    @contextmanager
    def connection():
        nonlocal opened
        with assets_db.connection() as conn:
            opened+=1
            try: yield conn
            finally: opened-=1
    sent=[]
    async def send(recipient):
        assert opened==0
        sent.append(recipient)
        if recipient==101:
            with assets_db.connection() as conn:
                conn.execute("UPDATE staff_mapping SET role='staff' WHERE telegram_user_id=202")
            if fails: raise RuntimeError('simulated delivery failure')
    asyncio.run(jobs.send_to_admins(connection,send))
    assert sent==[101,303]


@pytest.mark.parametrize('cancel', [False, True])
def test_backup_temp_removed_on_creation_failure_or_cancellation(tmp_path, monkeypatch, cancel):
    source=tmp_path/'source.db'
    import sqlite3
    with sqlite3.connect(source) as conn: conn.execute('CREATE TABLE sample(value)')
    created=[]
    real_temp=backup.tempfile.NamedTemporaryFile
    def temp(*args, **kwargs):
        file=real_temp(*args, **kwargs)
        created.append(Path(file.name))
        return file
    monkeypatch.setattr(backup.tempfile,'NamedTemporaryFile',temp)
    if cancel:
        with pytest.raises(asyncio.CancelledError):
            with backup.database_snapshot(source): raise asyncio.CancelledError
    else:
        def fail(*args, **kwargs): raise sqlite3.OperationalError('simulated backup failure')
        monkeypatch.setattr(backup.sqlite3,'connect',fail)
        with pytest.raises(sqlite3.OperationalError):
            with backup.database_snapshot(source): pytest.fail('Creation should fail')
    assert created and all(not path.exists() for path in created)


def test_scheduler_timing_failure_isolation_and_cancellation(monkeypatch):
    times=iter([jdatetime.datetime(1405,7,20,8),jdatetime.datetime(1405,7,20,8),
                jdatetime.datetime(1405,7,25,19),jdatetime.datetime(1405,7,25,19)])
    current=[None]
    async def sleep(seconds):
        assert seconds==60
        try: current[0]=next(times)
        except StopIteration: raise asyncio.CancelledError
    insurance=AsyncMock(side_effect=RuntimeError('insurance unavailable'))
    salary=AsyncMock()
    report=AsyncMock()
    weekly=AsyncMock()
    for name, mock in [('deliver_alerts',insurance),('deliver_salary_notice',salary),
                       ('deliver_tomorrow_report',report),('deliver_backup',weekly)]:
        monkeypatch.setattr(jobs,name,mock)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(jobs.background_schedulers(None,None,lambda:current[0],None,sleep=sleep))
    assert insurance.await_count==2
    salary.assert_awaited_once()
    report.assert_awaited_once()
    weekly.assert_awaited_once()


def test_salary_and_report_delivery_content(assets_db):
    bot=SimpleNamespace(send_message=AsyncMock())
    asyncio.run(jobs.deliver_salary_notice(assets_db.connection,bot))
    assert bot.send_message.await_args.kwargs['chat_id']==101
    assert 'تأمین اجتماعی' in bot.send_message.await_args.kwargs['text']
    bot.send_message.reset_mock()
    asyncio.run(jobs.deliver_tomorrow_report(assets_db.connection,bot,jdatetime.datetime(1405,7,24)))
    bot.send_message.assert_not_awaited()


def test_snapshot_does_not_create_a_missing_source(tmp_path):
    import sqlite3
    source=tmp_path/'missing.db'
    with pytest.raises(sqlite3.OperationalError):
        with backup.database_snapshot(source): pytest.fail('Missing source accepted')
    assert not source.exists()
