"""Command line interface for the purchase order tracker."""
from __future__ import annotations

import argparse
import sys
from datetime import date

from . import core


def _table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [max([len(h)] + [len(r[i]) for r in rows]) for i, h in enumerate(headers)]

    def line(cells: list[str]) -> str:
        return "  ".join(c.ljust(w) for c, w in zip(cells, widths)).rstrip()

    return "\n".join([line(headers), line(["-" * w for w in widths]), *(line(r) for r in rows)])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="po_tracker", description="Open balances on purchase orders.")
    parser.add_argument("command", choices=["load", "balances", "overdue", "vendors"])
    parser.add_argument("--pos", help="PO lines CSV")
    parser.add_argument("--receipts", help="receipts CSV")
    parser.add_argument("--db", default=":memory:", help="SQLite file (default: in memory)")
    parser.add_argument("--today", default=None, help="date for overdue, YYYY-MM-DD (default: today)")
    parser.add_argument("--all", action="store_true", help="balances: include fully received lines")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the tool. Returns the exit code."""
    args = build_parser().parse_args(argv)
    try:
        conn = core.connect(args.db)
        if args.pos or args.receipts or args.command == "load":
            if not (args.pos and args.receipts):
                raise ValueError("--pos and --receipts are both required to load data")
            lines, receipts = core.load(conn, args.pos, args.receipts)
            if args.command == "load":
                print(f"Loaded {lines} PO lines and {receipts} receipts into {args.db}")
                return 0
        if args.command == "balances":
            rows = [[i["po"], str(i["line"]), i["vendor"], i["item"], f"{i['ordered']:g}", f"{i['received']:g}",
                     f"{i['open_qty']:g}", f"{i['open_value']:,.2f}"] for i in core.balances(conn, args.all)]
            print(_table(["PO", "Line", "Vendor", "Item", "Ordered", "Received", "Open", "Open value"], rows))
            print(f"\nTotal open value: {sum(i['open_value'] for i in core.balances(conn)):,.2f}")
        elif args.command == "overdue":
            today = date.fromisoformat(args.today) if args.today else date.today()
            rows = [[i["po"], str(i["line"]), i["vendor"], i["due_date"], str(i["days_late"]), f"{i['open_value']:,.2f}"]
                    for i in core.overdue(conn, today)]
            print(_table(["PO", "Line", "Vendor", "Due", "Days late", "Open value"], rows))
        elif args.command == "vendors":
            rows = [[v["vendor"], str(v["lines"]), f"{v['open_value']:,.2f}"] for v in core.by_vendor(conn)]
            print(_table(["Vendor", "Open lines", "Open value"], rows))
    except (ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0
