"""Ligne de commande : traiter un dossier de factures et afficher la file de contrôle.

Usage :
    python -m factuagent.cli process data/invoices
    python -m factuagent.cli review
    python -m factuagent.cli suppliers
"""
from __future__ import annotations

import argparse
from pathlib import Path

from .tools import InvoiceTools

ICON = {"ok": "✓", "check": "!", "to_review": "✗"}


def _table(rows: list[dict]):
    if not rows:
        print("(aucun résultat)")
        return
    cols = list(rows[0])
    widths = {c: min(48, max(len(c), *(len(str(r[c])) for r in rows))) for c in cols}
    print("  ".join(c.ljust(widths[c]) for c in cols))
    for r in rows:
        print("  ".join(str(r[c])[:48].ljust(widths[c]) for c in cols))


def main():
    ap = argparse.ArgumentParser(prog="factuagent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("process"); p.add_argument("folder")
    sub.add_parser("review")
    sub.add_parser("suppliers")
    q = sub.add_parser("sql"); q.add_argument("query")
    args = ap.parse_args()

    if args.cmd == "process":
        tools = InvoiceTools(inbox=args.folder)
        counts = {"ok": 0, "check": 0, "to_review": 0}
        for name in tools.list_inbox():
            r = tools.process_invoice(name)
            counts[r["status"]] += 1
            codes = ", ".join(i["code"] for i in r["issues"] if i["severity"] != "info")
            print(f"{ICON[r['status']]} {name:42s} [{r['method']:7s}] {codes}")
        print(f"\n{sum(counts.values())} factures : {counts['ok']} OK, {counts['check']} à vérifier, "
              f"{counts['to_review']} à revoir")
    else:
        tools = InvoiceTools()
        if args.cmd == "review":
            _table(tools.review_queue())
        elif args.cmd == "suppliers":
            _table(tools.supplier_summary())
        elif args.cmd == "sql":
            res = tools.query_sql(args.query)
            print(res["error"]) if isinstance(res, dict) else _table(res)


if __name__ == "__main__":
    main()
