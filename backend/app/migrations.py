import logging

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

logger = logging.getLogger("netdoc.migrations")

# Columns added after the initial release. SQLite supports simple
# ADD COLUMN migrations directly, so we don't need a full migration
# framework for a single-user homelab app - just add what's missing.
ADDITIVE_COLUMNS = {
    "assets": [
        ("canonical_asset_id", "INTEGER"),
        ("cpu_cores", "INTEGER"),
        ("memory_mb", "INTEGER"),
        ("disk_gb", "REAL"),
        ("uptime_seconds", "INTEGER"),
    ],
    "connectors": [
        ("site", "TEXT"),
    ],
}


def run_additive_migrations(engine: Engine) -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table, columns in ADDITIVE_COLUMNS.items():
            if table not in existing_tables:
                continue  # a fresh install will get the full table from create_all()
            existing_columns = {c["name"] for c in inspector.get_columns(table)}
            for name, sql_type in columns:
                if name in existing_columns:
                    continue
                logger.info("Migrating: adding column %s.%s", table, name)
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))
