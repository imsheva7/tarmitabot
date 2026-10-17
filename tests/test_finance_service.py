"""Financial roles, request types, quotas and atomic status changes on SQLite."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import sqlite3
import pytest
from erpbot.core.database import transaction
from erpbot.services import finance
from erpbot.services.requests import create_request


@pytest.mark.parametrize('text,value',[
    ('۱۲۳,۴۵۶',123456),('٠٠١٢',12),('0',0),('9,000 ریال',9000),
])
def test_amount_formats(text,value):
    assert finance.amount_value(text,allow_rial=True)==value


@pytest.mark.parametrize('text',['-1','1.5','9'*5000,str(2**63),'نامعتبر','',None])
def test_invalid_or_overflow_amounts_are_rejected(text):
    with pytest.raises(finance.FinanceError): finance.amount_value(text)


@pytest.mark.parametrize('text,valid',[
    ('۶۰۳۷۹۹۱۲۳۴۵۶۷۸۹۰',True),('ir'+'0'*24,True),('1'*24,True),
    ('1'*15,False),('IR'+'a'*24,False),('',False),
])
def test_existing_card_and_sheba_format_rules(text,valid):
    assert finance.valid_card(text)==valid


@pytest.mark.parametrize('action,kind,allowed',[
    ('approve','مساعده',[101]),('approve','تنخواه',[101]),('approve','خرید ملزومات',[101]),
    ('paid','مساعده',[101,404]),('paid','تنخواه',[101,404]),('bought','خرید ملزومات',[101,505]),
])
def test_role_matrix_is_preserved(assets_db,action,kind,allowed):
    for actor in (101,202,303,404,505,606,999):
        rid=assets_db.request(kind)
        if action!='approve':
            with assets_db.connection() as conn: finance.decide(conn,101,rid,'approve')
        with assets_db.connection() as conn:
            if actor in allowed:
                assert finance.decide(conn,actor,rid,action).outcome==action
            else:
                with pytest.raises(finance.FinanceError): finance.decide(conn,actor,rid,action)


@pytest.mark.parametrize('action,kind',[
    ('paid','خرید ملزومات'),('bought','مساعده'),('bought','تنخواه'),
    ('paid','تحویل اموال'),('bought','تحویل اموال'),('approve','تحویل اموال'),
])
def test_action_cannot_change_wrong_request_type(assets_db,action,kind):
    rid=assets_db.request(kind)
    with assets_db.connection() as conn:
        assert finance.decide(conn,101,rid,action).outcome=='invalid_type'
    assert 'در انتظار' in assets_db.status(rid)


@pytest.mark.parametrize('action,kind',[('paid','مساعده'),('bought','خرید ملزومات')])
def test_completion_requires_approval_and_cannot_repeat(assets_db,action,kind):
    rid=assets_db.request(kind)
    with assets_db.connection() as conn:
        assert finance.decide(conn,101,rid,action).outcome=='already_processed'
        assert finance.decide(conn,101,rid,'approve').outcome=='approve'
        assert finance.decide(conn,101,rid,'approve').outcome=='already_processed'
        assert finance.decide(conn,101,rid,action).outcome==action
        assert finance.decide(conn,101,rid,action).outcome=='already_processed'


def test_advance_capacity_counts_pending_approved_and_paid_but_not_rejected_or_cancelled(assets_db):
    statuses=['⏳ در انتظار تأیید نهایی مدیریت','✅ تأیید شده قطعی','💳 تسویه و پرداخت شده','❌ رد شده','❌ لغو شده توسط پرسنل']
    for status in statuses:
        rid=assets_db.request('مساعده',amount=1000)
        with assets_db.connection() as conn:
            conn.execute('UPDATE requests SET status=? WHERE id=?',(status,rid))
    assets_db.request('تنخواه',amount=9000)
    with assets_db.connection() as conn:
        assert finance.advance_capacity(conn,202,'1405/07',24)==(80_000_000-3000,3000,80_000_000)
        assert finance.advance_capacity(conn,202,'1405/08',1)==(3333333,0,3333333)


def test_final_persistence_rechecks_advance_limit(assets_db):
    assets_db.request('مساعده',amount=70_000_000)
    with pytest.raises(finance.FinanceError): assets_db.request('مساعده',amount=11_000_000)
    with assets_db.connection() as conn:
        assert conn.execute('SELECT COUNT(*) FROM requests').fetchone()[0]==1


def test_simultaneous_final_submissions_cannot_exceed_limit(assets_db):
    barrier=Barrier(2)
    def submit():
        try:
            with assets_db.connection() as conn:
                barrier.wait(timeout=10)
                with transaction(conn):
                    create_request(conn,202,'Owner','Telegram','مساعده','مبلغ','دلیل','محفوظ','-',
                        year=1405,created_at='1405/07/24 12:00',month_tag='1405/07',amount=50_000_000)
            return 'saved'
        except finance.FinanceError:
            return 'denied'
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(submit),pool.submit(submit)]
        assert sorted(future.result(timeout=15) for future in futures)==['denied','saved']


@pytest.mark.parametrize('action,kind',[('approve','مساعده'),('paid','تنخواه'),('bought','خرید ملزومات')])
def test_concurrent_actions_commit_only_once(assets_db,action,kind):
    rid=assets_db.request(kind)
    if action!='approve':
        with assets_db.connection() as conn: finance.decide(conn,101,rid,'approve')
    barrier=Barrier(2)
    def decide():
        with assets_db.connection() as conn:
            barrier.wait(timeout=10)
            return finance.decide(conn,101,rid,action).outcome
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(decide),pool.submit(decide)]
        assert sorted(future.result(timeout=15) for future in futures)==sorted([action,'already_processed'])


def test_storage_failure_leaves_request_unchanged(assets_db):
    rid=assets_db.request('مساعده')
    with assets_db.connection() as conn:
        conn.execute("CREATE TRIGGER fail_finance BEFORE UPDATE ON requests BEGIN SELECT RAISE(ABORT,'finance failure'); END")
    with assets_db.connection() as conn:
        with pytest.raises(sqlite3.IntegrityError): finance.decide(conn,101,rid,'approve')
        assert not conn.in_transaction
    assert 'در انتظار' in assets_db.status(rid)


def test_private_recipient_must_be_active_linked_and_have_exact_role(assets_db):
    with assets_db.connection() as conn:
        assert finance.recipient(conn,'finance')==404
        conn.execute("UPDATE staff_mapping SET telegram_user_id=NULL WHERE role='finance'")
    with assets_db.connection() as conn:
        assert finance.recipient(conn,'finance') is None
        conn.execute("UPDATE staff_mapping SET telegram_user_id=-999 WHERE role='finance'")
    with assets_db.connection() as conn:
        assert finance.recipient(conn,'finance') is None
        conn.execute("UPDATE staff_mapping SET telegram_user_id=404,is_active=0 WHERE role='finance'")
    with assets_db.connection() as conn: assert finance.recipient(conn,'finance') is None


@pytest.mark.parametrize('kind',['مساعده','تنخواه','خرید ملزومات'])
def test_final_submit_rechecks_active_employee(assets_db,kind):
    with assets_db.connection() as conn:
        conn.execute('UPDATE staff_mapping SET is_active=0 WHERE staff_id=2')
    with pytest.raises(finance.FinanceError): assets_db.request(kind)
