from datetime import date

import pytest

from po_tracker import core
from po_tracker.cli import main

POS = "po,line,vendor,item,qty,unit_price,due_date\nP1,1,Acme,Filter,10,5.00,2026-01-10\nP1,2,Acme,Belt,4,10.00,2026-03-01\nP2,1,Beta,Valve,2,100.00,2026-02-01\n"
RC = "po,line,qty,received_date\nP1,1,10,2026-01-09\nP1,2,1,2026-02-01\nP1,2,1,2026-02-02\n"


def _files(tmp_path, pos=POS, rc=RC):
    (tmp_path / "p.csv").write_text(pos)
    (tmp_path / "r.csv").write_text(rc)
    return tmp_path / "p.csv", tmp_path / "r.csv"


@pytest.fixture
def conn(tmp_path):
    c = core.connect()
    core.load(c, *_files(tmp_path))
    return c


def test_load_counts(tmp_path):
    assert core.load(core.connect(), *_files(tmp_path)) == (3, 3)


def test_open_balances_exclude_closed(conn):
    keys = [(b["po"], b["line"]) for b in core.balances(conn)]
    assert keys == [("P1", 2), ("P2", 1)]


def test_partial_receipts_are_summed(conn):
    line = [b for b in core.balances(conn) if b["po"] == "P1"][0]
    assert line["received"] == 2 and line["open_qty"] == 2 and line["open_value"] == 20.0


def test_include_closed(conn):
    assert len(core.balances(conn, include_closed=True)) == 3


def test_overdue_sorted_by_days_late(conn):
    late = core.overdue(conn, date(2026, 3, 15))
    assert [i["po"] for i in late] == ["P2", "P1"]
    assert late[0]["days_late"] == 42


def test_not_overdue_on_due_date(conn):
    assert core.overdue(conn, date(2026, 2, 1)) == []


def test_over_receipt_is_flagged_not_negative(tmp_path):
    c = core.connect()
    core.load(c, *_files(tmp_path, rc=RC + "P2,1,5,2026-02-02\n"))
    line = [b for b in core.balances(c, True) if b["po"] == "P2"][0]
    assert line["open_qty"] == 0 and line["over_received"]


def test_vendor_totals(conn):
    assert core.by_vendor(conn)[0] == {"vendor": "Beta", "lines": 1, "open_value": 200.0}


def test_receipt_for_unknown_line_rejected(tmp_path):
    with pytest.raises(ValueError, match="unknown PO line"):
        core.load(core.connect(), *_files(tmp_path, rc=RC + "P9,1,1,2026-01-01\n"))


def test_bad_number_and_date_rejected(tmp_path):
    with pytest.raises(ValueError, match="not a number"):
        core.load(core.connect(), *_files(tmp_path, pos=POS.replace("10,5.00", "ten,5.00")))
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        core.load(core.connect(), *_files(tmp_path, pos=POS.replace("2026-03-01", "03/01/2026")))


def test_missing_column(tmp_path):
    with pytest.raises(ValueError, match="missing column"):
        core.load(core.connect(), *_files(tmp_path, pos="po,line\nP1,1\n"))


def test_cli_balances_and_error(tmp_path, capsys):
    p, r = _files(tmp_path)
    assert main(["balances", "--pos", str(p), "--receipts", str(r)]) == 0
    assert "Total open value: 220.00" in capsys.readouterr().out
    assert main(["balances", "--pos", "nope.csv", "--receipts", "nope.csv"]) == 1


def test_cli_persisted_database(tmp_path, capsys):
    p, r = _files(tmp_path)
    db = str(tmp_path / "t.db")
    assert main(["load", "--pos", str(p), "--receipts", str(r), "--db", db]) == 0
    assert main(["vendors", "--db", db]) == 0
    assert "Beta" in capsys.readouterr().out
