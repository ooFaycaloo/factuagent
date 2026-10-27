"""Contrôles métier : identifiants français, IBAN, cohérence des montants."""
from __future__ import annotations

import re
from decimal import Decimal

from .models import Invoice, Issue

TOLERANCE = Decimal("0.02")


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def is_valid_siren(siren: str) -> bool:
    """SIREN : 9 chiffres, clé de Luhn."""
    s = _digits(siren)
    if len(s) != 9:
        return False
    total = 0
    for i, ch in enumerate(reversed(s)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def fr_vat_key(siren: str) -> int:
    return (12 + 3 * (int(_digits(siren)) % 97)) % 97


def make_fr_vat(siren: str) -> str:
    return f"FR{fr_vat_key(siren):02d}{_digits(siren)}"


def is_valid_fr_vat(vat: str, siren: str | None = None) -> bool:
    v = (vat or "").replace(" ", "").upper()
    m = re.fullmatch(r"FR(\d{2})(\d{9})", v)
    if not m:
        return False
    key, vsiren = int(m.group(1)), m.group(2)
    if key != fr_vat_key(vsiren):
        return False
    return siren is None or _digits(siren) == vsiren


def is_valid_iban(iban: str) -> bool:
    s = (iban or "").replace(" ", "").upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", s):
        return False
    rearranged = s[4:] + s[:4]
    num = "".join(str(int(c, 36)) for c in rearranged)
    return int(num) % 97 == 1


def validate(inv: Invoice) -> list[Issue]:
    issues: list[Issue] = []

    for role, party in (("vendeur", inv.seller), ("acheteur", inv.buyer)):
        if party.siren and not is_valid_siren(party.siren):
            issues.append(Issue(code="SIREN_INVALID", severity="error",
                                message=f"SIREN {role} invalide : {party.siren}"))
        if party.vat_id and party.vat_id.upper().startswith("FR") and not is_valid_fr_vat(party.vat_id, party.siren):
            issues.append(Issue(code="VAT_INVALID", severity="error",
                                message=f"N° TVA {role} incohérent : {party.vat_id}"))
    if not inv.seller.siren:
        issues.append(Issue(code="SIREN_MISSING", severity="warning", message="SIREN vendeur absent"))
    if inv.seller.iban and not is_valid_iban(inv.seller.iban):
        issues.append(Issue(code="IBAN_INVALID", severity="error",
                            message=f"IBAN vendeur invalide : {inv.seller.iban}"))

    if abs(inv.total_ht + inv.total_vat - inv.total_ttc) > TOLERANCE:
        issues.append(Issue(code="TOTALS_MISMATCH", severity="error",
                            message=f"HT + TVA ≠ TTC ({inv.total_ht} + {inv.total_vat} ≠ {inv.total_ttc})"))
    if inv.lines:
        lines_ht = sum((l.total_ht for l in inv.lines), Decimal(0))
        if abs(lines_ht - inv.total_ht) > TOLERANCE:
            issues.append(Issue(code="LINES_MISMATCH", severity="error",
                                message=f"Somme des lignes ({lines_ht}) ≠ total HT ({inv.total_ht})"))
        vat = sum((l.total_ht * l.vat_rate / 100 for l in inv.lines), Decimal(0))
        if abs(vat - inv.total_vat) > Decimal("0.05"):
            issues.append(Issue(code="VAT_AMOUNT_MISMATCH", severity="warning",
                                message=f"TVA recalculée {vat:.2f} ≠ TVA déclarée {inv.total_vat}"))
    if inv.due_date and inv.due_date < inv.issue_date:
        issues.append(Issue(code="DUE_BEFORE_ISSUE", severity="error",
                            message="Échéance antérieure à la date d'émission"))
    if inv.due_date and (inv.due_date - inv.issue_date).days > 60:
        issues.append(Issue(code="PAYMENT_TERMS", severity="warning",
                            message="Délai de paiement > 60 jours (art. L441-10 C. com.)"))
    return issues
