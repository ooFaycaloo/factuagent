"""Pipeline : PDF → (Factur-X | LLM | règles) → validation → détection d'anomalies → DuckDB."""
from __future__ import annotations

import statistics
from pathlib import Path

from .extractors import LLMExtractor, RulesExtractor, llm_available, pdf_text
from .facturx import extract_xml, parse_cii_xml
from .models import Invoice, Issue, ProcessingResult
from .store import Store
from .validators import validate


def detect_anomalies(inv: Invoice, store: Store) -> list[Issue]:
    issues = []
    dup = store.find_duplicate(inv.seller.siren, inv.seller.name, inv.invoice_number)
    if dup:
        issues.append(Issue(code="DUPLICATE", severity="error",
                            message=f"Facture {inv.invoice_number} déjà enregistrée (id {dup})"))
    known = store.known_ibans(inv.seller.siren, inv.seller.name)
    if inv.seller.iban and known and inv.seller.iban not in known:
        issues.append(Issue(code="IBAN_CHANGED", severity="error",
                            message="IBAN différent de celui connu pour ce fournisseur : "
                                    "possible fraude au changement de RIB, à confirmer par téléphone"))
    history = store.supplier_amounts(inv.seller.siren, inv.seller.name)
    if len(history) >= 3:
        med = statistics.median(history)
        if med and float(inv.total_ttc) > 4 * med:
            issues.append(Issue(code="AMOUNT_OUTLIER", severity="warning",
                                message=f"Montant {inv.total_ttc} € > 4× la médiane du fournisseur ({med:.0f} €)"))
    return issues


class Pipeline:
    def __init__(self, store: Store, use_llm: bool | None = None):
        self.store = store
        self.rules = RulesExtractor()
        self.use_llm = llm_available() if use_llm is None else use_llm
        self.llm = LLMExtractor() if self.use_llm else None

    def extract(self, path: str) -> tuple[Invoice | None, str, list[Issue]]:
        xml = extract_xml(path)
        if xml:
            return parse_cii_xml(xml), "facturx", []
        text = pdf_text(path)
        if self.llm:
            try:
                return self.llm.extract(text), "llm", []
            except Exception as e:  # on retombe sur les règles plutôt que d'échouer
                fallback = [Issue(code="LLM_ERROR", severity="info", message=str(e)[:200])]
        else:
            fallback = []
        try:
            return self.rules.extract(text), "rules", fallback
        except Exception as e:
            return None, "rules", fallback + [Issue(code="EXTRACTION_FAILED", severity="error",
                                                    message=f"Extraction impossible : {e}")]

    def process(self, path: str | Path, save: bool = True) -> ProcessingResult:
        path = str(path)
        inv, method, issues = self.extract(path)
        if inv is not None:
            issues += validate(inv)
            issues += detect_anomalies(inv, self.store)
        result = ProcessingResult(source_file=Path(path).name, method=method, invoice=inv, issues=issues)
        if save:
            self.store.save(result)
        return result
