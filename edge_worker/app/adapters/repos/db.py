import os


APP_SCHEMA = os.getenv("EDGE_DB_SCHEMA", "edge_ingest")


def db_dsn() -> str:
    host = os.getenv("EDGE_DB_HOST", "postgres")
    port = os.getenv("EDGE_DB_PORT", "5432")
    name = os.getenv("EDGE_DB_NAME", "edge")
    user = os.getenv("EDGE_DB_USER", "edge")
    password = os.getenv("EDGE_DB_PASSWORD", "")
    return f"host={host} port={port} dbname={name} user={user} password={password}"
