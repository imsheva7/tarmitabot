"""Company holiday persistence."""


def recent(conn):
    return conn.execute('SELECT h_date,description FROM holidays ORDER BY h_date DESC LIMIT 10').fetchall()


def save(conn, date, description):
    conn.execute('INSERT OR REPLACE INTO holidays(h_date,description) VALUES(?,?)',(date,description))


def delete(conn, date):
    return conn.execute('DELETE FROM holidays WHERE h_date=?',(date,)).rowcount
