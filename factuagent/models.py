"""Schéma de données d'une facture, inspiré du profil EN 16931 / Factur-X."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class Party(BaseModel):
    name: str
    siren: str | None = Field(None, description="SIREN à 9 chiffres")
    vat_id: str | None = Field(None, description="N° de TVA intracommunautaire, ex. FR32123456789")
    address: str | None = None
    iban: str | None = None


class InvoiceLine(BaseModel):
    description: str
    quantity: Decimal
    unit_price: Decimal
    vat_rate: Decimal = Field(description="Taux en %, ex. 20")
    total_ht: Decimal


class Invoice(BaseModel):
    invoice_number: str
    issue_date: date
    due_date: date | None = None
    currency: str = "EUR"
    seller: Party
    buyer: Party
    lines: list[InvoiceLine] = Field(default_factory=list)
    total_ht: Decimal
    total_vat: Decimal
    total_ttc: Decimal


class Issue(BaseModel):
    code: str
    severity: Literal["info", "warning", "error"]
    message: str


class ProcessingResult(BaseModel):
    source_file: str
    method: Literal["facturx", "llm", "rules"]
    invoice: Invoice | None
    issues: list[Issue] = Field(default_factory=list)

    @property
    def status(self) -> str:
        if self.invoice is None or any(i.severity == "error" for i in self.issues):
            return "to_review"
        if any(i.severity == "warning" for i in self.issues):
            return "check"
        return "ok"
