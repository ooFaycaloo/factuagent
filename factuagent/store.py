"""Stockage analytique des factures dans DuckDB."""
from __future__ import annotations

import json
from pathlib import Path

import duckdb

from .models import ProcessingResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
    id            INTEGER PRIMARY KEY,
    source_file   VARCHAR,
    method        VARCHAR,
    status        VARCHAR,
    invoice_number VARCHAR,
    issue_date    DATE,
    due_date      DATE,
    seller_name   VARCHAR,
    seller_siren  VARCHAR,
    seller_vat    VARCHAR,
    seller_iban   VARCHAR,
    buyer_name    VARCHAR,
    total_ht      DECIMAL(14,2),
    total_vat     DECIMAL(14,2),
    total_ttc     DECIMAL(14,2),
    processed_at  TIMESTAMP DEFAULT current_timestamp
);
CREATE SEQUENCE IF NOT EXISTS invoice_id_seq;
CREATE TABLE IF NOT EXISTS invoice_lines (
    invoice_id  INTEGER,
    line_no     INTEGER,
    description VARCHAR,
    quantity    DECIMAL(14,3),
    unit_price  DECIMAL(14,2),
    vat_rate    DECIMAL(5,2),
    total_ht    DECIMAL(14,2)
);
CREATE TABLE IF NOT EXISTS issues (
    invoice_id INTEGER,
    code       VARCHAR,
    severity   VARCHAR,
    message    VARCHAR
);
"""


class Store:
    def __init__(self, path: str | Path = "data/factuagent.duckdb", read_only: bool = False):
        self.path = str(path)
        if not read_only:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(self.path, read_only=read_only)
        if not read_only:
            self.con.execute(SCHEMA)

    # -- historique utilisé par la détection d'anomalies
    def find_duplicate(self, seller_siren: str | None, seller_name: str, number: str) -> int | None:
        row = self.con.execute(
            "SELECT id FROM invoices WHERE invoice_number = ? AND (seller_siren = ? OR seller_name = ?) LIMIT 1",
            [number, seller_siren, seller_name]).fetchone()
        return row[0] if row else None

    def known_ibans(self, seller_siren: str | None, seller_name: str) -> set[str]:
        rows = self.con.execute(
            "SELECT DISTINCT seller_iban FROM invoices WHERE seller_iban IS NOT NULL "
            "AND (seller_siren = ? OR seller_name = ?)", [seller_siren, seller_name]).fetchall()
        return {r[0] for r in rows}

    def supplier_amounts(self, seller_siren: str | None, seller_name: str) -> list[float]:
        rows = self.con.execute(
            "SELECT total_ttc FROM invoices WHERE seller_siren = ? OR seller_name = ?",
            [seller_siren, seller_name]).fetchall()
        return [float(r[0]) for r in rows]

    # -- écriture
    def save(self, result: ProcessingResult) -> int:
        inv_id = self.con.execute("SELECT nextval('invoice_id_seq')").fetchone()[0]
        inv = result.invoice
        if inv is None:
            self.con.execute("INSERT INTO invoices (id, source_file, method, status) VALUES (?, ?, ?, ?)",
                             [inv_id, result.source_file, result.method, result.status])
        else:
            self.con.execute(
                "INSERT INTO invoices (id, source_file, method, status, invoice_number, issue_date, due_date, "
                "seller_name, seller_siren, seller_vat, seller_iban, buyer_name, total_ht, total_vat, total_ttc) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [inv_id, result.source_file, result.method, result.status, inv.invoice_number, inv.issue_date,
                 inv.due_date, inv.seller.name, inv.seller.siren, inv.seller.vat_id, inv.seller.iban,
                 inv.buyer.name, inv.total_ht, inv.total_vat, inv.total_ttc])
            for n, l in enumerate(inv.lines, 1):
                self.con.execute("INSERT INTO invoice_lines VALUES (?, ?, ?, ?, ?, ?, ?)",
                                 [inv_id, n, l.description, l.quantity, l.unit_price, l.vat_rate, l.total_ht])
        for i in result.issues:
            self.con.execute("INSERT INTO issues VALUES (?, ?, ?, ?)", [inv_id, i.code, i.severity, i.message])
        return inv_id

    # -- lecture
    def query(self, sql: str, params: list | None = None) -> list[dict]:
        cur = self.con.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def to_json(self, rows: list[dict]) -> str:
        return json.dumps(rows, default=str, ensure_ascii=False, indent=2)

    def close(self):
        self.con.close()
