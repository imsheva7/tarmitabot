"""Audit insertion participates in the caller's transaction."""


def record(conn, actor, action, entity, entity_id, details=""):
    conn.execute(
        "INSERT INTO audit_logs(actor_staff_id,action_code,entity_type,entity_id,details) VALUES(?,?,?,?,?)",
        (actor, action, entity, str(entity_id), details),
    )
