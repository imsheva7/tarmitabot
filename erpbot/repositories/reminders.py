"""Reminder SQL; connections and transactions are owned by callers."""


def active_staff_name(conn, telegram_id):
    row = conn.execute("SELECT staff_name FROM staff_mapping WHERE telegram_user_id=? AND is_active=1", (telegram_id,)).fetchone()
    return row[0] if row else None


def insert(conn, chat_id, thread_id, actor_id, name, spec):
    return conn.execute("""INSERT INTO reminders(chat_id,message_thread_id,telegram_user_id,user_name,
        remind_type,day_of_week,day_of_month,remind_time,remind_at,text_content,is_sent)
        VALUES(?,?,?,?,?,?,?,?,?,?,0)""", (
        chat_id,thread_id,actor_id,name,spec.kind,
        spec.when if spec.kind == "weekly" else None,
        spec.when if spec.kind == "monthly" else None,
        spec.time if spec.kind != "once" else None,
        f"{spec.when} {spec.time}" if spec.kind == "once" else None,spec.content,
    )).lastrowid


def due(conn, full_time, date, time, weekday, month_days):
    columns = "id,chat_id,message_thread_id,user_name,text_content,remind_type"
    once = conn.execute(f"SELECT {columns} FROM reminders WHERE remind_type='once' AND is_sent=0 AND remind_at<=?", (full_time,)).fetchall()
    weekly = conn.execute(f"""SELECT {columns} FROM reminders WHERE remind_type='weekly' AND day_of_week=?
        AND remind_time=? AND COALESCE(last_fired,'')!=?""", (weekday,time,date)).fetchall()
    placeholders = ','.join('?' for _ in month_days)
    monthly = conn.execute(f"""SELECT {columns} FROM reminders WHERE remind_type='monthly'
        AND day_of_month IN ({placeholders}) AND remind_time=? AND COALESCE(last_fired,'')!=?""",
        (*month_days,time,date)).fetchall()
    return [*once,*weekly,*monthly]


def mark_delivered(conn, reminder_id, kind, date):
    if kind == "once":
        return conn.execute("UPDATE reminders SET is_sent=1 WHERE id=? AND remind_type='once' AND is_sent=0", (reminder_id,)).rowcount
    return conn.execute("UPDATE reminders SET last_fired=? WHERE id=? AND remind_type=? AND COALESCE(last_fired,'')!=?", (date,reminder_id,kind,date)).rowcount
