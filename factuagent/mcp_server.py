"""Serveur MCP : expose les factures à n'importe quel client MCP (Claude Desktop, Claude Code, IDE…).

Lancement : python -m factuagent.mcp_server
"""
from __future__ import annotations

import json

from mcp.server.mcpserver import MCPServer

from .tools import InvoiceTools

tools = InvoiceTools()
server = MCPServer(
    name="factuagent",
    instructions=(
        "Outils de traitement et d'analyse de factures fournisseurs. "
        "Utilise review_queue pour les factures à contrôler, supplier_summary pour une vue par fournisseur, "
        "query_sql pour toute analyse ad hoc (tables : invoices, invoice_lines, issues). "
        "Ne valide jamais un paiement : signale les anomalies à l'utilisateur."
    ),
)


def _dump(x) -> str:
    return json.dumps(x, default=str, ensure_ascii=False)


@server.tool()
def list_inbox() -> str:
    """Liste les PDF présents dans la boîte de réception des factures."""
    return _dump(tools.list_inbox())


@server.tool()
def process_invoice(filename: str) -> str:
    """Traite une facture PDF de la boîte de réception et renvoie champs, statut et anomalies."""
    return _dump(tools.process_invoice(filename))


@server.tool()
def list_invoices(status: str | None = None, supplier: str | None = None, limit: int = 50) -> str:
    """Liste les factures traitées. status : ok, check ou to_review. supplier : recherche partielle."""
    return _dump(tools.list_invoices(status, supplier, limit))


@server.tool()
def get_invoice(invoice_id: int) -> str:
    """Détail d'une facture : en-tête, lignes, anomalies."""
    return _dump(tools.get_invoice(invoice_id))


@server.tool()
def review_queue() -> str:
    """Factures à contrôler par un humain, avec leurs anomalies."""
    return _dump(tools.review_queue())


@server.tool()
def supplier_summary() -> str:
    """Synthèse par fournisseur : volumes, montants, nombre d'IBAN distincts, factures à revoir."""
    return _dump(tools.supplier_summary())


@server.tool()
def query_sql(sql: str) -> str:
    """Requête SQL DuckDB en lecture seule sur invoices, invoice_lines, issues (200 lignes max)."""
    return _dump(tools.query_sql(sql))


if __name__ == "__main__":
    server.run("stdio")
