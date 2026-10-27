"""Outils métier exposés à un agent (serveur MCP et agent Claude intégré)."""
from __future__ import annotations

import os
import re
from pathlib import Path

from .pipeline import Pipeline
from .store import Store

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|attach|detach|copy|export|import|install|load|pragma|set|"
    r"call|checkpoint|vacuum|read_\w+|glob|httpfs)\b", re.IGNORECASE)


class InvoiceTools:
    def __init__(self, db_path: str | None = None, inbox: str | None = None):
        self.store = Store(db_path or os.environ.get("FACTUAGENT_DB", "data/factuagent.duckdb"))
        self.pipeline = Pipeline(self.store)
        self.inbox = Path(inbox or os.environ.get("FACTUAGENT_INBOX", "data/invoices")).resolve()

    # ------------------------------------------------------------ écriture contrôlée
    def process_invoice(self, filename: str) -> dict:
        """Traite une facture PDF de la boîte de réception (Factur-X, LLM ou règles)
        et renvoie les champs extraits, le statut et les anomalies détectées."""
        path = (self.inbox / filename).resolve()
        if self.inbox not in path.parents or path.suffix.lower() != ".pdf" or not path.exists():
            return {"error": f"fichier introuvable dans la boîte de réception : {filename}"}
        res = self.pipeline.process(path)
        return {"status": res.status, "method": res.method,
                "invoice": res.invoice.model_dump(mode="json") if res.invoice else None,
                "issues": [i.model_dump() for i in res.issues]}

    def list_inbox(self) -> list[str]:
        """Liste les PDF présents dans la boîte de réception."""
        return sorted(p.name for p in self.inbox.glob("*.pdf"))

    # ------------------------------------------------------------ lecture
    def list_invoices(self, status: str | None = None, supplier: str | None = None, limit: int = 50) -> list[dict]:
        """Liste les factures traitées. status ∈ {ok, check, to_review} ; supplier = recherche partielle."""
        sql = ("SELECT id, invoice_number, issue_date, due_date, seller_name, total_ttc, status, method, source_file "
               "FROM invoices WHERE 1=1")
        params: list = []
        if status:
            sql += " AND status = ?"; params.append(status)
        if supplier:
            sql += " AND seller_name ILIKE ?"; params.append(f"%{supplier}%")
        sql += " ORDER BY issue_date DESC NULLS LAST LIMIT ?"; params.append(min(int(limit), 500))
        return self.store.query(sql, params)

    def get_invoice(self, invoice_id: int) -> dict:
        """Détail d'une facture : en-tête, lignes et anomalies."""
        head = self.store.query("SELECT * FROM invoices WHERE id = ?", [invoice_id])
        if not head:
            return {"error": f"facture {invoice_id} inconnue"}
        return {"invoice": head[0],
                "lines": self.store.query("SELECT * FROM invoice_lines WHERE invoice_id = ? ORDER BY line_no", [invoice_id]),
                "issues": self.store.query("SELECT code, severity, message FROM issues WHERE invoice_id = ?", [invoice_id])}

    def review_queue(self) -> list[dict]:
        """Factures à contrôler par un humain, avec leurs anomalies, les plus graves d'abord."""
        return self.store.query(
            "SELECT i.id, i.source_file, i.invoice_number, i.seller_name, i.total_ttc, i.status, "
            "string_agg(s.code || ' : ' || s.message, ' | ') AS anomalies "
            "FROM invoices i JOIN issues s ON s.invoice_id = i.id AND s.severity IN ('error','warning') "
            "GROUP BY i.id, i.source_file, i.invoice_number, i.seller_name, i.total_ttc, i.status "
            "ORDER BY CASE i.status WHEN 'to_review' THEN 0 ELSE 1 END, i.total_ttc DESC NULLS LAST")

    def supplier_summary(self) -> list[dict]:
        """Synthèse par fournisseur : nombre de factures, montants, IBAN distincts, factures à revoir."""
        return self.store.query(
            "SELECT seller_name, count(*) AS nb_factures, sum(total_ht) AS total_ht, sum(total_ttc) AS total_ttc, "
            "count(DISTINCT seller_iban) AS nb_iban, count(*) FILTER (WHERE status = 'to_review') AS a_revoir "
            "FROM invoices WHERE seller_name IS NOT NULL GROUP BY seller_name ORDER BY total_ttc DESC")

    def query_sql(self, sql: str) -> list[dict] | dict:
        """Requête SQL DuckDB en lecture seule (SELECT / WITH) sur les tables
        invoices, invoice_lines et issues. Résultat limité à 200 lignes."""
        stmt = sql.strip().rstrip(";")
        if ";" in stmt or not re.match(r"^(select|with)\b", stmt, re.IGNORECASE) or FORBIDDEN.search(stmt):
            return {"error": "seules les requêtes SELECT/WITH simples sont autorisées"}
        return self.store.query(f"SELECT * FROM ({stmt}) LIMIT 200")


TOOL_NAMES = ["list_inbox", "process_invoice", "list_invoices", "get_invoice",
              "review_queue", "supplier_summary", "query_sql"]
