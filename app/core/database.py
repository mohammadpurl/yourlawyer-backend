import os
import logging
from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool
from dotenv import load_dotenv
from urllib.parse import urlparse

# Load environment variables
load_dotenv(override=True)

# Prefer DATABASE_URL if provided (works best in Docker)
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")

if SQLALCHEMY_DATABASE_URL:
    # Normalize url scheme if needed
    if SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace(
            "postgres://", "postgresql+psycopg://", 1
        )
else:
    # Fallback to discrete env vars
    DB_USER = os.getenv("POSTGRES_USER")
    DB_PASSWORD = os.getenv("POSTGRES_PASSWORD")
    DB_HOST = os.getenv("POSTGRES_SERVER")
    DB_PORT = os.getenv("POSTGRES_PORT")
    DB_NAME = os.getenv("POSTGRES_DB")

    missing_vars = [
        var_name
        for var_name, value in {
            "POSTGRES_USER": DB_USER,
            "POSTGRES_PASSWORD": DB_PASSWORD,
            "POSTGRES_SERVER": DB_HOST,
            "POSTGRES_PORT": DB_PORT,
            "POSTGRES_DB": DB_NAME,
        }.items()
        if not value
    ]

    if missing_vars:
        # Helpful message but do not reference localhost implicitly
        raise ValueError(
            "Database is not configured. Set DATABASE_URL or all of: "
            + ", ".join(missing_vars)
        )

    SQLALCHEMY_DATABASE_URL = (
        f"postgresql+psycopg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )


# Log database connection details (password masked)
def _log_db_connection_details(db_url: str) -> None:
    try:
        parsed = urlparse(db_url)
        driver = parsed.scheme
        host = parsed.hostname
        port = parsed.port
        database = parsed.path.lstrip("/") if parsed.path else None
        user = parsed.username
        password_present = parsed.password is not None
        options = parsed.query or None

        logging.info(
            "Database connection: driver=%s host=%s port=%s db=%s user=%s password=%s options=%s",
            driver,
            host,
            port,
            database,
            user,
            "<set>" if password_present else None,
            options,
        )
    except Exception as exc:
        logging.warning("Unable to log DB connection details: %s", exc)


# Ensure logging is configured at least at INFO level if not configured by app
logging.basicConfig(level=logging.INFO)

# Emit one-time log for where we are connecting to
_log_db_connection_details(SQLALCHEMY_DATABASE_URL)

# Create engine with connection pooling
# Ensure UTF-8 encoding for Persian/Farsi text support
# Add client_encoding=UTF8 to connection options to properly handle Persian text
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    poolclass=QueuePool,
    pool_size=5,
    max_overflow=10,
    pool_timeout=60,
    pool_recycle=1800,
    pool_pre_ping=True,
    connect_args={
        "connect_timeout": 30,
        "keepalives": 1,
        "keepalives_idle": 60,
        "keepalives_interval": 30,
        "keepalives_count": 10,
        "application_name": "airport_bot",
        "options": "-c statement_timeout=30000 -c client_encoding=UTF8",
    },
)


# Event listener to ensure UTF-8 encoding on each connection
# This is a backup measure - the options parameter should handle it, but this ensures it
@event.listens_for(engine, "connect")
def set_utf8_encoding(dbapi_conn, connection_record):
    """Ensure UTF-8 encoding is set for each database connection."""
    try:
        # Execute SET client_encoding = 'UTF8' for each new connection
        # This ensures Persian/Farsi text is properly handled
        # Works with both psycopg2 and psycopg3
        if hasattr(dbapi_conn, "cursor"):
            cursor = dbapi_conn.cursor()
            cursor.execute("SET client_encoding = 'UTF8'")
            cursor.close()
            if hasattr(dbapi_conn, "commit"):
                dbapi_conn.commit()
            elif hasattr(dbapi_conn, "autocommit"):
                # psycopg3 might use autocommit differently
                pass
    except Exception as e:
        # Don't fail the connection if encoding setting fails
        # The options parameter should handle it anyway
        logging.debug(
            f"Could not set UTF-8 encoding via event listener (may be handled by options): {e}"
        )


# Session and Base classes
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# Dependency for FastAPI
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
