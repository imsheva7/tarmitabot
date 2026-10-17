"""Committed financial decisions never fall back to a public secret destination."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock
import pytest
from erpbot.handlers.finance_decisions import create_router


def callback(data,user=101,photo=False):
    return SimpleNamespace(data=data,from_user=SimpleNamespace(id=user),answer=AsyncMock(),
        message=SimpleNamespace(text='Request',caption='Invoice',photo=photo,
                                edit_text=AsyncMock(),edit_caption=AsyncMock()))


@pytest.fixture
def decisions(assets_db):
    bot=SimpleNamespace(send_message=AsyncMock())
    decrypt=Mock(return_value='secret-<card>')
    router=create_router(assets_db.connection,bot,-100999,decrypt)
    handler=router.callback_query.handlers[0].callback
    return SimpleNamespace(bot=bot,decrypt=decrypt,handler=handler)


def test_financial_secret_only_goes_to_private_finance_recipient(assets_db,decisions):
    rid=assets_db.request('مساعده')
    event=callback(f'approve_{rid}')
    asyncio.run(decisions.handler(event))
    instructions=[call.kwargs for call in decisions.bot.send_message.await_args_list if 'secret-' in call.kwargs['text']]
    assert len(instructions)==1 and instructions[0]['chat_id']==404
    assert 'secret-&lt;card&gt;' in instructions[0]['text']
    assert instructions[0]['reply_markup'].inline_keyboard[0][0].callback_data==f'paid_{rid}'
    assert 'تأیید شده قطعی' in assets_db.status(rid)


@pytest.mark.parametrize('mode',['inactive','unlinked','wrong_role'])
def test_no_finance_recipient_never_exposes_or_decodes_secret(assets_db,decisions,mode):
    rid=assets_db.request('مساعده')
    update={'inactive':'is_active=0','unlinked':'telegram_user_id=NULL','wrong_role':"role='staff'"}[mode]
    with assets_db.connection() as conn:
        conn.execute(f'UPDATE staff_mapping SET {update} WHERE staff_id=4')
    event=callback(f'approve_{rid}')
    asyncio.run(decisions.handler(event))
    decisions.decrypt.assert_not_called()
    assert all(call.kwargs['chat_id']!=-100999 for call in decisions.bot.send_message.await_args_list)
    assert event.answer.await_args.kwargs['show_alert']
    assert 'تأیید شده قطعی' in assets_db.status(rid)


def test_bad_cipher_reports_notification_failure_after_committed_approval(assets_db,decisions):
    rid=assets_db.request('مساعده')
    decisions.decrypt.side_effect=ValueError('bad key')
    event=callback(f'approve_{rid}')
    asyncio.run(decisions.handler(event))
    assert 'تأیید شده قطعی' in assets_db.status(rid)
    assert len(decisions.bot.send_message.await_args_list)==1  # Employee status only.
    assert event.answer.await_args.kwargs['show_alert']


def test_invoice_caption_and_failed_notification_do_not_rollback_decision(assets_db,decisions):
    rid=assets_db.request('تنخواه')
    decisions.bot.send_message.side_effect=RuntimeError('offline')
    event=callback(f'approve_{rid}',photo=True)
    asyncio.run(decisions.handler(event))
    event.message.edit_caption.assert_awaited_once()
    event.message.edit_text.assert_not_awaited()
    assert 'تأیید شده قطعی' in assets_db.status(rid)
    assert event.answer.await_args.kwargs['show_alert']


def test_purchase_uses_existing_group_fallback_without_financial_secret(assets_db,decisions):
    rid=assets_db.request('خرید ملزومات')
    with assets_db.connection() as conn:
        conn.execute('UPDATE staff_mapping SET is_active=0 WHERE staff_id=5')
    asyncio.run(decisions.handler(callback(f'approve_{rid}')))
    group=[call.kwargs for call in decisions.bot.send_message.await_args_list if call.kwargs['chat_id']==-100999]
    assert len(group)==1 and 'دستور خرید' in group[0]['text']
    assert 'secret-' not in group[0]['text']
    decisions.decrypt.assert_not_called()


def test_duplicate_approval_sends_no_second_payment_instruction(assets_db,decisions):
    rid=assets_db.request('مساعده')
    asyncio.run(decisions.handler(callback(f'approve_{rid}')))
    decisions.bot.send_message.reset_mock()
    asyncio.run(decisions.handler(callback(f'approve_{rid}')))
    decisions.bot.send_message.assert_not_awaited()


def test_database_failure_alerts_without_sending_success_or_instructions(assets_db,decisions):
    rid=assets_db.request('مساعده')
    with assets_db.connection() as conn:
        conn.execute("CREATE TRIGGER fail_decision BEFORE UPDATE ON requests BEGIN SELECT RAISE(ABORT,'failure'); END")
    event=callback(f'approve_{rid}')
    asyncio.run(decisions.handler(event))
    decisions.bot.send_message.assert_not_awaited()
    event.message.edit_text.assert_not_awaited()
    assert event.answer.await_args.kwargs['show_alert']
    assert 'در انتظار' in assets_db.status(rid)
