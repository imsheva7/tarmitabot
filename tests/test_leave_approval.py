
import sqlite3

import pytest

from erpbot.services.leave_approval import approve_annual_leave


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")

    conn.executescript(
        """
        CREATE TABLE staff_mapping (
            staff_id INTEGER PRIMARY KEY,
            telegram_user_id INTEGER,
            leave_balance REAL
        );

        CREATE TABLE requests (
            id INTEGER PRIMARY KEY,
            telegram_user_id INTEGER,
            user_name TEXT,
            req_code TEXT,
            request_type TEXT,
            col1 TEXT,
            location TEXT,
            status TEXT
        );

        CREATE TABLE request_replacements (
            request_id INTEGER PRIMARY KEY,
            response TEXT
        );

        CREATE TABLE request_effects (
            request_id INTEGER NOT NULL,
            effect_type TEXT NOT NULL,
            PRIMARY KEY (request_id, effect_type)
        );

        CREATE TABLE leave_ledger (
            id INTEGER PRIMARY KEY,
            staff_id INTEGER,
            staff_name TEXT,
            change_amount REAL,
            description TEXT,
            registered_by TEXT,
            created_at TEXT
        );
        """
    )

    conn.execute(
        "INSERT INTO staff_mapping VALUES (1, 100, 5)"
    )

    conn.execute(
        """
        INSERT INTO leave_ledger
            (staff_id, staff_name, change_amount)
        VALUES (1, 'Test Staff', 5)
        """
    )

    conn.execute(
        """
        INSERT INTO requests VALUES
            (
                10,
                100,
                'Test Staff',
                'REQ-TEST',
                'مرخصی',
                'نوع: استحقاقی',
                '3',
                '⏳ در انتظار تأیید نهایی مدیریت'
            )
        """
    )

    conn.commit()

    yield conn

    conn.close()


def get_balance(db):
    return db.execute(
        "SELECT leave_balance FROM staff_mapping WHERE staff_id = 1"
    ).fetchone()[0]


def get_status(db):
    return db.execute(
        "SELECT status FROM requests WHERE id = 10"
    ).fetchone()[0]


def get_effect_count(db):
    return db.execute(
        "SELECT COUNT(*) FROM request_effects"
    ).fetchone()[0]


def get_ledger_count(db):
    return db.execute(
        "SELECT COUNT(*) FROM leave_ledger"
    ).fetchone()[0]


def test_normal_approval(db):
    result = approve_annual_leave(db, 10)

    assert result.outcome == "approved"
    assert result.balance == 2
    assert get_balance(db) == 2
    assert get_status(db) == "✅ تأیید شده قطعی"
    assert get_effect_count(db) == 1
    assert get_ledger_count(db) == 2


def test_insufficient_balance(db):
    db.execute(
        "UPDATE staff_mapping SET leave_balance = 2"
    )
    db.commit()

    result = approve_annual_leave(db, 10)

    assert result.outcome == "needs_override"
    assert get_balance(db) == 2
    assert get_effect_count(db) == 0
    assert get_ledger_count(db) == 1
    assert "در انتظار" in get_status(db)


def test_exceptional_approval(db):
    db.execute(
        "UPDATE staff_mapping SET leave_balance = 2"
    )
    db.execute(
        "UPDATE leave_ledger SET change_amount = 2"
    )
    db.commit()

    result = approve_annual_leave(
        db,
        10,
        exceptional=True,
    )

    assert result.outcome == "exceptional_approved"
    assert result.balance == -1
    assert get_balance(db) == -1
    assert get_effect_count(db) == 1
    assert get_ledger_count(db) == 2


def test_no_duplicate_debit(db):
    first = approve_annual_leave(db, 10)
    second = approve_annual_leave(db, 10)

    assert first.outcome == "approved"
    assert second.outcome == "already_processed"
    assert get_balance(db) == 2
    assert get_effect_count(db) == 1
    assert get_ledger_count(db) == 2


def test_replacement_must_approve(db):
    db.execute(
        """
        INSERT INTO request_replacements
        VALUES (10, NULL)
        """
    )
    db.commit()

    result = approve_annual_leave(db, 10)

    assert result.outcome == "replacement_pending"
    assert get_balance(db) == 5
    assert get_effect_count(db) == 0
    assert get_ledger_count(db) == 1


def test_balance_rechecked_after_first_click(db):
    first = approve_annual_leave(db, 10)

    assert first.outcome == "approved"

    # The normal path was completed.
    # A later exceptional attempt must not debit again.
    second = approve_annual_leave(
        db,
        10,
        exceptional=True,
    )

    assert second.outcome == "already_processed"
    assert get_balance(db) == 2
    assert get_effect_count(db) == 1


def test_balance_changed_before_exceptional_confirmation(db):
    db.execute(
        "UPDATE staff_mapping SET leave_balance = 2"
    )
    db.commit()

    first = approve_annual_leave(db, 10)

    assert first.outcome == "needs_override"
    assert get_balance(db) == 2

    # Another operation changes the current balance
    # before the manager's second confirmation.
    db.execute(
        "UPDATE staff_mapping SET leave_balance = 4"
    )
    db.commit()

    second = approve_annual_leave(
        db,
        10,
        exceptional=True,
    )

    assert second.outcome == "exceptional_approved"
    assert second.balance == 1
    assert get_balance(db) == 1
    assert get_effect_count(db) == 1


def test_replacement_rejection_blocks_exceptional_approval(db):
    db.execute(
        """
        INSERT INTO request_replacements
        VALUES (10, 'rejected')
        """
    )
    db.execute(
        "UPDATE staff_mapping SET leave_balance = 1"
    )
    db.commit()

    result = approve_annual_leave(
        db,
        10,
        exceptional=True,
    )

    assert result.outcome == "replacement_pending"
    assert get_balance(db) == 1
    assert get_effect_count(db) == 0
    assert get_ledger_count(db) == 1


def test_missing_request(db):
    result = approve_annual_leave(db, 999)

    assert result.outcome == "not_found"
    assert get_balance(db) == 5
    assert get_effect_count(db) == 0


def test_non_annual_leave_is_rejected(db):
    db.execute(
        """
        UPDATE requests
        SET request_type = 'مأموریت'
        WHERE id = 10
        """
    )
    db.commit()

    result = approve_annual_leave(
        db,
        10,
        exceptional=True,
    )

    assert result.outcome == "not_annual_leave"
    assert get_balance(db) == 5
    assert get_effect_count(db) == 0


def test_invalid_leave_days(db):
    db.execute(
        """
        UPDATE requests
        SET location = '-3'
        WHERE id = 10
        """
    )
    db.commit()

    result = approve_annual_leave(db, 10)

    assert result.outcome == "invalid_days"
    assert get_balance(db) == 5
    assert get_effect_count(db) == 0


def test_already_rejected_request_cannot_be_approved(db):
    db.execute(
        """
        UPDATE requests
        SET status = '❌ رد شده'
        WHERE id = 10
        """
    )
    db.commit()

    result = approve_annual_leave(
        db,
        10,
        exceptional=True,
    )

    assert result.outcome == "already_processed"
    assert get_balance(db) == 5
    assert get_effect_count(db) == 0


def test_existing_debit_marker_prevents_second_debit(db):
    db.execute(
        """
        INSERT INTO request_effects
            (request_id, effect_type)
        VALUES (10, 'leave_debit')
        """
    )
    db.commit()

    result = approve_annual_leave(db, 10)

    assert result.outcome == "already_processed"
    assert get_balance(db) == 5
    assert get_effect_count(db) == 1
    assert get_ledger_count(db) == 1
