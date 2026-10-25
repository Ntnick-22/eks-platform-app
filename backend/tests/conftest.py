import os

import pytest

# app.py reads these at IMPORT time (and runs init_db()), so they must be set before "import app".
# setdefault: the defaults match the local throwaway container; CI can override them.
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_PORT", "5433")
os.environ.setdefault("POSTGRES_DB", "test")
os.environ.setdefault("POSTGRES_USER", "test")
os.environ.setdefault("POSTGRES_PASSWORD", "test")

import app as backend


@pytest.fixture
def client():
    # Every test starts with an empty table, so tests can't depend on each other's data
    with backend.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE users RESTART IDENTITY;")
        conn.commit()
    return backend.app.test_client()
