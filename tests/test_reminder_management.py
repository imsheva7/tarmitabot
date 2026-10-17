import pytest
from test_reminders_service import reminders_db
from erpbot.services import reminders as service


def test_management_is_scoped_by_owner_group_and_topic(reminders_db):
    db=reminders_db
    rid=db.save()
    with db.connection() as conn:
        for actor,chat,thread in [(999,-100999,38),(101,-100888,38),(101,-100999,None)]:
            with pytest.raises(service.ReminderError):
                service.manage(conn,actor,chat,thread,reminder_id=rid,delete=True)
        assert len(service.manage(conn,101,-100999,38))==1
        assert service.manage(conn,101,-100999,None)==[]
        conn.execute('UPDATE staff_mapping SET is_active=0 WHERE telegram_user_id=101')
    with db.connection() as conn:
        with pytest.raises(service.ReminderError):
            service.manage(conn,101,-100999,38,reminder_id=rid,delete=True)
        assert conn.execute('SELECT COUNT(*) FROM reminders').fetchone()[0]==1


def test_list_paginates_and_delete_removes_only_selected_owned_record(reminders_db):
    db=reminders_db
    ids=[db.save(content=f'item {i}') for i in range(8)]
    with db.connection() as conn:
        assert len(service.manage(conn,101,-100999,38))==6
        assert len(service.manage(conn,101,-100999,38,page=1))==3
        service.manage(conn,101,-100999,38,reminder_id=ids[0],delete=True)
        assert conn.execute('SELECT COUNT(*) FROM reminders').fetchone()[0]==7
        with pytest.raises(service.ReminderError):
            service.manage(conn,101,-100999,38,reminder_id=ids[0],delete=True)


@pytest.mark.parametrize('number',[-1,0,2**64,True])
def test_invalid_management_id_rejected(reminders_db,number):
    with reminders_db.connection() as conn:
        with pytest.raises(service.ReminderError):
            service.manage(conn,101,-100999,38,reminder_id=number)
