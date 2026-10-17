"""Report authorization, ownership, totals and fixed export columns on synthetic SQLite."""
import pytest
from erpbot.services import reports
from erpbot.reporting.catalogue import ADMIN_EXPORTS


@pytest.mark.parametrize('actor',[202,303,606,999])
@pytest.mark.parametrize('operation',['export','pending','staff','today'])
def test_admin_reports_deny_ordinary_disabled_and_unknown_accounts(assets_db,actor,operation):
    with assets_db.connection() as conn:
        with pytest.raises(reports.ReportError):
            if operation=='export': reports.admin_export(conn,actor,'staff')
            elif operation=='pending': reports.pending(conn,actor)
            elif operation=='staff': reports.staff_list(conn,actor)
            else: reports.absences(conn,actor,'1405/07/24')


@pytest.mark.parametrize('actor',[101,404,505])
def test_existing_admin_roles_can_read_all_four_exports(assets_db,actor):
    with assets_db.connection() as conn:
        for key in ADMIN_EXPORTS:
            before=conn.total_changes
            report=reports.admin_export(conn,actor,key)
            assert report.filename.endswith('.xlsx')
            assert len(report.sheets)==1
            assert report.sheets[0].headers==tuple(ADMIN_EXPORTS[key][3].values())
            assert conn.total_changes==before


def test_personal_reports_only_include_own_requests_and_assets(assets_db):
    mine=assets_db.request('ماموریت',owner=202)
    other=assets_db.request('ماموریت',owner=303)
    assets_db.assign(owner=2,secret='my-encrypted-password')
    assets_db.assign(owner=3,secret='other-encrypted-password')
    with assets_db.connection() as conn:
        conn.execute("UPDATE requests SET col1='Other confidential data' WHERE id=?",(other,))
        conn.execute("UPDATE user_assets SET details='Other asset' WHERE staff_id=3")
    with assets_db.connection() as conn:
        report=reports.personal_export(conn,202)
        recent=reports.personal_requests(conn,202)
    assert report.owner_staff_id==2 and report.filename=='Report_Owner.xlsx'
    assert len(report.sheets[0].rows)==len(report.sheets[1].rows)==len(recent)==1
    assert report.sheets[0].rows[0][0]==f'REQ-1405-{mine:05d}'
    assert 'Other confidential data' not in str(report) and 'Other asset' not in str(report)
    assert 'encrypted-password' not in str(report) and 'encrypted-secret' not in str(report)


@pytest.mark.parametrize('actor',[606,999])
@pytest.mark.parametrize('operation',['stats','recent','export'])
def test_personal_reports_require_current_active_account(assets_db,actor,operation):
    with assets_db.connection() as conn:
        with pytest.raises(reports.ReportError):
            if operation=='stats': reports.stats(conn,actor,'1405/07')
            elif operation=='recent': reports.personal_requests(conn,actor)
            else: reports.personal_export(conn,actor)


def test_stats_preserve_month_owner_type_and_status_rules(assets_db):
    def insert(kind,days='0',amount=0,status='✅ تأیید شده قطعی',month='1405/07',owner=202,col1='نوع: استحقاقی'):
        with assets_db.connection() as conn:
            conn.execute('INSERT INTO requests(telegram_user_id,request_type,col1,location,amount,status,month_tag) VALUES(?,?,?,?,?,?,?)',
                         (owner,kind,col1,days,amount,status,month))
    insert('مرخصی','2.5')
    insert('مرخصی','2',status='⏳ در انتظار')
    insert('مرخصی','3',month='1405/08')
    insert('مرخصی','4',owner=303)
    insert('مرخصی','invalid')
    insert('مرخصی','8',col1='نوع: استعلاجی')
    insert('مساعده',amount=1000)
    insert('مساعده',amount=2000,status='💳 تسویه و پرداخت شده')
    insert('مساعده',amount=3000,status='⏳ در انتظار')
    insert('تنخواه',amount=4000,status='💳 تسویه و پرداخت شده')
    insert('ماموریت')
    with assets_db.connection() as conn: result=reports.stats(conn,202,'1405/07')
    assert (result.name,result.balance,result.used_leave,result.advances,result.missions)==('Owner',5,2.5,3000,1)


def test_recent_requests_keep_five_newest_and_pending_report_keeps_ten_oldest(assets_db):
    for _ in range(12): assets_db.request('ماموریت')
    with assets_db.connection() as conn:
        recent=reports.personal_requests(conn,202)
        pending=reports.pending(conn,101)
    assert len(recent)==5 and recent[0][0]=='REQ-1405-00012' and recent[-1][0]=='REQ-1405-00008'
    assert [row[0] for row in pending]==list(range(1,11))


@pytest.mark.parametrize('key',["requests; DROP TABLE staff_mapping;--",'unknown','req_extra'])
def test_export_selector_is_a_fixed_whitelist(assets_db,key):
    with assets_db.connection() as conn:
        with pytest.raises(reports.ReportError): reports.admin_export(conn,101,key)
        assert conn.execute('SELECT COUNT(*) FROM staff_mapping').fetchone()[0]==7


def test_administrative_exports_exclude_encrypted_secret_columns(assets_db):
    assets_db.request('مساعده',secret='encrypted-request-secret')
    assets_db.assign(secret='encrypted-asset-secret')
    with assets_db.connection() as conn:
        for key in ('req','assets'):
            report=reports.admin_export(conn,101,key)
            assert 'encrypted-' not in str(report)
    assert 'sensitive_data' not in ADMIN_EXPORTS['req'][3]
    assert 'encrypted_password' not in ADMIN_EXPORTS['assets'][3]


def test_absence_report_preserves_inclusive_dates_and_legacy_text_fallback(assets_db):
    values=[('Inside','ماموریت','شرح','تاریخ','1405/07/23','1405/07/24','✅ تأیید شده قطعی'),
            ('Outside','مرخصی','نوع','متن','1405/07/25','1405/07/26','✅ تأیید شده قطعی'),
            ('Legacy','مرخصی','روز 1405/07/24','شرح',None,None,'✅ تأیید شده قطعی'),
            ('Rejected','مرخصی','1405/07/24','شرح',None,None,'❌ رد شده')]
    with assets_db.connection() as conn:
        conn.executemany('INSERT INTO requests(user_name,request_type,col1,col2,start_date,end_date,status) VALUES(?,?,?,?,?,?,?)',values)
    with assets_db.connection() as conn:
        assert [row[0] for row in reports.absences(conn,101,'1405/07/24')]==['Inside','Legacy']


def test_export_permission_is_rechecked_after_generation(assets_db):
    with assets_db.connection() as conn:
        personal=reports.personal_export(conn,202)
        administrative=reports.admin_export(conn,404,'staff')
        conn.execute('UPDATE staff_mapping SET is_active=0 WHERE staff_id=2')
        conn.execute("UPDATE staff_mapping SET role='staff' WHERE staff_id=4")
    with assets_db.connection() as conn:
        with pytest.raises(reports.ReportError): reports.authorize_export(conn,202,personal)
        with pytest.raises(reports.ReportError): reports.authorize_export(conn,404,administrative)
