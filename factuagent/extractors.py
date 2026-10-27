"""Extraction des champs d'une facture PDF « classique » (sans XML embarqué).

Deux stratégies :
- RulesExtractor : expressions régulières, rapide et gratuit, couvre les mises en page connues ;
- LLMExtractor   : Claude via tool use avec un schéma JSON strict, généralise aux mises en page inconnues.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import pdfplumber

from .models import Invoice, InvoiceLine, Party

MONTHS = {m: i for i, m in enumerate(
    ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
     "août", "septembre", "octobre", "novembre", "décembre"], 1)}


def pdf_text(path: str) -> str:
    with pdfplumber.open(path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def parse_amount(s: str) -> Decimal | None:
    s = s.replace(" ", "").replace("\xa0", "").replace(" ", "").replace("€", "").replace("EUR", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def parse_date(s: str) -> date | None:
    s = s.strip().lower()
    for fmt in ("%d/%m/%Y", "%d.%m.%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    m = re.match(r"(\d{1,2})(?:er)?\s+([a-zéû]+)\s+(\d{4})", s)
    if m and m.group(2) in MONTHS:
        return date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))
    return None


AMOUNT = r"([\d][\d\s \xa0]*[.,]\d{2})"
DATE = r"(\d{2}[/.\-]\d{2}[/.\-]\d{4}|\d{1,2}(?:er)?\s+[a-zéû]+\s+\d{4})"


def _find(pattern: str, text: str, flags=re.IGNORECASE) -> str | None:
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else None


def _party_block(block: str, name_hint: str | None) -> Party:
    siren = _find(r"(?:SIREN|SIRET|immatricul\w+ sous le n°)\s*:?\s*(\d{9})", block)
    vat = _find(r"(?:TVA|intracom\.?)\s*[^\n:]*?:?\s*(FR\s?\d{2}\s?\d{9})", block)
    iban = _find(r"IBAN\s*:?\s*([A-Z]{2}\d{2}(?:\s?[A-Z0-9]){10,30})", block, 0)
    lines = [l.strip() for l in block.splitlines() if l.strip()]
    address = next((l for l in lines if re.search(r"\b\d{5}\b", l) and not re.search(r"SIRE|TVA", l)), None)
    return Party(name=name_hint or (lines[0] if lines else ""), siren=siren,
                 vat_id=vat.replace(" ", "") if vat else None,
                 address=address.split(" - ")[0] if address else None,
                 iban=iban.replace(" ", "") if iban else None)


class RulesExtractor:
    name = "rules"

    def extract(self, text: str) -> Invoice:
        # séparation vendeur / acheteur
        split = re.split(r"\n(?:Facturé à\s*:|Client\s*:)", text, maxsplit=1)
        seller_txt = split[0]
        buyer_txt = split[1] if len(split) > 1 else ""
        seller_name = _find(r"Émetteur\s*:\s*(.+)", seller_txt)
        buyer_lines = [l for l in buyer_txt.splitlines() if l.strip()]
        buyer_name = buyer_lines[0].strip() if buyer_lines else None
        buyer_block = "\n".join(buyer_lines[:4])

        seller = _party_block(seller_txt, seller_name)
        iban = _find(r"IBAN\s*:?\s*([A-Z]{2}\d{2}(?:\s?[A-Z0-9]){10,30})", text, 0)
        seller.iban = iban.replace(" ", "") if iban else None
        buyer = _party_block(buyer_block, buyer_name) if buyer_name else Party(name="")

        number = _find(r"Facture\s+n[°o]\s*:?\s*([A-Z0-9][\w/\-]+)", text)
        issue = _find(r"(?:Date d'émission|émise le|Date de facture)\s*:?\s*" + DATE, text)
        due = _find(r"(?:Échéance|Date limite de paiement|à régler avant le)\s*:?\s*" + DATE, text)

        ht = _find(r"(?:Total|Montant)\s+HT\s*:?\s*" + AMOUNT, text)
        vat_amt = _find(r"(?:Montant TVA|TVA\s+\d+(?:[.,]\d+)?\s*%)\s*:?\s*" + AMOUNT, text)
        ttc = _find(r"(?:Total TTC|Net à payer)\s*:?\s*" + AMOUNT, text)

        lines = []
        for m in re.finditer(r"^(.+?)\s*\|?\s+(\d+(?:[.,]\d+)?)\s*\|?\s+(\d+[.,]\d{2})\s*\|?\s+"
                             r"(\d+(?:[.,]\d+)?)\s*%\s*\|?\s+(\d+[.,]\d{2})\s*$", text, re.MULTILINE):
            desc = m.group(1).strip(" |")
            if desc.lower().startswith(("description", "désignation")):
                continue
            lines.append(InvoiceLine(description=desc, quantity=parse_amount(m.group(2)),
                                     unit_price=parse_amount(m.group(3)), vat_rate=parse_amount(m.group(4)),
                                     total_ht=parse_amount(m.group(5))))

        if not (number and issue and ht and ttc):
            raise ValueError("mise en page non reconnue par les règles")
        total_ht, total_ttc = parse_amount(ht), parse_amount(ttc)
        total_vat = parse_amount(vat_amt) if vat_amt else total_ttc - total_ht
        return Invoice(invoice_number=number, issue_date=parse_date(issue),
                       due_date=parse_date(due) if due else None, seller=seller, buyer=buyer,
                       lines=lines, total_ht=total_ht, total_vat=total_vat, total_ttc=total_ttc)


# ------------------------------------------------------------------ LLM

SYSTEM = """Tu es un moteur d'extraction de factures françaises.
Extrais exactement ce qui est écrit dans le document, sans rien inventer.
- Montants en nombres décimaux (point décimal), dates au format AAAA-MM-JJ.
- SIREN : les 9 premiers chiffres (si seul un SIRET de 14 chiffres figure, prends ses 9 premiers).
- Si un champ est absent du document, renvoie null.
- Les lignes de facture peuvent être décrites en texte libre : décompose-les si quantité et prix sont donnés, sinon laisse la liste vide."""


def _invoice_tool_schema() -> dict:
    schema = Invoice.model_json_schema()
    return {"name": "record_invoice", "description": "Enregistre les champs extraits de la facture.",
            "input_schema": schema}


class LLMExtractor:
    name = "llm"

    def __init__(self, model: str | None = None):
        import anthropic  # import paresseux : dépendance optionnelle

        self.client = anthropic.Anthropic()
        self.model = model or os.environ.get("FACTUAGENT_MODEL", "claude-haiku-5-5")

    def extract(self, text: str) -> Invoice:
        resp = self.client.messages.create(
            model=self.model, max_tokens=2000, system=SYSTEM,
            tools=[_invoice_tool_schema()], tool_choice={"type": "tool", "name": "record_invoice"},
            messages=[{"role": "user", "content": f"<document>\n{text}\n</document>"}],
        )
        block = next(b for b in resp.content if b.type == "tool_use")
        return Invoice.model_validate(block.input)


def llm_available() -> bool:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
        return True
    except ImportError:
        return False


if __name__ == "__main__":  # debug rapide : python -m factuagent.extractors fichier.pdf
    import sys

    print(json.dumps(json.loads(RulesExtractor().extract(pdf_text(sys.argv[1])).model_dump_json()),
                     indent=2, ensure_ascii=False))
