"""Export permissions are rechecked after rendering, before a document can leave the bot."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import jdatetime
import pytest
from erpbot.handlers.reports import create_router
from erpbot.services.reports import ReportError


def export_handler(assets_db,renderer,*,personal=False):
    router=create_router(assets_db.connection,lambda:jdatetime.datetime(1405,7,24),renderer=renderer)
    name='send_my_excel_report' if personal else 'send_specific_excel'
    return next(h.callback for h in router.callback_query.handlers if h.callback.__name__==name)


def event(*,personal=False):
    return SimpleNamespace(data='xcl_staff',from_user=SimpleNamespace(id=202 if personal else 404),
        answer=AsyncMock(),message=SimpleNamespace(answer_document=AsyncMock()))


@pytest.mark.parametrize('mode',['admin_role','personal_disabled','personal_remapped'])
def test_permission_changes_while_rendering_block_file_delivery(assets_db,mode):
    personal=mode!='admin_role'
    def render(report):
        with assets_db.connection() as conn:
            if mode=='admin_role': conn.execute("UPDATE staff_mapping SET role='staff' WHERE staff_id=4")
            elif mode=='personal_disabled': conn.execute('UPDATE staff_mapping SET is_active=0 WHERE staff_id=2')
            else:
                conn.execute('UPDATE staff_mapping SET telegram_user_id=NULL WHERE staff_id=2')
                conn.execute('UPDATE staff_mapping SET telegram_user_id=202 WHERE staff_id=3')
        return b'generated workbook'
    callback=event(personal=personal)
    handler=export_handler(assets_db,render,personal=personal)
    with pytest.raises(ReportError): asyncio.run(handler(callback))
    callback.message.answer_document.assert_not_awaited()


def test_failed_generation_sends_no_document_or_success(assets_db):
    def render(report): raise RuntimeError('renderer failed')
    callback=event()
    asyncio.run(export_handler(assets_db,render)(callback))
    callback.message.answer_document.assert_not_awaited()
    assert callback.answer.await_args.kwargs['show_alert']


def test_renderer_runs_off_event_loop_with_database_connection_closed(assets_db):
    import threading
    from contextlib import contextmanager
    opened=0
    main_thread=threading.get_ident()
    @contextmanager
    def connection():
        nonlocal opened
        with assets_db.connection() as conn:
            opened+=1
            try: yield conn
            finally: opened-=1
    def render(report):
        assert threading.get_ident()!=main_thread and opened==0
        return b'workbook bytes'
    router=create_router(connection,lambda:jdatetime.datetime(1405,7,24),renderer=render)
    handler=next(h.callback for h in router.callback_query.handlers if h.callback.__name__=='send_specific_excel')
    callback=event()
    asyncio.run(handler(callback))
    document=callback.message.answer_document.await_args.args[0]
    assert document.data==b'workbook bytes' and document.filename=='Staff_Mapping_Report.xlsx'
