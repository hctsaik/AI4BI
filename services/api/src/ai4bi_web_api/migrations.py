"""SQLite upgrades: schema changes and their version marker commit together."""
CURRENT_SCHEMA = 2


def migrate(db):
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version >= CURRENT_SCHEMA:
        return
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("""CREATE TABLE publications(
            id TEXT PRIMARY KEY REFERENCES jobs(id),
            rid TEXT NOT NULL REFERENCES reports(id),
            wid TEXT NOT NULL REFERENCES workspaces(id),
            published_revision INTEGER NOT NULL,
            source_revision INTEGER NOT NULL,
            snapshot TEXT NOT NULL, checks TEXT NOT NULL, created TEXT NOT NULL,
            UNIQUE(rid,published_revision))""")
        db.execute("""CREATE TRIGGER publications_no_update BEFORE UPDATE ON publications
            BEGIN SELECT RAISE(ABORT, 'Published revisions are immutable'); END""")
        db.execute("""CREATE TRIGGER publications_no_delete BEFORE DELETE ON publications
            BEGIN SELECT RAISE(ABORT, 'Published revisions are immutable'); END""")
        db.execute("PRAGMA user_version=2")
        db.commit()
    except Exception:
        db.rollback()
        raise
