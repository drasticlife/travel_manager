"""여행 자료 수집·검증 CLI.

핵심 원칙: LLM 은 추출·분류만 한다. 좌표·place_id 같은 사실은 Places API 만 채운다.
스펙: docs/superpowers/specs/2026-09-06-travel-manager-design.md
"""
import os
import sqlite3

_HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(_HERE, "schema.sql")
DEFAULT_DB = os.path.join(_HERE, "data", "trip.db")


def connect(db_path=DEFAULT_DB):
    """스키마가 적용된 연결을 반환한다. 없으면 만든다."""
    if db_path != ":memory:":
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        conn.executescript(f.read())
    return conn
