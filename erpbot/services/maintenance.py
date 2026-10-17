"""Approved reset scopes with backup freshness and atomic server authorization."""
from contextlib import contextmanager
import hashlib
import json
import secrets
from ..core.database import connect,transaction
from ..repositories import maintenance as repository
from .admin_console import authorized_backup
from .personnel import require_admin,PersonnelError,balance_value

TITLES={'requests':'پاک کردن تاریخچه درخواست‌ها و وابستگی‌های آن',
        'assets':'پاک کردن اموال و بیمه‌های ناوگان',
        'leaves':'صفر کردن تمام مانده مرخصی‌ها و پاک کردن دفتر مرخصی',
        'all_except_staff':'پاک کردن درخواست‌ها، اموال، بیمه‌ها، تعطیلات و بازسازی دفتر با مانده فعلی'}


class MaintenanceError(ValueError):
    pass


def validate_target(target):
    if not isinstance(target,str) or target not in TITLES:
        raise MaintenanceError('بخش پاکسازی نامعتبر است.')


def fingerprint(conn):
    digest=hashlib.sha256()
    for line in conn.iterdump():
        digest.update(line.encode('utf-8'))
        digest.update(b'\n')
    return digest.hexdigest()


@contextmanager
def prepared_backup(get_connection,database_path,actor_id):
    with authorized_backup(get_connection,database_path,actor_id) as path:
        with connect(path) as snapshot:
            digest=fingerprint(snapshot)
        yield path,digest


def preview(conn,actor_id,target):
    validate_target(target)
    require_admin(conn,actor_id)
    return repository.counts(conn,target)


def execute(conn,actor_id,target,backup_digest,timestamp):
    validate_target(target)
    if not isinstance(backup_digest,str) or len(backup_digest)!=64 or any(char not in '0123456789abcdef' for char in backup_digest):
        raise MaintenanceError('پشتیبان معتبر برای این عملیات یافت نشد.')
    with transaction(conn):
        require_admin(conn,actor_id)
        if not secrets.compare_digest(fingerprint(conn),backup_digest):
            raise MaintenanceError('داده‌ها پس از تهیه پشتیبان تغییر کرده‌اند؛ دوباره عملیات را تأیید کنید.')
        before=repository.counts(conn,target)
        opening=[]
        if target=='all_except_staff':
            for staff_id,name,value in repository.balances(conn):
                balance=balance_value(value)
                if balance!=0:
                    opening.append((staff_id,name,balance))
        actor=repository.active_staff(conn,actor_id)[0]
        repository.clear(conn,target)
        for staff_id,name,balance in opening:
            repository.record_change(conn,staff_id,name,balance,'مانده افتتاحیه پس از پاکسازی جامع',timestamp)
        repository.record(conn,actor,'database.reset','maintenance',target,
            json.dumps({'deleted':before,'opening_entries':len(opening),'backup_sha256':backup_digest,'timestamp':timestamp},ensure_ascii=False))
        return before
