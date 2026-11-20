"""Load purchase orders and receipts into SQLite and compute open balances."""
from __future__ import annotations

import csv
import sqlite3
from datetime import date
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS po_lines (
    po TEXT NOT NULL, line INTEGER NOT NULL, vendor TEXT NOT NULL, item TEXT NOT NULL,
    qty REAL NOT NULL, unit_price REAL NOT NULL, due_date TEXT NOT NULL,
    PRIMARY KEY (po, line));
CREATE TABLE IF NOT EXISTS receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, po TEXT NOT NULL, line INTEGER NOT NULL,
    qty REAL NOT NULL, received_date TEXT NOT NULL);
"""


def connect(path: str = ":memory:") -> sqlite3.Connection:
    """Open a database and make sure the tables exist."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _read(path: str | Path, columns: list[str]) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in columns if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: missing column(s) {', '.join(missing)}")
        return list(reader)


def _number(value: str, label: str, row: int) -> float:
    try:
        number = float(value)
    except ValueError:
        raise ValueError(f"row {row}: {label} '{value}' is not a number") from None
    if number < 0:
        raise ValueError(f"row {row}: {label} must not be negative")
    return number


def _day(value: str, label: str, row: int) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise ValueError(f"row {row}: {label} '{value}' is not YYYY-MM-DD") from None


def load(conn: sqlite3.Connection, pos_csv: str | Path, receipts_csv: str | Path) -> tuple[int, int]:
    """Replace the data with the two CSV files. Returns (po lines, receipts)."""
    pos = _read(pos_csv, ["po", "line", "vendor", "item", "qty", "unit_price", "due_date"])
    receipts = _read(receipts_csv, ["po", "line", "qty", "received_date"])
    po_rows = []
    for n, r in enumerate(pos, start=2):
        po_rows.append((r["po"], int(_number(r["line"], "line", n)), r["vendor"], r["item"],
                        _number(r["qty"], "qty", n), _number(r["unit_price"], "unit_price", n),
                        _day(r["due_date"], "due_date", n)))
    known = {(p[0], p[1]) for p in po_rows}
    rc_rows = []
    for n, r in enumerate(receipts, start=2):
        key = (r["po"], int(_number(r["line"], "line", n)))
        if key not in known:
            raise ValueError(f"row {n}: receipt for unknown PO line {key[0]}/{key[1]}")
        rc_rows.append((key[0], key[1], _number(r["qty"], "qty", n), _day(r["received_date"], "received_date", n)))
    with conn:
        conn.execute("DELETE FROM receipts")
        conn.execute("DELETE FROM po_lines")
        conn.executemany("INSERT INTO po_lines VALUES (?,?,?,?,?,?,?)", po_rows)
        conn.executemany("INSERT INTO receipts (po, line, qty, received_date) VALUES (?,?,?,?)", rc_rows)
    return len(po_rows), len(rc_rows)


def balances(conn: sqlite3.Connection, include_closed: bool = False) -> list[dict]:
    """Per line: ordered, received, open quantity and open value."""
    rows = conn.execute(
        """SELECT p.po, p.line, p.vendor, p.item, p.qty AS ordered, p.unit_price, p.due_date,
                  COALESCE(SUM(r.qty), 0) AS received
           FROM po_lines p LEFT JOIN receipts r ON r.po = p.po AND r.line = p.line
           GROUP BY p.po, p.line ORDER BY p.po, p.line""").fetchall()
    result = []
    for r in rows:
        open_qty = max(r["ordered"] - r["received"], 0.0)
        item = dict(r)
        item.update(open_qty=open_qty, open_value=round(open_qty * r["unit_price"], 2),
                    over_received=r["received"] > r["ordered"])
        if include_closed or open_qty > 0:
            result.append(item)
    return result


def overdue(conn: sqlite3.Connection, today: date) -> list[dict]:
    """Open lines whose due date is before today, with days late."""
    late = []
    for item in balances(conn):
        days = (today - date.fromisoformat(item["due_date"])).days
        if days > 0:
            late.append({**item, "days_late": days})
    return sorted(late, key=lambda i: -i["days_late"])


def by_vendor(conn: sqlite3.Connection) -> list[dict]:
    """Open value and open line count per vendor, largest first."""
    totals: dict[str, dict] = {}
    for item in balances(conn):
        t = totals.setdefault(item["vendor"], {"vendor": item["vendor"], "lines": 0, "open_value": 0.0})
        t["lines"] += 1
        t["open_value"] = round(t["open_value"] + item["open_value"], 2)
    return sorted(totals.values(), key=lambda t: -t["open_value"])
