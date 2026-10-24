import pytest

import app as backend


def register(client, name="Ada", email="ada@example.com", role="Engineer"):
    return client.post("/api/register", json={"name": name, "email": email, "role": role})


def test_health_reports_database_connected(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.get_json()["database"] == "connected"


def test_health_does_not_expose_db_host(client):
    # /api/health is public: it reports whether the database is reachable, never where it is
    r = client.get("/api/health")
    assert "db_host" not in r.get_json()


def test_ready(client):
    assert client.get("/api/ready").status_code == 200


def test_register_creates_user(client):
    r = register(client)
    assert r.status_code == 201
    user = r.get_json()["user"]
    assert user["email"] == "ada@example.com"
    assert user["role"] == "Engineer"


def test_register_normalises_email(client):
    r = register(client, email="  ADA@Example.COM ")
    assert r.get_json()["user"]["email"] == "ada@example.com"


def test_register_requires_name_and_email(client):
    r = client.post("/api/register", json={"name": "Ada"})
    assert r.status_code == 400


def test_register_duplicate_email_is_409(client):
    register(client)
    r = register(client, name="Someone else")
    assert r.status_code == 409


def test_register_database_error_does_not_leak_details(client):
    # Longer than VARCHAR(100): Postgres rejects the INSERT. The client gets a generic error;
    # the real one (SQL, column types) belongs in the logs, not in the response
    r = register(client, name="x" * 101)
    assert r.status_code == 500
    assert r.get_json() == {"error": "Registration failed"}


def test_no_cors_headers_for_other_origins(client):
    # The frontend calls relative /api paths (same origin), so CORS is never needed. A foreign
    # origin must not be allowed to read API responses from a visitor's browser
    r = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "Access-Control-Allow-Origin" not in r.headers


def test_list_users(client):
    register(client)
    register(client, name="Bob", email="bob@example.com")
    users = client.get("/api/users").get_json()["users"]
    assert {u["email"] for u in users} == {"ada@example.com", "bob@example.com"}


def test_stats(client):
    # Drill E (2026-10-07) broke this endpoint with a column typo; only a real database catches that
    register(client, role="Engineer")
    register(client, name="Bob", email="bob@example.com", role="Student")
    register(client, name="Cy", email="cy@example.com", role="Student")
    r = client.get("/api/stats")
    assert r.status_code == 200
    assert r.get_json() == {"total_users": 3, "today_users": 3, "total_roles": 2}


def test_delete_user(client):
    user_id = register(client).get_json()["user"]["id"]
    assert client.delete(f"/api/users/{user_id}").status_code == 200
    assert client.delete(f"/api/users/{user_id}").status_code == 404


# ── Database down: the Kubernetes probes rely on exactly this behaviour ──
# liveness (/api/health) must stay 200, or a DB outage would restart every pod;
# readiness (/api/ready) must fail, so the Service stops sending traffic to the pod.


@pytest.fixture
def db_down(client, monkeypatch):
    # Nothing listens on port 1: every new connection is refused at once (OperationalError)
    monkeypatch.setitem(backend.DB_CONFIG, "port", "1")
    return client


def test_health_stays_up_when_database_is_down(db_down):
    r = db_down.get("/api/health")
    assert r.status_code == 200
    assert r.get_json()["database"] == "disconnected"


def test_ready_fails_when_database_is_down(db_down):
    r = db_down.get("/api/ready")
    assert r.status_code == 503
    assert r.get_json() == {"error": "Database unavailable"}
