# Rapport d'évaluation — règles + Factur-X (sans LLM)

- Factures évaluées : **41**
- Précision globale par champ : **95.1%** (468/492)
- Anomalies : rappel **100%** (7/7), précision **88%** (1 fausse(s) alerte(s))

## Par méthode d'extraction

| Méthode | Précision champs |
|---|---|
| facturx | 100.0% |
| rules | 93.5% |

## Par mise en page

| Mise en page | Précision champs |
|---|---|
| classic | 100.0% |
| letter | 0.0% |
| siret | 100.0% |

## Par champ

| Champ | Précision |
|---|---|
| invoice_number | 95.1% |
| issue_date | 95.1% |
| due_date | 95.1% |
| seller.name | 95.1% |
| seller.siren | 95.1% |
| seller.vat_id | 95.1% |
| seller.iban | 95.1% |
| buyer.name | 95.1% |
| total_ht | 95.1% |
| total_vat | 95.1% |
| total_ttc | 95.1% |
| n_lines | 95.1% |

## Détail

| Fichier | Méthode | Statut | Champs OK | Anomalie attendue | Détectée | Fausse alerte |
|---|---|---|---|---|---|---|
| 001_classic.pdf | rules | ok | 12/12 | - | - |  |
| 002_siret.pdf | rules | ok | 12/12 | - | - |  |
| 003_classic_facturx.pdf | facturx | ok | 12/12 | - | - |  |
| 004_siret_facturx.pdf | facturx | ok | 12/12 | - | - |  |
| 005_classic.pdf | rules | ok | 12/12 | - | - |  |
| 006_classic.pdf | rules | ok | 12/12 | - | - |  |
| 007_siret.pdf | rules | ok | 12/12 | - | - |  |
| 008_siret.pdf | rules | ok | 12/12 | - | - |  |
| 009_siret.pdf | rules | ok | 12/12 | - | - |  |
| 010_siret.pdf | rules | ok | 12/12 | - | - |  |
| 011_letter.pdf | rules | to_review | 0/12 | - | - |  |
| 012_classic.pdf | rules | ok | 12/12 | - | - |  |
| 013_siret.pdf | rules | ok | 12/12 | - | - |  |
| 014_classic.pdf | rules | ok | 12/12 | - | - |  |
| 015_classic.pdf | rules | ok | 12/12 | - | - |  |
| 016_classic.pdf | rules | ok | 12/12 | - | - |  |
| 017_classic.pdf | rules | ok | 12/12 | - | - |  |
| 018_siret.pdf | rules | ok | 12/12 | - | - |  |
| 019_classic.pdf | rules | ok | 12/12 | - | - |  |
| 020_classic_facturx.pdf | facturx | ok | 12/12 | - | - |  |
| 021_classic_facturx.pdf | facturx | ok | 12/12 | - | - |  |
| 022_siret.pdf | rules | ok | 12/12 | - | - |  |
| 023_letter.pdf | rules | to_review | 0/12 | - | - |  |
| 024_classic_facturx.pdf | facturx | ok | 12/12 | - | - |  |
| 025_classic.pdf | rules | ok | 12/12 | - | - |  |
| 026_classic_facturx.pdf | facturx | ok | 12/12 | - | - |  |
| 027_siret.pdf | rules | ok | 12/12 | - | - |  |
| 028_siret.pdf | rules | ok | 12/12 | - | - |  |
| 029_classic.pdf | rules | ok | 12/12 | - | - |  |
| 030_siret.pdf | rules | ok | 12/12 | - | - |  |
| 031_classic.pdf | rules | ok | 12/12 | - | - |  |
| 032_classic.pdf | rules | to_review | 12/12 | TOTALS_MISMATCH | TOTALS_MISMATCH |  |
| 033_siret_facturx.pdf | facturx | to_review | 12/12 | SIREN_INVALID | SIREN_INVALID,VAT_INVALID |  |
| 034_classic.pdf | rules | to_review | 12/12 | IBAN_CHANGED | IBAN_CHANGED |  |
| 035_classic.pdf | rules | check | 12/12 | PAYMENT_TERMS | PAYMENT_TERMS |  |
| 036_classic.pdf | rules | to_review | 12/12 | TOTALS_MISMATCH | TOTALS_MISMATCH |  |
| 037_classic.pdf | rules | to_review | 12/12 | IBAN_CHANGED | IBAN_CHANGED |  |
| 038_classic.pdf | rules | ok | 12/12 | - | - |  |
| 039_siret_facturx.pdf | facturx | ok | 12/12 | - | - |  |
| 040_siret_facturx.pdf | facturx | check | 12/12 | - | AMOUNT_OUTLIER | AMOUNT_OUTLIER |
| 041_doublon_021_classic_facturx.pdf | facturx | to_review | 12/12 | DUPLICATE | DUPLICATE |  |
