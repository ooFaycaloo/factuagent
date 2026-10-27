import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from factuagent.extractors import parse_amount, parse_date  # noqa: E402
from factuagent.facturx import build_cii_xml, parse_cii_xml  # noqa: E402
from factuagent.models import Invoice, InvoiceLine, Party  # noqa: E402
from factuagent.tools import InvoiceTools  # noqa: E402
from factuagent.validators import (is_valid_fr_vat, is_valid_iban, is_valid_siren,  # noqa: E402
                                   make_fr_vat, validate)


def sample_invoice(**kw) -> Invoice:
    base = dict(
        invoice_number="T-001", issue_date=date(2026, 9, 1), due_date=date(2026, 10, 1),
        seller=Party(name="Vendeur", siren="552081317", vat_id=make_fr_vat("552081317"),
                     iban="FR7630006000011234567890189"),
        buyer=Party(name="Acheteur"),
        lines=[InvoiceLine(description="Conseil", quantity=Decimal(2), unit_price=Decimal("500.00"),
                           vat_rate=Decimal(20), total_ht=Decimal("1000.00"))],
        total_ht=Decimal("1000.00"), total_vat=Decimal("200.00"), total_ttc=Decimal("1200.00"))
    base.update(kw)
    return Invoice(**base)


# --------------------------------------------------------------- identifiants

def test_siren_luhn():
    assert is_valid_siren("552081317")
    assert not is_valid_siren("552081318")
    assert not is_valid_siren("12345")


def test_vat_key():
    assert make_fr_vat("552081317") == "FR03552081317"
    assert is_valid_fr_vat("FR03552081317", "552081317")
    assert not is_valid_fr_vat("FR04552081317")
    assert not is_valid_fr_vat("FR03552081317", "123456782")


def test_iban():
    assert is_valid_iban("FR76 3000 6000 0112 3456 7890 189")
    assert not is_valid_iban("FR76 3000 6000 0112 3456 7890 188")


# --------------------------------------------------------------- parsing

@pytest.mark.parametrize("raw,expected", [
    ("1 234,50", "1234.50"), ("1234.50", "1234.50"), ("1.234,50 €", "1234.50"),
    ("12 345,00", "12345.00"), ("2 340.00 EUR", "2340.00")])
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == Decimal(expected)


@pytest.mark.parametrize("raw,expected", [
    ("15/09/2026", date(2026, 9, 15)), ("3 septembre 2026", date(2026, 9, 3)),
    ("1er août 2026", date(2026, 8, 1)), ("2026-09-14", date(2026, 9, 14))])
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


def test_facturx_roundtrip():
    inv = sample_invoice()
    back = parse_cii_xml(build_cii_xml(inv))
    assert back.seller == inv.seller
    assert back.lines == inv.lines
    assert (back.invoice_number, back.issue_date, back.due_date) == (inv.invoice_number, inv.issue_date, inv.due_date)
    assert (back.total_ht, back.total_vat, back.total_ttc) == (inv.total_ht, inv.total_vat, inv.total_ttc)


# --------------------------------------------------------------- règles métier

def test_valid_invoice_has_no_issue():
    assert validate(sample_invoice()) == []


def test_totals_mismatch():
    codes = {i.code for i in validate(sample_invoice(total_ttc=Decimal("1300.00")))}
    assert "TOTALS_MISMATCH" in codes


def test_payment_terms_and_due_date():
    codes = {i.code for i in validate(sample_invoice(due_date=date(2026, 12, 15)))}
    assert "PAYMENT_TERMS" in codes
    codes = {i.code for i in validate(sample_invoice(due_date=date(2026, 8, 1)))}
    assert "DUE_BEFORE_ISSUE" in codes


# --------------------------------------------------------------- bout en bout

@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    d = tmp_path_factory.mktemp("demo")
    subprocess.run([sys.executable, str(ROOT / "scripts/generate_invoices.py"), "--out", str(d / "inv"),
                    "--n", "40"], check=True, capture_output=True)
    tools = InvoiceTools(db_path=str(d / "t.duckdb"), inbox=str(d / "inv"))
    results = {name: tools.process_invoice(name) for name in tools.list_inbox()}
    return tools, results


def test_pipeline_detects_injected_anomalies(demo):
    _, results = demo
    codes = {c for r in results.values() for c in (i["code"] for i in r["issues"])}
    for expected in ("TOTALS_MISMATCH", "SIREN_INVALID", "IBAN_CHANGED", "PAYMENT_TERMS", "DUPLICATE"):
        assert expected in codes


def test_facturx_files_use_xml(demo):
    _, results = demo
    assert all(r["method"] == "facturx" for n, r in results.items() if "facturx" in n)


def test_sql_tool_is_read_only(demo):
    tools, _ = demo
    assert isinstance(tools.query_sql("SELECT count(*) AS n FROM invoices"), list)
    for bad in ("DELETE FROM invoices", "SELECT 1; DROP TABLE invoices", "COPY invoices TO 'x.csv'",
                "SELECT * FROM read_csv('/etc/passwd')"):
        assert "error" in tools.query_sql(bad)


def test_review_queue_and_suppliers(demo):
    tools, _ = demo
    queue = tools.review_queue()
    assert queue and queue[0]["status"] == "to_review"
    summary = tools.supplier_summary()
    assert any(row["nb_iban"] > 1 for row in summary)  # le changement d'IBAN est visible


def test_process_invoice_rejects_path_traversal(demo):
    tools, _ = demo
    assert "error" in tools.process_invoice("../../etc/passwd")
