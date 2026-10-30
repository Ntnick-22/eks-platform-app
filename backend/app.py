import os
import random
import time

import psycopg2
from flask import Flask, g, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from psycopg2.extras import RealDictCursor

app = Flask(__name__)

# Prometheus metrics, scraped from /metrics (ServiceMonitor in the gitops chart). Labelled by the
# route template (/api/users), never the raw URL: one series per endpoint, not per request path.
# One gunicorn worker, so the default in-process registry is enough. With "-w N" every worker
# would count on its own: that needs prometheus_client's multiprocess mode.
REQUESTS = Counter("http_requests_total", "HTTP requests", ["method", "endpoint", "status"])
LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request duration", ["method", "endpoint"]
)


@app.before_request
def start_timer():
    g.start = time.perf_counter()


# Fault injection for release drills: a canary analysis must catch a bad version, so a version
# can be made bad on purpose. A share of API requests fails with 500 and/or answers slowly.
# Off unless set. Probes and /metrics are never affected, like a real bug that passes the
# health checks: Kubernetes keeps the pod, only the canary analysis can stop the release.
def read_fault_config(env):
    error_rate = float(env.get("FAULT_ERROR_RATE", "0"))
    latency_seconds = float(env.get("FAULT_LATENCY_SECONDS", "0"))
    if not 0 <= error_rate <= 1 or latency_seconds < 0:
        raise ValueError("FAULT_ERROR_RATE must be 0..1 and FAULT_LATENCY_SECONDS >= 0")
    return error_rate, latency_seconds


FAULT_ERROR_RATE, FAULT_LATENCY_SECONDS = read_fault_config(os.environ)
FAULT_EXEMPT_PATHS = {"/api/health", "/api/ready", "/metrics"}


@app.before_request
def inject_faults():
    if request.path in FAULT_EXEMPT_PATHS:
        return None
    if FAULT_LATENCY_SECONDS:
        time.sleep(FAULT_LATENCY_SECONDS)
    if FAULT_ERROR_RATE and random.random() < FAULT_ERROR_RATE:
        return jsonify({"error": "Injected fault"}), 500
    return None


@app.after_request
def record_request(response):
    # Also runs for error responses (404, the 503 handler below, unhandled 500s)
    endpoint = request.url_rule.rule if request.url_rule else "unmatched"
    if endpoint != "/metrics":  # Prometheus' own scrapes would drown the real traffic
        LATENCY.labels(request.method, endpoint).observe(time.perf_counter() - g.start)
        REQUESTS.labels(request.method, endpoint, str(response.status_code)).inc()
    return response


# Not public: the Ingress only routes /api/* to the backend
@app.get("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


# Required config has NO defaults: a missing or misspelled variable crashes the app at startup,
# so the new pod never becomes ready and the rollout stops while the old pods keep serving
# (ECS drill D, 2026-10-06: a silent default "myecs-db" made a typo look healthy and broke
# every DB request instead).
DB_CONFIG = {
    "host": os.environ["DB_HOST"],
    "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.environ["POSTGRES_DB"],
    "user": os.environ["POSTGRES_USER"],
    "password": os.environ["POSTGRES_PASSWORD"],
}


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def init_db():
    # Retry only "can't reach the database yet" (RDS or the compose db still starting). Anything
    # else, or still unreachable after ~60 s, is raised: the task crashes at startup and the circuit
    # breaker rolls the deploy back, instead of running with no users table.
    for attempt in range(30):
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS users (
                            id SERIAL PRIMARY KEY,
                            name VARCHAR(100) NOT NULL,
                            email VARCHAR(150) NOT NULL UNIQUE,
                            role VARCHAR(80) DEFAULT 'Student',
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        );
                    """)
                conn.commit()
            return
        except psycopg2.OperationalError:
            if attempt == 29:
                raise
            time.sleep(2)


init_db()


@app.errorhandler(psycopg2.OperationalError)
def database_unavailable(error):
    app.logger.error("Database unavailable: %s", error)
    return jsonify({"error": "Database unavailable"}), 503


@app.get("/api/ready")
def ready():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT 1;")

    return jsonify({"status": "ready"})


@app.get("/api/health")
def health():
    try:
        with get_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1;")
        db_status = "connected"
    except psycopg2.Error:  # database problems only; a bug in this function should still surface
        db_status = "disconnected"

    return jsonify(
        {
            "status": "ok",
            "service": "backend",
            "port": 8000,
            "database": db_status,
        }
    )


@app.get("/api/users")
def list_users():
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT id, name, email, role, created_at FROM users ORDER BY created_at DESC;")
        users = cur.fetchall()

    return jsonify({"users": users})


@app.get("/api/stats")
def stats():
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM users;")
        total_users = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM users WHERE created_at::date = CURRENT_DATE;")
        today_users = cur.fetchone()[0]

        cur.execute("SELECT COUNT(DISTINCT role) FROM users;")
        total_roles = cur.fetchone()[0]

    return jsonify(
        {"total_users": total_users, "today_users": today_users, "total_roles": total_roles}
    )


@app.post("/api/register")
def register():
    data = request.get_json(silent=True) or {}

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    role = (data.get("role") or "Student").strip()

    if not name or not email:
        return jsonify({"error": "Name and email are required"}), 400

    try:
        with get_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(
                    """
                    INSERT INTO users (name, email, role)
                    VALUES (%s, %s, %s)
                    RETURNING id, name, email, role, created_at;
                    """,
                    (name, email, role),
                )
                user = cur.fetchone()
            conn.commit()

        return jsonify({"message": "Registration successful", "user": user}), 201

    except psycopg2.errors.UniqueViolation:
        return jsonify({"error": "This email is already registered"}), 409
    except psycopg2.OperationalError:
        raise  # database down: the errorhandler above answers 503, like every other endpoint
    except psycopg2.Error:
        # The details (SQL, column types) go to the logs (CloudWatch), never to the client
        app.logger.exception("Registration failed")
        return jsonify({"error": "Registration failed"}), 500


@app.delete("/api/users/<int:user_id>")
def delete_user(user_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = %s RETURNING id;", (user_id,))
            deleted = cur.fetchone()
        conn.commit()

    if not deleted:
        return jsonify({"error": "User not found"}), 404

    return jsonify({"message": "User deleted successfully"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
