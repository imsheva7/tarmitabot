"""Real asset forms, middleware, encryption and request approvals with an offline bot."""
import os
from pathlib import Path
import subprocess
import sys


def test_asset_workflows_through_real_dispatcher(tmp_path):
    script=r'''
import asyncio
import sqlite3
from pathlib import Path
import jdatetime
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery,EditMessageText,SendMessage
from aiogram.types import Message,Update,User
from cryptography.fernet import Fernet
from erpbot.bootstrap import initialize_runtime
from erpbot.core import runtime
from erpbot.core.settings import Settings
from erpbot.loader import register_handlers

class OfflineSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls=[]
        self.message_id=100
    async def close(self): pass
    async def make_request(self,bot,method,timeout=None):
        self.calls.append(method)
        if isinstance(method,AnswerCallbackQuery): return True
        assert isinstance(method,(SendMessage,EditMessageText)),type(method)
        self.message_id+=1
        return Message(message_id=self.message_id,date=0,chat={'id':method.chat_id,'type':'private'},text=method.text)
    async def stream_content(self,*args,**kwargs):
        raise AssertionError('No network')
        yield b''

async def main():
    app=initialize_runtime(Settings.from_env({
        'BOT_TOKEN':'123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk',
        'FERNET_KEY':Fernet.generate_key().decode(),'GROUP_ID':'-100999',
    },data_directory=Path.cwd()),configure_logging=False)
    runtime.init_db()
    runtime.get_current_tehran_time=lambda:jdatetime.datetime(1405,7,24,12,30)
    with runtime.get_connection() as conn:
        conn.executemany('INSERT INTO staff_mapping(staff_name,telegram_user_id,role) VALUES(?,?,?)',[
            ('Admin',101,'main_admin'),('Employee',202,'staff'),('Other',303,'staff'),
            ('Finance',404,'finance'),('Purchase',505,'purchase')])
        sid=conn.execute('SELECT staff_id FROM staff_mapping WHERE telegram_user_id=202').fetchone()[0]
    register_handlers()
    session=OfflineSession()
    app.bot.session=session
    app.bot._me=User(id=123456789,is_bot=True,first_name='Bot',username='test_bot')
    sequence=0
    async def click(data,user=202):
        nonlocal sequence
        sequence+=1
        session.calls.clear()
        query={'id':str(sequence),'from':{'id':user,'is_bot':False,'first_name':'Test'},
            'chat_instance':'test','data':data,'message':{'message_id':10,'date':0,
            'chat':{'id':user,'type':'private'},'from':{'id':123456789,'is_bot':True,'first_name':'Bot'},'text':'Menu'}}
        await app.dispatcher.feed_update(app.bot,Update.model_validate({'update_id':sequence,'callback_query':query}))
    async def send(text,user=202):
        nonlocal sequence
        sequence+=1
        session.calls.clear()
        message={'message_id':sequence,'date':0,'chat':{'id':user,'type':'private'},
            'from':{'id':user,'is_bot':False,'first_name':'Test'},'text':text}
        await app.dispatcher.feed_update(app.bot,Update.model_validate({'update_id':sequence,'message':message}))
    def assets():
        with runtime.get_connection() as conn:
            return conn.execute('SELECT * FROM user_assets ORDER BY id').fetchall()
    def latest_request():
        with runtime.get_connection() as conn:
            return conn.execute('SELECT * FROM requests ORDER BY id DESC LIMIT 1').fetchone()
    async def employee_form(kind):
        await click('req_asset')
        await click('asset_sel_'+kind)
        if kind=='car':
            for text in ('CAR-01','پلاک <الف>','سواری','۱۲۳۴','شرح خودرو'): await send(text)
        elif kind=='fuel':
            for text in ('FUEL-01','private-<pass>','10','20','30'): await send(text)
        elif kind=='pos':
            await send('POS-01')
            await send('بانک آزمایشی')
            await click('poschg_yes')
        else:
            await send('PR-01')
            await click('prchg_no')
        context=app.dispatcher.fsm.get_context(bot=app.bot,chat_id=202,user_id=202)
        assert await context.get_state()=='Form:asset_'+kind+'_preview'
        await click('asset_'+kind+'_submit_final')
        assert await context.get_state() is None
        request=latest_request()
        assert request['request_type']=='تحویل اموال'
        assert request['admin_msg_id'] is not None
        for call in session.calls:
            if isinstance(call,SendMessage) and call.chat_id==-100999:
                assert 'private-' not in call.text
        await click('approve_'+str(request['id']),user=404)
        assert session.calls[-1].show_alert
        before=len(assets())
        await click('approve_'+str(request['id']),user=101)
        assert len(assets())==before+1
        await click('approve_'+str(request['id']),user=101)
        assert len(assets())==before+1
        return assets()[-1]

    for kind in ('car','fuel','pos','printer'):
        row=await employee_form(kind)
        if kind=='fuel':
            assert 'private-' not in row['details']
            assert row['encrypted_password']!='private-<pass>'
            assert 'private-<pass>' in runtime.decrypt_data(row['encrypted_password'])
    # Return request remains pending until main admin approval.
    aid=assets()[0]['id']
    await click('retasset_'+str(aid),user=303)
    assert session.calls[-1].show_alert
    await click('req_return_asset')
    await click('retasset_'+str(aid))
    await send('عودت آزمایشی')
    await click('return_submit_final')
    rid=latest_request()['id']
    assert assets()[0]['is_active']==1
    await click('approve_'+str(rid),user=101)
    assert assets()[0]['is_active']==0 and assets()[0]['return_date']=='1405/07/24'
    await click('confirmasset_'+str(aid))
    assert session.calls[-1].show_alert

    # Existing finance/purchase admin rights remain valid for direct assignments.
    async def admin_start(kind,actor=404):
        await click('admin_assign_asset',actor)
        await click('asgn_new_step1',actor)
        await click('asgnuser_'+str(sid),actor)
        await click('asgntype_'+kind,actor)
    await admin_start('car')
    for text in ('ADM-CAR','پلاک','سواری','۱۲۳۴','شرح مدیر'): await send(text,404)
    assert assets()[-1]['asset_type']=='خودروی سازمانی'
    await admin_start('fuel')
    for text in ('ADM-FUEL','admin-<secret>','10','20','30'): await send(text,404)
    fuel=assets()[-1]
    assert runtime.decrypt_data(fuel['encrypted_password'])=='admin-<secret>'
    assert 'admin-' not in fuel['details']
    await admin_start('pos',505)
    await send('ADM-POS',505)
    await send('بانک',505)
    await click('admposchg_yes',505)
    assert assets()[-1]['asset_type']=='کارت‌خوان'
    await admin_start('printer',505)
    await send('ADM-PR',505)
    await click('admprchg_no',505)
    aid=assets()[-1]['id']
    assert assets()[-1]['asset_type']=='پرینتر جیبی'
    await click('confirmasset_'+str(aid),303)
    assert session.calls[-1].show_alert
    await click('confirmasset_'+str(aid))
    assert 'تأیید قطعی توسط پرسنل' in assets()[-1]['approval_status']
    await click('confirmasset_'+str(aid))
    assert session.calls[-1].show_alert
    await click('asgn_list_active',404)
    assert any(isinstance(call,SendMessage) and 'admin-&lt;secret&gt;' in call.text for call in session.calls)
    await click('asgnedit_'+str(aid),404)
    await send('توضیح تازه',404)
    assert assets()[-1]['details']=='توضیح تازه'
    await click('asgndel_'+str(aid),505)
    assert assets()[-1]['is_active']==0
    # Role revocation while a message form is open must prevent its final mutation.
    await admin_start('printer',404)
    with runtime.get_connection() as conn:
        conn.execute("UPDATE staff_mapping SET role='staff' WHERE telegram_user_id=404")
    count=len(assets())
    await send('نباید ثبت شود',404)
    assert 'غیرمجاز' in session.calls[-1].text and len(assets())==count
    with runtime.get_connection() as conn:
        conn.execute("UPDATE staff_mapping SET role='finance' WHERE telegram_user_id=404")
    await send('RETRY-PR',404)
    with runtime.get_connection() as conn:
        conn.execute("CREATE TRIGGER fail_asset BEFORE INSERT ON user_assets BEGIN SELECT RAISE(ABORT,'test failure'); END")
    try:
        await click('admprchg_yes',404)
    except sqlite3.IntegrityError:
        pass
    else: raise AssertionError('Expected insert failure')
    assert len(assets())==count
    assert not any(isinstance(call,SendMessage) for call in session.calls)
    with runtime.get_connection() as conn: conn.execute('DROP TRIGGER fail_asset')
    await click('admprchg_yes',404)
    assert len(assets())==count+1
    # Ownership is checked again when a stale return preview is submitted.
    aid=assets()[-1]['id']
    await click('retasset_'+str(aid))
    await send('درخواست عودت')
    with runtime.get_connection() as conn:
        conn.execute('UPDATE user_assets SET staff_id=(SELECT staff_id FROM staff_mapping WHERE telegram_user_id=303) WHERE id=?',(aid,))
    previous_request=latest_request()['id']
    await click('return_submit_final')
    assert session.calls[-1].show_alert and latest_request()['id']==previous_request
    for payload in ('retasset_bad','confirmasset_'+'9'*100,'asgndel_²','asgnuser_-1','asgnedit_0'):
        await click(payload,101)
        assert session.calls[-1].show_alert
    await app.close()

asyncio.run(main())
'''
    root=Path(__file__).resolve().parents[1]
    env=dict(os.environ,PYTHONPATH=str(root),PYTHONIOENCODING='utf-8')
    result=subprocess.run([sys.executable,'-c',script],cwd=tmp_path,env=env,capture_output=True,text=True,encoding='utf-8',timeout=60)
    assert result.returncode==0,result.stdout+result.stderr
