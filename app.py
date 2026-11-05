import hashlib
import hmac
import io
import os
import re
import secrets
import smtplib
import ssl
import statistics
import uuid
from datetime import date, datetime, time, timedelta
from email.message import EmailMessage
from functools import wraps
from pathlib import Path
from urllib.parse import urlsplit

import click
import psycopg
from psycopg.conninfo import conninfo_to_dict
from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from PIL import Image, ImageOps, UnidentifiedImageError
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename


ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", ROOT / "uploads")).expanduser().resolve()
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
IMAGE_FORMATS = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
AUTH_RATE_LIMIT = 10
ROLES = {
    "student": "Student",
    "lecturer": "Lecturer",
    "maintenance": "Maintenance",
    "admin": "Administrator",
}
STATUSES = ("Submitted", "Assigned", "In progress", "Resolved")
SLA_URGENCIES = ("Urgent", "High", "Normal", "Low")
CATEGORIES = (
    "Electrical",
    "Furniture",
    "Cleaning",
    "Plumbing",
    "Classroom equipment",
    "Hostel",
    "Other",
)

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    MAX_CONTENT_LENGTH=MAX_UPLOAD_BYTES,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("APP_ENV") == "production",
)

APP_ENV = os.environ.get("APP_ENV", "development")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
try:
    TRUSTED_PROXY_HOPS = int(os.environ.get("TRUSTED_PROXY_HOPS", "0"))
except ValueError as exc:
    raise RuntimeError("TRUSTED_PROXY_HOPS must be a non-negative whole number.") from exc
if TRUSTED_PROXY_HOPS < 0:
    raise RuntimeError("TRUSTED_PROXY_HOPS must be a non-negative whole number.")
if TRUSTED_PROXY_HOPS:
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=TRUSTED_PROXY_HOPS,
        x_proto=TRUSTED_PROXY_HOPS,
    )

OIDC_ISSUER = os.environ.get("OIDC_ISSUER", "").rstrip("/")
OIDC_CLIENT_ID = os.environ.get("OIDC_CLIENT_ID", "")
OIDC_CLIENT_SECRET = os.environ.get("OIDC_CLIENT_SECRET", "")
OIDC_METADATA_URL = os.environ.get("OIDC_METADATA_URL", "")
OIDC_REDIRECT_URI = os.environ.get("OIDC_REDIRECT_URI", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
DATABASE_OPTIONS = conninfo_to_dict(DATABASE_URL) if DATABASE_URL else {}
OIDC_CONFIG = (OIDC_ISSUER, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET)
if any(OIDC_CONFIG) and not all(OIDC_CONFIG):
    raise RuntimeError("Set OIDC_ISSUER, OIDC_CLIENT_ID, and OIDC_CLIENT_SECRET together.")
OIDC_ENABLED = all(OIDC_CONFIG)
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "")
SMTP_SECURITY = os.environ.get("SMTP_SECURITY", "starttls").lower()
try:
    SMTP_PORT = int(
        os.environ.get(
            "SMTP_PORT", "465" if SMTP_SECURITY == "ssl" else "587"
        )
    )
except ValueError as exc:
    raise RuntimeError("SMTP_PORT must be a valid port number.") from exc
if not 1 <= SMTP_PORT <= 65535:
    raise RuntimeError("SMTP_PORT must be between 1 and 65535.")
if SMTP_SECURITY not in ("starttls", "ssl"):
    raise RuntimeError("SMTP_SECURITY must be either 'starttls' or 'ssl'.")
SMTP_CONFIG = (SMTP_HOST, SMTP_FROM)
if any(SMTP_CONFIG) and not all(SMTP_CONFIG):
    raise RuntimeError("Set SMTP_HOST and SMTP_FROM together.")
if bool(SMTP_USERNAME) != bool(SMTP_PASSWORD):
    raise RuntimeError("Set SMTP_USERNAME and SMTP_PASSWORD together.")
SMTP_ENABLED = bool(SMTP_HOST and SMTP_FROM)
PHOTO_RETENTION_DAYS = os.environ.get("PHOTO_RETENTION_DAYS", "")
if PHOTO_RETENTION_DAYS:
    try:
        PHOTO_RETENTION_DAYS = int(PHOTO_RETENTION_DAYS)
    except ValueError as exc:
        raise RuntimeError("PHOTO_RETENTION_DAYS must be a positive whole number.") from exc
    if PHOTO_RETENTION_DAYS < 1:
        raise RuntimeError("PHOTO_RETENTION_DAYS must be a positive whole number.")
else:
    PHOTO_RETENTION_DAYS = None


def _first_name(name):
    parts = (name or "").split()
    if not parts:
        return ""
    return parts[1] if len(parts) > 1 and parts[0].endswith(".") else parts[0]


if APP_ENV == "production":
    missing_production = []
    if not os.environ.get("SECRET_KEY"):
        missing_production.append("SECRET_KEY")
    if OIDC_ENABLED and not OIDC_REDIRECT_URI:
        missing_production.append("OIDC_REDIRECT_URI")
    if not OIDC_ENABLED and (not SMTP_ENABLED or not SMTP_USERNAME):
        missing_production.append(
            "SMTP_HOST, SMTP_FROM, SMTP_USERNAME, and SMTP_PASSWORD for email sign-in"
        )
    if not DATABASE_URL:
        missing_production.append("DATABASE_URL")
    elif DATABASE_OPTIONS.get("sslmode") != "verify-full":
        missing_production.append("DATABASE_URL with sslmode=verify-full")
    if not PUBLIC_BASE_URL:
        missing_production.append("PUBLIC_BASE_URL")
    if PHOTO_RETENTION_DAYS is None:
        missing_production.append("PHOTO_RETENTION_DAYS")
    if missing_production:
        raise RuntimeError(
            "Production configuration is incomplete: " + "; ".join(missing_production)
        )
    public_url = urlsplit(PUBLIC_BASE_URL)
    if (
        (OIDC_ENABLED and (
            not OIDC_ISSUER.startswith("https://")
            or not OIDC_REDIRECT_URI.startswith("https://")
        ))
        or public_url.scheme != "https"
        or not public_url.netloc
        or public_url.path not in ("", "/")
        or public_url.query
        or public_url.fragment
        or public_url.username
        or public_url.password
    ):
        raise RuntimeError("Production public, OIDC issuer, and callback URLs must use HTTPS.")
    app.config["TRUSTED_HOSTS"] = [public_url.netloc]

DEMO_MODE = not DATABASE_URL
if APP_ENV == "production" and DEMO_MODE:
    raise RuntimeError("Production mode requires DATABASE_URL.")
DB_POOL = (
    ConnectionPool(
        conninfo=DATABASE_URL,
        min_size=1,
        max_size=5,
        kwargs={"row_factory": dict_row},
    )
    if DATABASE_URL
    else None
)
if OIDC_ENABLED:
    from authlib.integrations.flask_client import OAuth

    oauth = OAuth(app)
    university_sso = oauth.register(
        name="university",
        server_metadata_url=OIDC_METADATA_URL
        or f"{OIDC_ISSUER}/.well-known/openid-configuration",
        client_id=OIDC_CLIENT_ID,
        client_secret=OIDC_CLIENT_SECRET,
        client_kwargs={"scope": "openid email profile"},
    )
else:
    university_sso = None

DEMO_USERS = {
    "student": {"id": 1, "name": "Amara Okafor", "role": "student"},
    "lecturer": {"id": 2, "name": "Dr. Samuel Mensah", "role": "lecturer"},
    "maintenance": {"id": 3, "name": "Kofi Boateng", "role": "maintenance"},
    "admin": {"id": 4, "name": "Facilities Office", "role": "admin"},
}
DEMO_LOCATIONS = [
    {"id": 1, "building": "Block C", "room": "Room 204", "active": True},
    {"id": 2, "building": "Business School", "room": "Lecture Hall 1", "active": True},
    {"id": 3, "building": "Hostel B", "room": "Ground floor", "active": True},
    {"id": 4, "building": "Main Library", "room": "Study room 3", "active": True},
]
DEMO_NEXT_LOCATION_ID = 5
DEMO_WORK_LOGS = [
    {
        "id": 1,
        "report_id": 1042,
        "actor_name": "Kofi Boateng",
        "labor_minutes": 35,
        "parts_used": "None",
        "note": "Inspected the projector power connection and secured the loose cable.",
        "follow_up_at": None,
        "created_at": datetime(2026, 11, 4, 8, 10),
    }
]
DEMO_REPORTS = [
    {
        "id": 1042,
        "reference_code": "UPS-26-1042",
        "reporter_id": 1,
        "reporter_name": "Amara Okafor",
        "title": "Projector flickers during lectures",
        "category": "Classroom equipment",
        "location": "Block C · Room 204",
        "urgency": "High",
        "description": "The projector turns off every few minutes during class.",
        "photo_name": None,
        "is_anonymous": False,
        "status": "In progress",
        "assigned_to": 3,
        "assignee_name": "Kofi Boateng",
        "created_at": datetime(2026, 11, 3, 9, 20),
        "updated_at": datetime(2026, 11, 4, 8, 10),
        "updates": [
            {"status": "Submitted", "note": "Report received.", "created_at": datetime(2026, 11, 3, 9, 20)},
            {"status": "Assigned", "note": "Assigned to Kofi Boateng.", "created_at": datetime(2026, 11, 3, 14, 5)},
            {"status": "In progress", "note": "Technician is checking the power connection.", "created_at": datetime(2026, 11, 4, 8, 10)},
        ],
        "feedback": None,
    },
    {
        "id": 1041,
        "reference_code": "UPS-26-1041",
        "reporter_id": 2,
        "reporter_name": "Dr. Samuel Mensah",
        "title": "Loose desk row needs repair",
        "category": "Furniture",
        "location": "Business School · Lecture Hall 1",
        "urgency": "Normal",
        "description": "Two desks near the front row are loose and wobble.",
        "photo_name": None,
        "is_anonymous": False,
        "status": "Assigned",
        "assigned_to": 3,
        "assignee_name": "Kofi Boateng",
        "created_at": datetime(2026, 11, 2, 11, 35),
        "updated_at": datetime(2026, 11, 3, 10, 0),
        "updates": [
            {"status": "Submitted", "note": "Report received.", "created_at": datetime(2026, 11, 2, 11, 35)},
            {"status": "Assigned", "note": "Assigned to Kofi Boateng.", "created_at": datetime(2026, 11, 3, 10, 0)},
        ],
        "feedback": None,
    },
    {
        "id": 1040,
        "reference_code": "UPS-26-1040",
        "reporter_id": 1,
        "reporter_name": "Amara Okafor",
        "title": "Water tap leaking by the east wing",
        "category": "Plumbing",
        "location": "Hostel B · Ground floor",
        "urgency": "Urgent",
        "description": "The tap is leaking continuously and the floor is getting wet.",
        "photo_name": None,
        "is_anonymous": True,
        "status": "Submitted",
        "assigned_to": None,
        "assignee_name": None,
        "created_at": datetime(2026, 11, 4, 7, 45),
        "updated_at": datetime(2026, 11, 4, 7, 45),
        "updates": [
            {"status": "Submitted", "note": "Report received.", "created_at": datetime(2026, 11, 4, 7, 45)}
        ],
        "feedback": None,
    },
    {
        "id": 1039,
        "reference_code": "UPS-26-1039",
        "reporter_id": 1,
        "reporter_name": "Amara Okafor",
        "title": "Library study-room light replaced",
        "category": "Electrical",
        "location": "Main Library · Study room 3",
        "urgency": "Low",
        "description": "The ceiling light above the shared desk had stopped working.",
        "photo_name": None,
        "is_anonymous": False,
        "status": "Resolved",
        "assigned_to": 3,
        "assignee_name": "Kofi Boateng",
        "created_at": datetime(2026, 10, 29, 13, 10),
        "updated_at": datetime(2026, 10, 30, 15, 40),
        "updates": [
            {"status": "Submitted", "note": "Report received.", "created_at": datetime(2026, 10, 29, 13, 10)},
            {"status": "Assigned", "note": "Assigned to Kofi Boateng.", "created_at": datetime(2026, 10, 29, 16, 20)},
            {"status": "Resolved", "note": "Light replaced and checked.", "created_at": datetime(2026, 10, 30, 15, 40)},
        ],
        "feedback": None,
    },
]
DEMO_NEXT_ID = 1043
DEMO_SETTINGS = {
    "public_board_enabled": True,
    "anonymous_reports_enabled": True,
    **{f"sla_hours_{urgency.lower()}": "" for urgency in SLA_URGENCIES},
}


def _db():
    if DB_POOL is None:
        return None
    if "db" not in g:
        g.db = DB_POOL.getconn()
    return g.db


@app.teardown_appcontext
def close_db(_error=None):
    connection = g.pop("db", None)
    if connection is not None:
        DB_POOL.putconn(connection)


@app.after_request
def set_security_headers(response):
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'; "
        "object-src 'none'; "
        "img-src 'self'; "
        "font-src 'self' https://fonts.gstatic.com; "
        "style-src 'self' https://fonts.googleapis.com; "
        "script-src 'self'; "
        "connect-src 'self'",
    )
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Cache-Control", "no-store")
    if APP_ENV == "production" and request.is_secure:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000"
        )
    return response


def _query(sql, params=(), one=False):
    connection = _db()
    if connection is None:
        return None
    cursor = connection.cursor()
    try:
        cursor.execute(sql, params)
        result = cursor.fetchone() if one else cursor.fetchall()
        return result
    finally:
        cursor.close()


def _execute(sql, params=()):
    connection = _db()
    if connection is None:
        return None
    cursor = connection.cursor()
    try:
        cursor.execute(sql, params)
        connection.commit()
        if cursor.description:
            row = cursor.fetchone()
            return next(iter(row.values())) if row is not None else None
        return None
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()


def _current_user():
    if DEMO_MODE:
        role = session.get("demo_role", "student")
        return DEMO_USERS.get(role, DEMO_USERS["student"])
    user_id = session.get("user_id")
    if not user_id:
        return None
    user = _query(
        "SELECT id, name, email, role, session_version FROM users WHERE id = %s",
        (user_id,),
        one=True,
    )
    if user and session.get("auth_version") != user["session_version"]:
        session.clear()
        return None
    return user


def _auth_rate_key(scope):
    remote_addr = request.remote_addr or "unknown"
    payload = f"{scope}:{remote_addr}".encode("utf-8")
    return hmac.new(
        app.config["SECRET_KEY"].encode("utf-8"), payload, hashlib.sha256
    ).hexdigest()


def _auth_attempt_allowed(scope):
    bucket = _auth_rate_key(scope)
    _execute(
        """
        INSERT INTO auth_attempts (bucket_hash, window_started_at, attempts)
        VALUES (%s, CURRENT_TIMESTAMP, 1)
        ON CONFLICT (bucket_hash) DO UPDATE SET
            attempts = CASE
                WHEN auth_attempts.window_started_at < CURRENT_TIMESTAMP - INTERVAL '15 minutes'
                THEN 1
                ELSE LEAST(auth_attempts.attempts + 1, 11)
            END,
            window_started_at = CASE
                WHEN auth_attempts.window_started_at < CURRENT_TIMESTAMP - INTERVAL '15 minutes'
                THEN CURRENT_TIMESTAMP
                ELSE auth_attempts.window_started_at
            END
        """,
        (bucket,),
    )
    row = _query(
        "SELECT attempts FROM auth_attempts WHERE bucket_hash = %s",
        (bucket,),
        one=True,
    )
    return row is not None and row["attempts"] <= AUTH_RATE_LIMIT


def _issue_auth_token(user_id, purpose):
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    saved_user_id = _execute(
        """
        INSERT INTO auth_tokens (token_hash, user_id, purpose, expires_at)
        VALUES (%s, %s, %s, CURRENT_TIMESTAMP + INTERVAL '30 minutes')
        ON CONFLICT (user_id, purpose) DO UPDATE
        SET token_hash = EXCLUDED.token_hash,
            expires_at = EXCLUDED.expires_at,
            created_at = CURRENT_TIMESTAMP
        RETURNING user_id
        """,
        (token_hash, user_id, purpose),
    )
    if saved_user_id is None:
        raise RuntimeError("Could not save the requested authentication token.")
    return token


def _send_auth_email(recipient, subject, body):
    if not SMTP_ENABLED:
        raise RuntimeError("SMTP email delivery is not configured.")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = SMTP_FROM
    message["To"] = recipient
    message.set_content(body)
    context = ssl.create_default_context()
    if SMTP_SECURITY == "ssl":
        with smtplib.SMTP_SSL(
            SMTP_HOST, SMTP_PORT, timeout=15, context=context
        ) as server:
            if SMTP_USERNAME:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(message)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            if SMTP_USERNAME:
                server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(message)


def _auth_link(endpoint, token):
    base_url = PUBLIC_BASE_URL or request.url_root.rstrip("/")
    return f"{base_url}{url_for(endpoint, token=token)}"


def _send_verification_email(user_id, email):
    token = _issue_auth_token(user_id, "verify_email")
    link = _auth_link("verify_email", token)
    _send_auth_email(
        email,
        "Verify your Campus Care email",
        "Confirm your email address by opening this link within 30 minutes:\n\n"
        f"{link}\n\nIf you did not request this, you can ignore this message.",
    )


def _send_password_reset_email(user_id, email):
    token = _issue_auth_token(user_id, "password_reset")
    link = _auth_link("reset_password", token)
    _send_auth_email(
        email,
        "Reset your Campus Care password",
        "Set a new password by opening this link within 30 minutes:\n\n"
        f"{link}\n\nIf you did not request this, you can ignore this message.",
    )


def _valid_email(email):
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email))


@app.before_request
def load_user_and_check_csrf():
    if APP_ENV == "production" and not request.is_secure:
        return redirect(f"{PUBLIC_BASE_URL}{request.full_path}", code=308)
    g.user = _current_user()
    if request.method == "POST":
        supplied = request.form.get("csrf_token", "")
        expected = session.get("csrf_token", "")
        if not expected or not secrets.compare_digest(supplied, expected):
            abort(400, description="Your form expired. Reload the page and try again.")


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


app.jinja_env.globals["csrf_token"] = csrf_token
app.jinja_env.globals["now"] = datetime.now
app.jinja_env.globals["roles"] = ROLES
app.jinja_env.globals["demo_mode"] = DEMO_MODE
app.jinja_env.filters["first_name"] = _first_name


def _settings():
    if DEMO_MODE:
        return dict(DEMO_SETTINGS)
    keys = ("public_board_enabled", "anonymous_reports_enabled") + tuple(
        f"sla_hours_{urgency.lower()}" for urgency in SLA_URGENCIES
    )
    placeholders = ", ".join(["%s"] * len(keys))
    rows = _query(
        f"SELECT setting_key, setting_value FROM app_settings WHERE setting_key IN ({placeholders})",
        keys,
    )
    saved = {row["setting_key"]: row["setting_value"] for row in rows}
    settings = {
        "public_board_enabled": saved.get("public_board_enabled", "true") == "true",
        "anonymous_reports_enabled": saved.get("anonymous_reports_enabled", "true") == "true",
    }
    settings.update(
        {
            f"sla_hours_{urgency.lower()}": saved.get(
                f"sla_hours_{urgency.lower()}", ""
            )
            for urgency in SLA_URGENCIES
        }
    )
    return settings


def _list_locations(*, active_only=True):
    if DEMO_MODE:
        locations = DEMO_LOCATIONS
        if active_only:
            locations = [location for location in locations if location["active"]]
        return sorted(locations, key=lambda row: (row["building"].casefold(), row["room"].casefold()))
    where = "WHERE is_active = TRUE" if active_only else ""
    return _query(
        f"""
        SELECT id, building, room, is_active AS active
        FROM campus_locations {where}
        ORDER BY building, room
        """
    )


def _location_by_id(location_id, *, active_only=True):
    if DEMO_MODE:
        return next(
            (
                location
                for location in DEMO_LOCATIONS
                if location["id"] == location_id
                and (location["active"] or not active_only)
            ),
            None,
        )
    active_filter = "AND is_active = TRUE" if active_only else ""
    return _query(
        f"""
        SELECT id, building, room, is_active AS active
        FROM campus_locations WHERE id = %s {active_filter}
        """,
        (location_id,),
        one=True,
    )


def _work_logs(report_id):
    if DEMO_MODE:
        return sorted(
            [entry for entry in DEMO_WORK_LOGS if entry["report_id"] == report_id],
            key=lambda row: row["created_at"],
            reverse=True,
        )
    return _query(
        """
        SELECT w.id, w.report_id, w.labor_minutes, w.parts_used, w.note,
               w.follow_up_at, w.created_at, u.name AS actor_name
        FROM maintenance_work_logs w
        JOIN users u ON u.id = w.actor_id
        WHERE w.report_id = %s
        ORDER BY w.created_at DESC, w.id DESC
        """,
        (report_id,),
    )


def _analytics(start_date, end_date):
    start = datetime.combine(start_date, time.min)
    end = datetime.combine(end_date + timedelta(days=1), time.min)
    if DEMO_MODE:
        records = []
        for report in DEMO_REPORTS:
            if not start <= report["created_at"] < end:
                continue
            resolved_at = next(
                (
                    update["created_at"]
                    for update in reversed(report["updates"])
                    if update["status"] == "Resolved"
                ),
                None,
            )
            records.append(
                {
                    "id": report["id"],
                    "reference_code": report["reference_code"],
                    "category": report["category"],
                    "location": report["location"],
                    "urgency": report["urgency"],
                    "status": report["status"],
                    "created_at": report["created_at"],
                    "resolved_at": resolved_at,
                    "rating": (report.get("feedback") or {}).get("rating"),
                }
            )
    else:
        records = _query(
            """
            SELECT r.id, r.reference_code, r.category, r.location, r.urgency, r.status, r.created_at,
                   (SELECT MIN(ru.created_at)
                    FROM report_updates ru
                    WHERE ru.report_id = r.id AND ru.status = 'Resolved') AS resolved_at,
                   (SELECT f.rating FROM feedback f WHERE f.report_id = r.id) AS rating
            FROM reports r
            WHERE r.created_at >= %s AND r.created_at < %s
            ORDER BY r.created_at DESC
            """,
            (start, end),
        )

    durations = [
        (record["resolved_at"] - record["created_at"]).total_seconds() / 3600
        for record in records
        if record["status"] == "Resolved" and record["resolved_at"] is not None
    ]
    ratings = [record["rating"] for record in records if record["rating"] is not None]
    category_counts = {}
    location_counts = {}
    now = datetime.now()
    configured_settings = DEMO_SETTINGS if DEMO_MODE else _settings()
    targets = {
        urgency: int(
            configured_settings.get(f"sla_hours_{urgency.lower()}") or 0
        )
        for urgency in SLA_URGENCIES
    }
    overdue = []
    for record in records:
        category_counts[record["category"]] = category_counts.get(record["category"], 0) + 1
        location_counts[record["location"]] = location_counts.get(record["location"], 0) + 1
        target = targets.get(record["urgency"], 0)
        age_hours = (now - record["created_at"]).total_seconds() / 3600
        if record["status"] != "Resolved" and target and age_hours >= target:
            overdue.append({**record, "age_hours": age_hours, "target_hours": target})

    return {
        "total": len(records),
        "resolved": sum(record["status"] == "Resolved" for record in records),
        "average_resolution_hours": statistics.mean(durations) if durations else None,
        "feedback_average": statistics.mean(ratings) if ratings else None,
        "feedback_count": len(ratings),
        "recurring_categories": [
            {"label": label, "count": count}
            for label, count in sorted(
                category_counts.items(), key=lambda item: (-item[1], item[0])
            )
            if count > 1
        ],
        "recurring_locations": [
            {"label": label, "count": count}
            for label, count in sorted(
                location_counts.items(), key=lambda item: (-item[1], item[0])
            )
            if count > 1
        ],
        "overdue": sorted(overdue, key=lambda row: row["age_hours"], reverse=True),
        "sla_configured": any(targets.values()),
    }


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("login", next=request.full_path))
        return view(*args, **kwargs)

    return wrapped


def roles_required(*allowed):
    def decorate(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if g.user["role"] not in allowed:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorate


def _report_by_id(report_id, *, public=False):
    if DEMO_MODE:
        report = next((r for r in DEMO_REPORTS if r["id"] == report_id), None)
        if report and public:
            return {
                key: report[key]
                for key in (
                    "id",
                    "reference_code",
                    "title",
                    "category",
                    "location",
                    "urgency",
                    "status",
                    "created_at",
                    "updated_at",
                )
            }
        return report
    if public:
        return _query(
            """
            SELECT id, reference_code, title, category, location, urgency, status,
                   created_at, updated_at
            FROM reports WHERE id = %s
            """,
            (report_id,),
            one=True,
        )
    return _query(
        """
        SELECT r.*, u.name AS reporter_name, a.name AS assignee_name
        FROM reports r
        JOIN users u ON u.id = r.reporter_id
        LEFT JOIN users a ON a.id = r.assigned_to
        WHERE r.id = %s
        """,
        (report_id,),
        one=True,
    )


def _updates(report_id):
    if DEMO_MODE:
        report = _report_by_id(report_id)
        return report["updates"] if report else []
    return _query(
        "SELECT status, note, created_at FROM report_updates WHERE report_id = %s ORDER BY created_at",
        (report_id,),
    )


def _list_reports(*, public=False, reporter_id=None, assignee_id=None):
    if DEMO_MODE:
        reports = list(DEMO_REPORTS)
        if reporter_id is not None:
            reports = [r for r in reports if r["reporter_id"] == reporter_id]
        if assignee_id is not None:
            reports = [r for r in reports if r["assigned_to"] == assignee_id]
        if public:
            reports = [
                {
                    key: report[key]
                    for key in (
                        "id",
                        "reference_code",
                        "title",
                        "category",
                        "location",
                        "urgency",
                        "status",
                        "created_at",
                        "updated_at",
                    )
                }
                for report in reports
            ]
        else:
            reports = [
                {
                    **report,
                    "latest_update_note": report["updates"][-1]["note"]
                    if report["updates"]
                    else "",
                }
                for report in reports
            ]
        return sorted(reports, key=lambda report: report["created_at"], reverse=True)

    if public:
        return _query(
            """
            SELECT id, reference_code, title, category, location, urgency, status,
                   created_at, updated_at
            FROM reports ORDER BY created_at DESC
            """
        )

    filters, params = [], []
    if reporter_id is not None:
        filters.append("r.reporter_id = %s")
        params.append(reporter_id)
    if assignee_id is not None:
        filters.append("r.assigned_to = %s")
        params.append(assignee_id)
    where = f" WHERE {' AND '.join(filters)}" if filters else ""
    rows = _query(
        f"""
        SELECT r.*, u.name AS reporter_name, a.name AS assignee_name,
               (SELECT ru.note FROM report_updates ru
                WHERE ru.report_id = r.id
                ORDER BY ru.created_at DESC, ru.id DESC LIMIT 1) AS latest_update_note
        FROM reports r
        JOIN users u ON u.id = r.reporter_id
        LEFT JOIN users a ON a.id = r.assigned_to
        {where}
        ORDER BY r.created_at DESC
        """,
        tuple(params),
    )
    if public:
        return rows
    return rows


def _can_view_report(report):
    if g.user["role"] == "admin":
        return True
    if g.user["role"] == "maintenance":
        return int(report["assigned_to"] or 0) == int(g.user["id"])
    return int(report["reporter_id"]) == int(g.user["id"])


def _status_class(status):
    return {
        "Submitted": "new",
        "Assigned": "assigned",
        "In progress": "progress",
        "Resolved": "resolved",
    }.get(status, "new")


app.jinja_env.globals["status_class"] = _status_class


@app.route("/")
def dashboard():
    view = request.args.get("view", "overview")
    if view == "board":
        if not _settings()["public_board_enabled"] and not g.user:
            return redirect(url_for("login"))
        reports = _list_reports(public=True)
    elif not g.user:
        return redirect(url_for("login"))
    elif g.user["role"] == "maintenance":
        reports = _list_reports(assignee_id=g.user["id"])
    elif g.user["role"] == "admin":
        reports = _list_reports()
    else:
        reports = _list_reports(reporter_id=g.user["id"])
    reports = reports or []
    counts = {
        "open": sum(r["status"] != "Resolved" for r in reports),
        "progress": sum(r["status"] == "In progress" for r in reports),
        "resolved": sum(r["status"] == "Resolved" for r in reports),
    }
    staff = (
        _query("SELECT id, name, role FROM users WHERE role = 'maintenance' ORDER BY name")
        if g.user and g.user["role"] == "admin" and not DEMO_MODE
        else [DEMO_USERS["maintenance"]]
        if g.user and g.user["role"] == "admin"
        else []
    )
    return render_template(
        "dashboard.html",
        view=view,
        reports=reports,
        counts=counts,
        staff=staff,
        statuses=STATUSES,
        categories=CATEGORIES,
        settings=_settings(),
    )


def _render_report_form(settings, selected_location_id=None):
    return render_template(
        "report.html",
        categories=CATEGORIES,
        locations=_list_locations(),
        allow_anonymous=settings["anonymous_reports_enabled"],
        selected_location_id=selected_location_id,
    )


def _normalized_image(photo, extension):
    expected_format = IMAGE_FORMATS.get(extension)
    if expected_format is None:
        return None
    try:
        with Image.open(photo) as image:
            if (
                image.format != expected_format
                or image.width < 1
                or image.height < 1
                or image.width * image.height > MAX_IMAGE_PIXELS
            ):
                return None
            image.verify()
        photo.seek(0)
        with Image.open(photo) as image:
            image.load()
            normalized = ImageOps.exif_transpose(image)
            if expected_format == "JPEG" and normalized.mode not in ("RGB", "L"):
                normalized = normalized.convert("RGB")
            output = io.BytesIO()
            save_options = {"optimize": True}
            if expected_format == "JPEG":
                save_options["quality"] = 90
            elif expected_format == "WEBP":
                save_options["method"] = 6
            normalized.save(output, format=expected_format, **save_options)
            if output.tell() > MAX_UPLOAD_BYTES:
                return None
            return output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return None


@app.route("/report", methods=["GET", "POST"])
@roles_required("student", "lecturer")
def create_report():
    settings = _settings()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        location_id = request.form.get("location_id", type=int)
        location_record = _location_by_id(location_id) if location_id else None
        location = (
            f"{location_record['building']} · {location_record['room']}"
            if location_record
            else ""
        )
        category = request.form.get("category", "")
        urgency = request.form.get("urgency", "Normal")
        description = request.form.get("description", "").strip()
        anonymous = (
            settings["anonymous_reports_enabled"]
            and request.form.get("anonymous") == "on"
        )
        photo = request.files.get("photo")
        if not title or len(title) > 160 or not location or len(location) > 190:
            flash("Add a short title and a specific campus location.", "error")
        elif category not in CATEGORIES or urgency not in ("Low", "Normal", "High", "Urgent"):
            flash("Choose a valid issue category and urgency.", "error")
        elif len(description) < 10 or len(description) > 3000:
            flash("Describe the issue in at least 10 characters (up to 3,000).", "error")
        else:
            photo_name = None
            if photo and photo.filename:
                safe_name = secure_filename(photo.filename)
                extension = Path(safe_name).suffix.lower().lstrip(".")
                image_data = _normalized_image(photo.stream, extension)
                if extension not in ALLOWED_EXTENSIONS or image_data is None:
                    flash("Upload a valid JPG, PNG, or WebP image.", "error")
                    return render_template(
                        "report.html",
                        categories=CATEGORIES,
                        locations=_list_locations(),
                        allow_anonymous=settings["anonymous_reports_enabled"],
                        selected_location_id=location_id,
                    )
                UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
                photo_name = f"{uuid.uuid4().hex}.{extension}"
                (UPLOAD_DIR / photo_name).write_bytes(image_data)

            if DEMO_MODE:
                global DEMO_NEXT_ID
                report_id = DEMO_NEXT_ID
                DEMO_NEXT_ID += 1
                now = datetime.now()
                report = {
                    "id": report_id,
                    "reference_code": f"UPS-26-{report_id}",
                    "reporter_id": g.user["id"],
                    "reporter_name": g.user["name"],
                    "title": title,
                    "category": category,
                    "location": location,
                    "location_id": location_id,
                    "urgency": urgency,
                    "description": description,
                    "photo_name": photo_name,
                    "is_anonymous": anonymous,
                    "status": "Submitted",
                    "assigned_to": None,
                    "assignee_name": None,
                    "created_at": now,
                    "updated_at": now,
                    "updates": [
                        {"status": "Submitted", "note": "Report received.", "created_at": now}
                    ],
                    "feedback": None,
                }
                DEMO_REPORTS.append(report)
            else:
                report_id = _execute(
                    """
                    INSERT INTO reports
                    (reference_code, reporter_id, title, category, location, location_id, urgency,
                     description, photo_name, is_anonymous)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        f"UPS-{datetime.now():%y}-{secrets.token_hex(3).upper()}",
                        g.user["id"],
                        title,
                        category,
                        location,
                        location_id,
                        urgency,
                        description,
                        photo_name,
                        anonymous,
                    ),
                )
                _execute(
                    "INSERT INTO report_updates (report_id, actor_id, status, note) VALUES (%s, %s, %s, %s)",
                    (report_id, g.user["id"], "Submitted", "Report received."),
                )
            flash("Your report is in. You can follow each update from My reports.", "success")
            return redirect(url_for("report_detail", report_id=report_id))
    return _render_report_form(settings, request.form.get("location_id", type=int))


@app.route("/report/<int:report_id>")
def report_detail(report_id):
    public_view = request.args.get("public") == "1"
    if public_view and not _settings()["public_board_enabled"] and not g.user:
        return redirect(url_for("login"))
    report = _report_by_id(report_id, public=public_view)
    if not report:
        abort(404)
    if not g.user and not public_view:
        return redirect(url_for("login"))
    if g.user and not public_view and not _can_view_report(report):
        abort(403)
    report = dict(report)
    report["updates"] = [] if public_view else _updates(report_id)
    feedback = None
    if public_view:
        pass
    elif DEMO_MODE:
        feedback = report.get("feedback")
    else:
        feedback = _query(
            "SELECT rating, note FROM feedback WHERE report_id = %s AND reporter_id = %s",
            (report_id, g.user["id"]),
            one=True,
        )
    staff = (
        _query("SELECT id, name, role FROM users WHERE role = 'maintenance' ORDER BY name")
        if g.user and g.user["role"] == "admin" and not DEMO_MODE
        else [DEMO_USERS["maintenance"]]
        if g.user and g.user["role"] == "admin"
        else []
    )
    return render_template(
        "detail.html",
        report=report,
        feedback=feedback,
        statuses=STATUSES,
        staff=staff,
        public_view=public_view,
        work_logs=(
            _work_logs(report_id)
            if g.user
            and g.user["role"] in ("maintenance", "admin")
            and not public_view
            else []
        ),
    )


@app.route("/report/<int:report_id>/update", methods=["POST"])
@roles_required("maintenance", "admin")
def update_report(report_id):
    report = _report_by_id(report_id)
    status = request.form.get("status", "")
    note = request.form.get("note", "").strip()
    if not report:
        abort(404)
    if g.user["role"] == "maintenance" and not _can_view_report(report):
        abort(403)
    if status not in STATUSES or not note or len(note) > 500:
        flash("Choose a status and add an update of up to 500 characters.", "error")
        return redirect(url_for("report_detail", report_id=report_id))
    if DEMO_MODE:
        report["status"] = status
        report["updated_at"] = datetime.now()
        report["updates"].append(
            {"status": status, "note": note, "created_at": report["updated_at"]}
        )
    else:
        _execute(
            "UPDATE reports SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (status, report_id),
        )
        _execute(
            "INSERT INTO report_updates (report_id, actor_id, status, note) VALUES (%s, %s, %s, %s)",
            (report_id, g.user["id"], status, note),
        )
    flash("Progress update saved.", "success")
    return redirect(url_for("report_detail", report_id=report_id))


@app.route("/report/<int:report_id>/work-log", methods=["POST"])
@roles_required("maintenance", "admin")
def add_work_log(report_id):
    report = _report_by_id(report_id)
    if not report:
        abort(404)
    if g.user["role"] == "maintenance" and not _can_view_report(report):
        abort(403)

    labor_minutes = request.form.get("labor_minutes", type=int)
    parts_used = request.form.get("parts_used", "").strip()
    note = request.form.get("note", "").strip()
    follow_up_raw = request.form.get("follow_up_at", "").strip()
    try:
        follow_up_at = date.fromisoformat(follow_up_raw) if follow_up_raw else None
    except ValueError:
        follow_up_at = None
        flash("Choose a valid follow-up date.", "error")
        return redirect(url_for("report_detail", report_id=report_id))
    if (
        labor_minutes is None
        or labor_minutes < 1
        or labor_minutes > 1440
        or len(parts_used) > 500
        or not note
        or len(note) > 500
    ):
        flash(
            "Enter labor between 1 minute and 24 hours, a note, and parts details up to 500 characters.",
            "error",
        )
        return redirect(url_for("report_detail", report_id=report_id))

    if DEMO_MODE:
        DEMO_WORK_LOGS.append(
            {
                "id": max((row["id"] for row in DEMO_WORK_LOGS), default=0) + 1,
                "report_id": report_id,
                "actor_name": g.user["name"],
                "labor_minutes": labor_minutes,
                "parts_used": parts_used or "None",
                "note": note,
                "follow_up_at": follow_up_at,
                "created_at": datetime.now(),
            }
        )
    else:
        _execute(
            """
            INSERT INTO maintenance_work_logs
                (report_id, actor_id, labor_minutes, parts_used, note, follow_up_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                report_id,
                g.user["id"],
                labor_minutes,
                parts_used or None,
                note,
                follow_up_at,
            ),
        )
    flash("Maintenance work log added.", "success")
    return redirect(url_for("report_detail", report_id=report_id))


@app.route("/report/<int:report_id>/assign", methods=["POST"])
@roles_required("admin")
def assign_report(report_id):
    report = _report_by_id(report_id)
    assignee_id = request.form.get("assignee_id", type=int)
    if not report:
        abort(404)
    if DEMO_MODE:
        if assignee_id not in (None, DEMO_USERS["maintenance"]["id"]):
            abort(400, description="Choose an active maintenance account.")
        report["assigned_to"] = assignee_id
        report["assignee_name"] = DEMO_USERS["maintenance"]["name"] if assignee_id else None
        report["status"] = "Assigned" if assignee_id else "Submitted"
        report["updated_at"] = datetime.now()
        report["updates"].append(
            {
                "status": report["status"],
                "note": f"Assigned to {report['assignee_name']}." if assignee_id else "Assignment removed.",
                "created_at": report["updated_at"],
            }
        )
    else:
        if assignee_id and not _query(
            "SELECT id FROM users WHERE id = %s AND role = 'maintenance'",
            (assignee_id,),
            one=True,
        ):
            abort(400, description="Choose an active maintenance account.")
        _execute(
            "UPDATE reports SET assigned_to = %s, status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
            (assignee_id, "Assigned" if assignee_id else "Submitted", report_id),
        )
        staff = _query("SELECT name FROM users WHERE id = %s", (assignee_id,), one=True) if assignee_id else None
        note = f"Assigned to {staff['name']}." if staff else "Assignment removed."
        _execute(
            "INSERT INTO report_updates (report_id, actor_id, status, note) VALUES (%s, %s, %s, %s)",
            (report_id, g.user["id"], "Assigned" if assignee_id else "Submitted", note),
        )
    flash("Work assignment updated.", "success")
    return redirect(url_for("report_detail", report_id=report_id))


@app.route("/report/<int:report_id>/feedback", methods=["POST"])
@roles_required("student", "lecturer")
def add_feedback(report_id):
    report = _report_by_id(report_id)
    if not report or int(report["reporter_id"]) != int(g.user["id"]):
        abort(404)
    rating = request.form.get("rating", type=int)
    note = request.form.get("note", "").strip()
    if report["status"] != "Resolved":
        abort(400, description="Feedback is available after a report is resolved.")
    if not DEMO_MODE and _query(
        "SELECT id FROM feedback WHERE report_id = %s",
        (report_id,),
        one=True,
    ):
        flash("Feedback has already been sent for this report.", "error")
        return redirect(url_for("report_detail", report_id=report_id))
    if rating not in range(1, 6) or len(note) > 500:
        flash("Choose a rating from 1 to 5; feedback can be up to 500 characters.", "error")
    elif DEMO_MODE:
        report["feedback"] = {"rating": rating, "note": note}
        flash("Thanks for helping improve campus maintenance.", "success")
    else:
        _execute(
            "INSERT INTO feedback (report_id, reporter_id, rating, note) VALUES (%s, %s, %s, %s)",
            (report_id, g.user["id"], rating, note or None),
        )
        flash("Thanks for helping improve campus maintenance.", "success")
    return redirect(url_for("report_detail", report_id=report_id))


@app.route("/admin/users", methods=["GET", "POST"])
@roles_required("admin")
def manage_users():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        role = request.form.get("role", "")
        password = request.form.get("password", "")
        if (
            not name
            or len(name) > 120
            or len(email) > 190
            or not _valid_email(email)
            or role not in ROLES
        ):
            flash("Enter a name, valid email, and role.", "error")
        elif not OIDC_ENABLED and (len(password) < 12 or len(password) > 1024):
            flash("Use a temporary password between 12 and 1,024 characters.", "error")
        elif DEMO_MODE:
            flash("User management is available after connecting a PostgreSQL database.", "error")
        elif not OIDC_ENABLED and not SMTP_ENABLED:
            flash("Email delivery must be configured before creating password accounts.", "error")
        else:
            try:
                user_id = _execute(
                    "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, %s) RETURNING id",
                    (
                        name,
                        email,
                        generate_password_hash(password or secrets.token_urlsafe(32)),
                        role,
                    ),
                )
            except psycopg.IntegrityError:
                flash("That email already has an account.", "error")
            else:
                if OIDC_ENABLED:
                    flash("Account provisioned. The user can sign in with their verified university account.", "success")
                else:
                    try:
                        _send_verification_email(user_id, email)
                    except (smtplib.SMTPException, OSError, ssl.SSLError):
                        app.logger.exception("Could not send staff account verification email")
                        flash(
                            "Account created, but the verification message could not be sent. "
                            "The user can request a new link from the sign-in page.",
                            "error",
                        )
                    else:
                        flash(
                            "Account created. The user must verify their email before signing in.",
                            "success",
                        )
    users = (
        _query("SELECT id, name, email, role, created_at FROM users ORDER BY name")
        if not DEMO_MODE
        else list(DEMO_USERS.values())
    )
    return render_template(
        "users.html",
        users=users,
        roles=ROLES,
        oidc_enabled=OIDC_ENABLED,
        smtp_enabled=SMTP_ENABLED,
    )


@app.route("/admin/locations", methods=["GET", "POST"])
@roles_required("admin")
def manage_locations():
    global DEMO_NEXT_LOCATION_ID
    if request.method == "POST":
        action = request.form.get("action", "")
        if action == "add":
            building = request.form.get("building", "").strip()
            room = request.form.get("room", "").strip()
            if not building or len(building) > 100 or not room or len(room) > 100:
                flash("Enter a building and room, each up to 100 characters.", "error")
            elif DEMO_MODE:
                duplicate = any(
                    row["building"].casefold() == building.casefold()
                    and row["room"].casefold() == room.casefold()
                    for row in DEMO_LOCATIONS
                )
                if duplicate:
                    flash("That building and room are already in the directory.", "error")
                else:
                    DEMO_LOCATIONS.append(
                        {
                            "id": DEMO_NEXT_LOCATION_ID,
                            "building": building,
                            "room": room,
                            "active": True,
                        }
                    )
                    DEMO_NEXT_LOCATION_ID += 1
                    flash("Location added to the demo directory.", "success")
            else:
                try:
                    _execute(
                        "INSERT INTO campus_locations (building, room) VALUES (%s, %s)",
                        (building, room),
                    )
                except psycopg.IntegrityError:
                    flash("That building and room are already in the directory.", "error")
                else:
                    flash("Campus location added.", "success")
        elif action == "toggle":
            location_id = request.form.get("location_id", type=int)
            location = _location_by_id(location_id, active_only=False) if location_id else None
            if not location:
                abort(404)
            if DEMO_MODE:
                location["active"] = not location["active"]
            else:
                _execute(
                    "UPDATE campus_locations SET is_active = NOT is_active WHERE id = %s",
                    (location_id,),
                )
            flash("Campus location availability updated.", "success")
        else:
            abort(400, description="Choose a valid campus-location action.")
        return redirect(url_for("manage_locations"))
    return render_template("locations.html", locations=_list_locations(active_only=False))


@app.route("/admin/analytics")
@roles_required("admin")
def service_analytics():
    today = date.today()
    try:
        end_date = date.fromisoformat(request.args.get("end", today.isoformat()))
        start_date = date.fromisoformat(
            request.args.get("start", (today - timedelta(days=29)).isoformat())
        )
    except ValueError:
        abort(400, description="Choose valid start and end dates.")
    if start_date > end_date or (end_date - start_date).days > 365:
        abort(400, description="Choose a date range of up to 366 days.")
    return render_template(
        "analytics.html",
        metrics=_analytics(start_date, end_date),
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
    )


@app.route("/admin/settings", methods=["GET", "POST"])
@roles_required("admin")
def manage_settings():
    if request.method == "POST":
        new_settings = {
            "public_board_enabled": request.form.get("public_board_enabled") == "on",
            "anonymous_reports_enabled": request.form.get("anonymous_reports_enabled") == "on",
        }
        for urgency in SLA_URGENCIES:
            raw_target = request.form.get(f"sla_hours_{urgency.lower()}", "").strip()
            if raw_target:
                try:
                    target = int(raw_target)
                except ValueError:
                    target = 0
                if target < 1 or target > 87600:
                    flash(
                        f"Enter a valid {urgency.lower()} response target between 1 and 87,600 hours, or leave it blank.",
                        "error",
                    )
                    return render_template("settings.html", settings=_settings())
                new_settings[f"sla_hours_{urgency.lower()}"] = str(target)
            else:
                new_settings[f"sla_hours_{urgency.lower()}"] = ""
        if DEMO_MODE:
            DEMO_SETTINGS.update(new_settings)
        else:
            for key, value in new_settings.items():
                if key in ("public_board_enabled", "anonymous_reports_enabled"):
                    stored_value = "true" if value else "false"
                else:
                    stored_value = value
                _execute(
                    """
                    INSERT INTO app_settings (setting_key, setting_value)
                    VALUES (%s, %s)
                    ON CONFLICT (setting_key) DO UPDATE
                    SET setting_value = EXCLUDED.setting_value
                    """,
                    (key, stored_value),
                )
        flash("System settings saved.", "success")
        return redirect(url_for("manage_settings"))
    return render_template("settings.html", settings=_settings())


@app.route("/demo-role", methods=["POST"])
@roles_required("student", "lecturer", "maintenance", "admin")
def demo_role():
    if not DEMO_MODE:
        abort(404)
    role = request.form.get("role", "")
    if role not in DEMO_USERS:
        abort(400)
    session["demo_role"] = role
    return redirect(url_for("dashboard"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if DEMO_MODE:
        return redirect(url_for("dashboard"))
    if university_sso is not None:
        return redirect(
            university_sso.authorize_redirect(
                OIDC_REDIRECT_URI
                or url_for("oidc_callback", _external=True)
            )
        )
    if request.method == "POST":
        if not _auth_attempt_allowed("login"):
            abort(429, description="Too many sign-in attempts. Try again in 15 minutes.")
        if request.form.get("website", "").strip():
            abort(400, description="Form could not be verified.")
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = (
            _query(
                "SELECT id, name, email, role, password_hash, email_verified_at, session_version FROM users WHERE email = %s",
                (email,),
                one=True,
            )
            if len(email) <= 190 and _valid_email(email) and len(password) <= 1024
            else None
        )
        if not user or not check_password_hash(user["password_hash"], password):
            flash("Email or password was not recognized.", "error")
        elif user["email_verified_at"] is None:
            flash(
                "Verify your email before signing in. You can request a new verification link below.",
                "error",
            )
        else:
            _execute(
                "DELETE FROM auth_attempts WHERE bucket_hash = %s",
                (_auth_rate_key("login"),),
            )
            session.clear()
            session["user_id"] = user["id"]
            session["auth_version"] = user["session_version"]
            return redirect(url_for("dashboard"))
    return render_template("auth.html", mode="login")


@app.route("/auth/university/callback")
def oidc_callback():
    if university_sso is None or DEMO_MODE:
        abort(404)
    token = university_sso.authorize_access_token()
    identity = token.get("userinfo")
    if not identity or identity.get("email_verified") is not True:
        abort(403, description="Use a university account with a verified email address.")
    subject = identity.get("sub")
    email = identity.get("email", "").strip().lower()
    if not subject or not email:
        abort(403, description="The university identity provider did not return a verified account.")

    user = _query(
        "SELECT id, oidc_sub, session_version FROM users WHERE LOWER(email) = %s",
        (email,),
        one=True,
    )
    if not user:
        abort(
            403,
            description="Your verified university account has not been provisioned in Campus Care.",
        )
    if user["oidc_sub"] and user["oidc_sub"] != subject:
        abort(403, description="This university identity is linked to a different campus account.")
    if not user["oidc_sub"]:
        _execute(
            "UPDATE users SET oidc_sub = %s WHERE id = %s AND oidc_sub IS NULL",
            (subject, user["id"]),
        )
        linked_user = _query(
            "SELECT oidc_sub FROM users WHERE id = %s",
            (user["id"],),
            one=True,
        )
        if not linked_user or linked_user["oidc_sub"] != subject:
            abort(403, description="This university identity could not be linked to the campus account.")
    session.clear()
    session["user_id"] = user["id"]
    session["auth_version"] = user["session_version"]
    return redirect(url_for("dashboard"))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if DEMO_MODE:
        return redirect(url_for("dashboard"))
    if university_sso is not None:
        return redirect(url_for("login"))
    if request.method == "POST":
        if not SMTP_ENABLED:
            flash(
                "Account creation requires email delivery. Ask the administrator to configure SMTP.",
                "error",
            )
            return render_template(
                "auth.html", mode="signup", email_enabled=SMTP_ENABLED
            )
        if not _auth_attempt_allowed("signup"):
            abort(429, description="Too many account-creation attempts. Try again in 15 minutes.")
        if request.form.get("website", "").strip():
            abort(400, description="Form could not be verified.")
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        role = request.form.get("role", "")
        password = request.form.get("password", "")
        if (
            not name
            or len(name) > 120
            or len(email) > 190
            or not _valid_email(email)
            or role not in ("student", "lecturer")
        ):
            flash("Enter your name and choose Student or Lecturer.", "error")
        elif len(password) < 12 or len(password) > 1024:
            flash("Use a password between 12 and 1,024 characters.", "error")
        else:
            try:
                user_id = _execute(
                    "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, %s) RETURNING id",
                    (name, email, generate_password_hash(password), role),
                )
            except psycopg.IntegrityError:
                flash(
                    "If this address can be registered, a verification message will be sent.",
                    "success",
                )
            else:
                try:
                    _send_verification_email(user_id, email)
                except (smtplib.SMTPException, OSError, ssl.SSLError):
                    app.logger.exception("Could not send account verification email")
                    flash(
                        "Your account was created, but the verification message could not be sent. "
                        "Try requesting a new link later.",
                        "error",
                    )
                else:
                    flash(
                        "Check your inbox for a verification link before signing in.",
                        "success",
                    )
                    return redirect(url_for("login"))
    return render_template("auth.html", mode="signup", email_enabled=SMTP_ENABLED)


@app.route("/verify-email/<token>", methods=["GET", "POST"])
def verify_email(token):
    if DEMO_MODE or university_sso is not None:
        abort(404)
    if request.method == "GET":
        return render_template("auth_action.html", mode="verify_email", token=token)
    if len(token) > 128:
        flash("That verification link is invalid or expired. Request a new one.", "error")
        return redirect(url_for("resend_verification"))
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    user_id = _execute(
        """
        WITH consumed AS (
            DELETE FROM auth_tokens
            WHERE token_hash = %s AND purpose = 'verify_email'
              AND expires_at > CURRENT_TIMESTAMP
            RETURNING user_id
        )
        UPDATE users SET email_verified_at = CURRENT_TIMESTAMP
        WHERE id = (SELECT user_id FROM consumed)
          AND email_verified_at IS NULL
        RETURNING id
        """,
        (token_hash,),
    )
    if user_id is None:
        flash("That verification link is invalid, expired, or already used.", "error")
        return redirect(url_for("resend_verification"))
    flash("Email verified. You can now sign in.", "success")
    return redirect(url_for("login"))


@app.route("/verify-email/resend", methods=["GET", "POST"])
def resend_verification():
    if DEMO_MODE or university_sso is not None:
        abort(404)
    if request.method == "POST":
        if request.form.get("website", "").strip():
            abort(400, description="Form could not be verified.")
        if not SMTP_ENABLED:
            flash("Email delivery is not configured. Contact the administrator.", "error")
            return render_template("auth_action.html", mode="resend_verification")
        if not _auth_attempt_allowed("verify-resend"):
            abort(429, description="Too many link requests. Try again in 15 minutes.")
        email = request.form.get("email", "").strip().lower()
        if len(email) <= 190 and _valid_email(email):
            user = _query(
                "SELECT id FROM users WHERE email = %s AND email_verified_at IS NULL",
                (email,),
                one=True,
            )
            if user:
                try:
                    _send_verification_email(user["id"], email)
                except (smtplib.SMTPException, OSError, ssl.SSLError):
                    app.logger.exception("Could not resend account verification email")
        flash(
            "If the address belongs to an unverified account, a new link will be sent.",
            "success",
        )
        return redirect(url_for("login"))
    return render_template("auth_action.html", mode="resend_verification")


@app.route("/password-reset", methods=["GET", "POST"])
def request_password_reset():
    if DEMO_MODE or university_sso is not None:
        abort(404)
    if request.method == "POST":
        if request.form.get("website", "").strip():
            abort(400, description="Form could not be verified.")
        if not SMTP_ENABLED:
            flash("Email delivery is not configured. Contact the administrator.", "error")
            return render_template("auth_action.html", mode="password_reset_request")
        if not _auth_attempt_allowed("password-reset"):
            abort(429, description="Too many reset requests. Try again in 15 minutes.")
        email = request.form.get("email", "").strip().lower()
        if len(email) <= 190 and _valid_email(email):
            user = _query(
                "SELECT id FROM users WHERE email = %s AND email_verified_at IS NOT NULL",
                (email,),
                one=True,
            )
            if user:
                try:
                    _send_password_reset_email(user["id"], email)
                except (smtplib.SMTPException, OSError, ssl.SSLError):
                    app.logger.exception("Could not send password reset email")
        flash(
            "If a verified account uses that address, a password reset link will be sent.",
            "success",
        )
        return redirect(url_for("login"))
    return render_template("auth_action.html", mode="password_reset_request")


@app.route("/password-reset/<token>", methods=["GET", "POST"])
def reset_password(token):
    if DEMO_MODE or university_sso is not None:
        abort(404)
    if request.method == "GET":
        return render_template("auth_action.html", mode="password_reset", token=token)
    password = request.form.get("password", "")
    confirmation = request.form.get("password_confirmation", "")
    if len(token) > 128:
        flash("That reset link is invalid or expired. Request a new one.", "error")
        return redirect(url_for("request_password_reset"))
    if len(password) < 12 or len(password) > 1024 or password != confirmation:
        flash("Passwords must match and contain between 12 and 1,024 characters.", "error")
        return render_template(
            "auth_action.html", mode="password_reset", token=token
        )
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    user_id = _execute(
        """
        WITH consumed AS (
            DELETE FROM auth_tokens
            WHERE token_hash = %s AND purpose = 'password_reset'
              AND expires_at > CURRENT_TIMESTAMP
            RETURNING user_id
        )
        UPDATE users
        SET password_hash = %s, session_version = session_version + 1
        WHERE id = (SELECT user_id FROM consumed)
          AND email_verified_at IS NOT NULL
        RETURNING id
        """,
        (token_hash, generate_password_hash(password)),
    )
    if user_id is None:
        flash("That reset link is invalid or expired. Request a new one.", "error")
        return redirect(url_for("request_password_reset"))
    _execute("DELETE FROM auth_tokens WHERE user_id = %s", (user_id,))
    flash("Password updated. Sign in with your new password.", "success")
    return redirect(url_for("login"))


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login") if not DEMO_MODE else url_for("dashboard"))


@app.route("/uploads/<path:filename>")
@login_required
def uploaded_file(filename):
    if not secure_filename(filename) or Path(filename).suffix.lower().lstrip(".") not in ALLOWED_EXTENSIONS:
        abort(404)
    if DEMO_MODE:
        report = next((r for r in DEMO_REPORTS if r["photo_name"] == filename), None)
    else:
        report = _query("SELECT * FROM reports WHERE photo_name = %s", (filename,), one=True)
    if not report or not _can_view_report(report):
        abort(404)
    return send_from_directory(UPLOAD_DIR, filename, as_attachment=False, max_age=3600)


@app.cli.command("init-db")
def init_db():
    """Create the PostgreSQL tables from schema.sql."""
    if DEMO_MODE:
        raise click.ClickException("Set DATABASE_URL before initializing PostgreSQL.")
    connection = _db()
    cursor = connection.cursor()
    try:
        for statement in (ROOT / "schema.sql").read_text(encoding="utf-8").split(";"):
            if statement.strip():
                cursor.execute(statement)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
    click.echo("Database schema created.")


@app.cli.command("prune-photos")
def prune_photos():
    """Remove report photos older than PHOTO_RETENTION_DAYS and clear their references."""
    if PHOTO_RETENTION_DAYS is None:
        raise click.ClickException(
            "Set PHOTO_RETENTION_DAYS to an approved positive retention period before pruning."
        )
    cutoff = datetime.now() - timedelta(days=PHOTO_RETENTION_DAYS)
    if DEMO_MODE:
        expired = [
            report
            for report in DEMO_REPORTS
            if report["photo_name"] and report["created_at"] < cutoff
        ]
    else:
        expired = _query(
            """
            SELECT id, photo_name FROM reports
            WHERE photo_name IS NOT NULL AND created_at < %s
            """,
            (cutoff,),
        )
    removed = 0
    for report in expired:
        filename = report["photo_name"]
        photo_path = (UPLOAD_DIR / filename).resolve()
        if photo_path.parent != UPLOAD_DIR.resolve():
            raise click.ClickException("A stored photo path escaped the upload directory.")
        try:
            photo_path.unlink()
        except FileNotFoundError:
            pass
        if DEMO_MODE:
            report["photo_name"] = None
        else:
            _execute(
                "UPDATE reports SET photo_name = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = %s",
                (report["id"],),
            )
        removed += 1
    click.echo(f"Cleared {removed} expired report photo(s).")


@app.cli.command("prune-auth-attempts")
def prune_auth_attempts():
    """Remove expired login and signup rate-limit buckets."""
    if DEMO_MODE:
        raise click.ClickException(
            "Set DATABASE_URL before pruning authentication attempt records."
        )
    _execute(
        """
        DELETE FROM auth_attempts
        WHERE window_started_at < CURRENT_TIMESTAMP - INTERVAL '1 day'
        """
    )
    click.echo("Expired authentication attempt records cleared.")


@app.cli.command("create-admin")
@click.option("--name", prompt=True)
@click.option("--email", prompt=True)
@click.password_option()
def create_admin(name, email, password):
    """Create the first administrator account in PostgreSQL mode."""
    if DEMO_MODE:
        raise click.ClickException("Set DATABASE_URL before creating an administrator.")
    name = name.strip()
    email = email.strip().lower()
    if not name or len(name) > 120 or len(email) > 190 or not _valid_email(email):
        raise click.ClickException("Enter a valid name and email address.")
    if len(password) < 12 or len(password) > 1024:
        raise click.ClickException(
            "Password must contain between 12 and 1,024 characters."
        )
    try:
        _execute(
            "INSERT INTO users (name, email, password_hash, role, email_verified_at) "
            "VALUES (%s, %s, %s, 'admin', CURRENT_TIMESTAMP)",
            (name, email, generate_password_hash(password)),
        )
    except psycopg.IntegrityError as exc:
        raise click.ClickException("That email already has an account.") from exc
    click.echo("Administrator account created.")


@app.cli.command("verify-account")
@click.option("--email", prompt=True)
def verify_account(email):
    """Mark an existing operator-provisioned account as email-verified."""
    if DEMO_MODE:
        raise click.ClickException("Set DATABASE_URL before verifying an account.")
    email = email.strip().lower()
    if len(email) > 190 or not _valid_email(email):
        raise click.ClickException("Enter a valid email address.")
    user_id = _execute(
        """
        UPDATE users
        SET email_verified_at = COALESCE(email_verified_at, CURRENT_TIMESTAMP)
        WHERE email = %s
        RETURNING id
        """,
        (email,),
    )
    if user_id is None:
        raise click.ClickException("No account uses that email address.")
    click.echo("Account email marked verified.")


@app.errorhandler(400)
def bad_request(error):
    return render_template("error.html", code=400, message=getattr(error, "description", "Please check your request.")), 400


@app.errorhandler(403)
def forbidden(_error):
    return render_template("error.html", code=403, message="This area is only available to your campus role."), 403


@app.errorhandler(404)
def not_found(_error):
    return render_template("error.html", code=404, message="We couldn't find that campus report or page."), 404


@app.errorhandler(413)
def too_large(_error):
    return render_template("error.html", code=413, message="That photo is too large. Choose an image under 8 MB."), 413


if __name__ == "__main__":
    app.run(debug=APP_ENV != "production")
