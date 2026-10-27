"""Lecture / écriture du XML CII (Cross Industry Invoice) embarqué dans un PDF Factur-X.

Note : un vrai Factur-X est un PDF/A-3 avec métadonnées XMP. Ici on embarque le
XML CII comme pièce jointe nommée « factur-x.xml », ce qui suffit pour la lecture
automatique ; la conformité PDF/A-3 complète relève d'outils dédiés.
"""
from __future__ import annotations

import io
from datetime import date, datetime
from decimal import Decimal

from lxml import etree
from pypdf import PdfReader, PdfWriter

from .models import Invoice, InvoiceLine, Party

NS = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
}
ATTACHMENT_NAME = "factur-x.xml"


def _q(prefix: str, tag: str) -> str:
    return f"{{{NS[prefix]}}}{tag}"


def _sub(parent, prefix, tag, text=None, **attrs):
    el = etree.SubElement(parent, _q(prefix, tag), **attrs)
    if text is not None:
        el.text = str(text)
    return el


def _date(parent, prefix, tag, d: date):
    w = _sub(parent, prefix, tag)
    _sub(w, "udt", "DateTimeString", d.strftime("%Y%m%d"), format="102")


def _party(parent, tag, p: Party):
    el = _sub(parent, "ram", tag)
    _sub(el, "ram", "Name", p.name)
    if p.siren:
        org = _sub(el, "ram", "SpecifiedLegalOrganization")
        _sub(org, "ram", "ID", p.siren, schemeID="0002")
    if p.address:
        addr = _sub(el, "ram", "PostalTradeAddress")
        _sub(addr, "ram", "LineOne", p.address)
        _sub(addr, "ram", "CountryID", "FR")
    if p.vat_id:
        tax = _sub(el, "ram", "SpecifiedTaxRegistration")
        _sub(tax, "ram", "ID", p.vat_id, schemeID="VA")


def build_cii_xml(inv: Invoice) -> bytes:
    root = etree.Element(_q("rsm", "CrossIndustryInvoice"), nsmap=NS)
    ctx = _sub(root, "rsm", "ExchangedDocumentContext")
    g = _sub(ctx, "ram", "GuidelineSpecifiedDocumentContextParameter")
    _sub(g, "ram", "ID", "urn:cen.eu:en16931:2017")

    doc = _sub(root, "rsm", "ExchangedDocument")
    _sub(doc, "ram", "ID", inv.invoice_number)
    _sub(doc, "ram", "TypeCode", "380")
    _date(doc, "ram", "IssueDateTime", inv.issue_date)

    tx = _sub(root, "rsm", "SupplyChainTradeTransaction")
    for i, line in enumerate(inv.lines, 1):
        li = _sub(tx, "ram", "IncludedSupplyChainTradeLineItem")
        _sub(_sub(li, "ram", "AssociatedDocumentLineDocument"), "ram", "LineID", i)
        _sub(_sub(li, "ram", "SpecifiedTradeProduct"), "ram", "Name", line.description)
        agr = _sub(li, "ram", "SpecifiedLineTradeAgreement")
        _sub(_sub(agr, "ram", "NetPriceProductTradePrice"), "ram", "ChargeAmount", line.unit_price)
        _sub(_sub(li, "ram", "SpecifiedLineTradeDelivery"), "ram", "BilledQuantity", line.quantity, unitCode="C62")
        st = _sub(li, "ram", "SpecifiedLineTradeSettlement")
        tax = _sub(st, "ram", "ApplicableTradeTax")
        _sub(tax, "ram", "TypeCode", "VAT")
        _sub(tax, "ram", "CategoryCode", "S")
        _sub(tax, "ram", "RateApplicablePercent", line.vat_rate)
        summ = _sub(st, "ram", "SpecifiedTradeSettlementLineMonetarySummation")
        _sub(summ, "ram", "LineTotalAmount", line.total_ht)

    agr = _sub(tx, "ram", "ApplicableHeaderTradeAgreement")
    _party(agr, "SellerTradeParty", inv.seller)
    _party(agr, "BuyerTradeParty", inv.buyer)
    _sub(tx, "ram", "ApplicableHeaderTradeDelivery")

    st = _sub(tx, "ram", "ApplicableHeaderTradeSettlement")
    _sub(st, "ram", "InvoiceCurrencyCode", inv.currency)
    if inv.seller.iban:
        pm = _sub(st, "ram", "SpecifiedTradeSettlementPaymentMeans")
        _sub(pm, "ram", "TypeCode", "58")
        _sub(_sub(pm, "ram", "PayeePartyCreditorFinancialAccount"), "ram", "IBANID", inv.seller.iban)
    if inv.due_date:
        terms = _sub(st, "ram", "SpecifiedTradePaymentTerms")
        _date(terms, "ram", "DueDateDateTime", inv.due_date)
    summ = _sub(st, "ram", "SpecifiedTradeSettlementHeaderMonetarySummation")
    _sub(summ, "ram", "TaxBasisTotalAmount", inv.total_ht)
    _sub(summ, "ram", "TaxTotalAmount", inv.total_vat, currencyID=inv.currency)
    _sub(summ, "ram", "GrandTotalAmount", inv.total_ttc)
    _sub(summ, "ram", "DuePayableAmount", inv.total_ttc)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def _text(el, path) -> str | None:
    found = el.find(path, NS)
    return found.text.strip() if found is not None and found.text else None


def _parse_date(el, path) -> date | None:
    s = _text(el, path)
    return datetime.strptime(s, "%Y%m%d").date() if s else None


def _parse_party(el) -> Party:
    return Party(
        name=_text(el, "ram:Name") or "",
        siren=_text(el, "ram:SpecifiedLegalOrganization/ram:ID"),
        vat_id=_text(el, "ram:SpecifiedTaxRegistration/ram:ID"),
        address=_text(el, "ram:PostalTradeAddress/ram:LineOne"),
    )


def parse_cii_xml(xml: bytes) -> Invoice:
    root = etree.fromstring(xml)
    doc = root.find("rsm:ExchangedDocument", NS)
    tx = root.find("rsm:SupplyChainTradeTransaction", NS)
    agr = tx.find("ram:ApplicableHeaderTradeAgreement", NS)
    st = tx.find("ram:ApplicableHeaderTradeSettlement", NS)
    summ = st.find("ram:SpecifiedTradeSettlementHeaderMonetarySummation", NS)

    seller = _parse_party(agr.find("ram:SellerTradeParty", NS))
    seller.iban = _text(st, "ram:SpecifiedTradeSettlementPaymentMeans/ram:PayeePartyCreditorFinancialAccount/ram:IBANID")

    lines = []
    for li in tx.findall("ram:IncludedSupplyChainTradeLineItem", NS):
        lines.append(InvoiceLine(
            description=_text(li, "ram:SpecifiedTradeProduct/ram:Name") or "",
            quantity=Decimal(_text(li, "ram:SpecifiedLineTradeDelivery/ram:BilledQuantity")),
            unit_price=Decimal(_text(li, "ram:SpecifiedLineTradeAgreement/ram:NetPriceProductTradePrice/ram:ChargeAmount")),
            vat_rate=Decimal(_text(li, "ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax/ram:RateApplicablePercent")),
            total_ht=Decimal(_text(li, "ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeSettlementLineMonetarySummation/ram:LineTotalAmount")),
        ))

    return Invoice(
        invoice_number=_text(doc, "ram:ID"),
        issue_date=_parse_date(doc, "ram:IssueDateTime/udt:DateTimeString"),
        due_date=_parse_date(st, "ram:SpecifiedTradePaymentTerms/ram:DueDateDateTime/udt:DateTimeString"),
        currency=_text(st, "ram:InvoiceCurrencyCode") or "EUR",
        seller=seller,
        buyer=_parse_party(agr.find("ram:BuyerTradeParty", NS)),
        lines=lines,
        total_ht=Decimal(_text(summ, "ram:TaxBasisTotalAmount")),
        total_vat=Decimal(_text(summ, "ram:TaxTotalAmount")),
        total_ttc=Decimal(_text(summ, "ram:GrandTotalAmount")),
    )


def embed_xml(pdf_bytes: bytes, xml: bytes) -> bytes:
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf_bytes)))
    writer.add_attachment(ATTACHMENT_NAME, xml)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def extract_xml(pdf_path: str) -> bytes | None:
    reader = PdfReader(pdf_path)
    for name, contents in (reader.attachments or {}).items():
        if name.lower() in (ATTACHMENT_NAME, "zugferd-invoice.xml", "xrechnung.xml"):
            return contents[0]
    return None
