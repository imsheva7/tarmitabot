"""Read approved absences for the existing daily report."""


def approved_absences(conn):
    return conn.execute("SELECT user_name, request_type, col1, col2, start_date, end_date FROM requests WHERE status LIKE '%تأیید شده%' AND request_type IN ('مرخصی', 'ماموریت')").fetchall()
