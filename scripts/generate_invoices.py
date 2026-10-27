"""Génère un jeu de factures de démonstration (PDF) avec leur vérité terrain.

- 3 mises en page différentes (tableau classique, format « SIRET », facture rédigée)
- une partie au format Factur-X (XML CII embarqué)
- des anomalies injectées : totaux faux, SIREN invalide, doublon,
  changement d'IBAN fournisseur (signal de fraude), délai de paiement abusif

Usage : python scripts/generate_invoices.py --out data/invoices --n 40
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from factuagent.facturx import build_cii_xml, embed_xml  # noqa: E402
from factuagent.models import Invoice, InvoiceLine, Party  # noqa: E402
from factuagent.validators import make_fr_vat  # noqa: E402

MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
          "août", "septembre", "octobre", "novembre", "décembre"]

SERVICES = [
    ("Audit de la qualité des données", 850), ("Développement pipeline dbt", 650),
    ("Maintenance serveur mensuelle", 320), ("Licence logiciel (mois)", 89),
    ("Intégration API ERP", 720), ("Formation équipe (jour)", 1200),
    ("Câble réseau Cat6 (rouleau)", 145), ("Borne de recharge 22 kW", 2390),
    ("Installation électrique (heure)", 68), ("Hébergement cloud (mois)", 240),
    ("Ramette papier A4", 6), ("Cartouche toner", 79),
]


def q2(x) -> Decimal:
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def luhn_siren(rng: random.Random) -> str:
    base = [rng.randint(0, 9) for _ in range(8)]
    base[0] = rng.randint(1, 9)
    for check in range(10):
        digits = base + [check]
        total = 0
        for i, d in enumerate(reversed(digits)):
            if i % 2 == 1:
                d *= 2
                d = d - 9 if d > 9 else d
            total += d
        if total % 10 == 0:
            return "".join(map(str, digits))
    raise RuntimeError


def make_iban(rng: random.Random) -> str:
    bban = "".join(str(rng.randint(0, 9)) for _ in range(23))
    num = int("".join(str(int(c, 36)) for c in bban + "FR00"))
    key = 98 - num % 97
    return f"FR{key:02d}{bban}"


def fmt_fr(x: Decimal) -> str:
    s = f"{x:,.2f}".replace(",", " ").replace(".", ",")
    return s


def fmt_iban(iban: str) -> str:
    return " ".join(iban[i:i + 4] for i in range(0, len(iban), 4))


def make_suppliers(rng):
    names = ["Datalys Conseil", "Volta Réseaux", "Nordica Cloud", "Atelier Pixel & Code",
             "ElecPro Services", "BuroPlus Fournitures", "Kinetik Énergie", "Orbis Formation"]
    cities = ["12 rue de la Paix, 75002 Paris", "4 avenue Jean Jaurès, 92000 Nanterre",
              "88 bd Haussmann, 75008 Paris", "3 place Bellecour, 69002 Lyon",
              "27 rue Nationale, 59000 Lille", "15 quai des Chartrons, 33000 Bordeaux",
              "9 rue Paradis, 13001 Marseille", "41 rue du Faubourg, 67000 Strasbourg"]
    out = []
    for name, addr in zip(names, cities):
        siren = luhn_siren(rng)
        out.append(Party(name=name, siren=siren, vat_id=make_fr_vat(siren), address=addr, iban=make_iban(rng)))
    return out


BUYER_SIREN = "552081317"  # fictif mais valide au sens de la clé de Luhn
BUYER = Party(name="Ville Lumière Mobilités SAS", siren=BUYER_SIREN, vat_id=make_fr_vat(BUYER_SIREN),
              address="1 parvis de la Défense, 92800 Puteaux")


def make_invoice(rng, supplier: Party, idx: int) -> Invoice:
    issue = date(2026, 9, 1) + timedelta(days=rng.randint(0, 50))
    lines = []
    for desc, base in rng.sample(SERVICES, rng.randint(1, 4)):
        qty = Decimal(rng.randint(1, 12))
        unit = q2(base * rng.uniform(0.9, 1.15))
        lines.append(InvoiceLine(description=desc, quantity=qty, unit_price=unit,
                                 vat_rate=Decimal(20), total_ht=q2(qty * unit)))
    ht = q2(sum(l.total_ht for l in lines))
    vat = q2(ht * Decimal("0.20"))
    prefix = "".join(w[0] for w in supplier.name.split()[:2]).upper()
    return Invoice(invoice_number=f"{prefix}-2026-{idx:04d}", issue_date=issue,
                   due_date=issue + timedelta(days=30), seller=supplier.model_copy(),
                   buyer=BUYER, lines=lines, total_ht=ht, total_vat=vat, total_ttc=ht + vat)


# ---------------------------------------------------------------- rendus PDF

def _new_canvas(path):
    c = canvas.Canvas(str(path), pagesize=A4)
    return c, A4[1] - 25 * mm


def render_classic(inv: Invoice, path: Path):
    """Mise en page A : tableau classique, montants au format français."""
    c, y = _new_canvas(path)
    x = 20 * mm
    c.setFont("Helvetica-Bold", 16); c.drawString(x, y, inv.seller.name); y -= 7 * mm
    c.setFont("Helvetica", 9)
    c.drawString(x, y, inv.seller.address); y -= 5 * mm
    c.drawString(x, y, f"SIREN : {inv.seller.siren}  -  TVA : {inv.seller.vat_id}"); y -= 12 * mm
    c.setFont("Helvetica-Bold", 14); c.drawString(x, y, f"FACTURE N° {inv.invoice_number}"); y -= 7 * mm
    c.setFont("Helvetica", 10)
    c.drawString(x, y, f"Date d'émission : {inv.issue_date:%d/%m/%Y}"); y -= 5 * mm
    c.drawString(x, y, f"Échéance : {inv.due_date:%d/%m/%Y}"); y -= 10 * mm
    c.setFont("Helvetica-Bold", 10); c.drawString(x, y, "Facturé à :"); y -= 5 * mm
    c.setFont("Helvetica", 10)
    c.drawString(x, y, inv.buyer.name); y -= 5 * mm
    c.drawString(x, y, inv.buyer.address); y -= 5 * mm
    c.drawString(x, y, f"SIREN : {inv.buyer.siren}  -  TVA : {inv.buyer.vat_id}"); y -= 12 * mm
    c.setFont("Helvetica-Bold", 9)
    cols = [x, x + 85 * mm, x + 100 * mm, x + 125 * mm, x + 145 * mm]
    for cx, h in zip(cols, ["Description", "Qté", "PU HT", "TVA", "Total HT"]):
        c.drawString(cx, y, h)
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    for l in inv.lines:
        vals = [l.description, f"{l.quantity}", f"{l.unit_price:.2f}".replace(".", ","),
                f"{l.vat_rate}%", f"{l.total_ht:.2f}".replace(".", ",")]
        for cx, v in zip(cols, vals):
            c.drawString(cx, y, v)
        y -= 5 * mm
    y -= 8 * mm
    for label, amount in (("Total HT", inv.total_ht), ("TVA 20 %", inv.total_vat), ("Total TTC", inv.total_ttc)):
        c.setFont("Helvetica-Bold" if label == "Total TTC" else "Helvetica", 10)
        c.drawString(x + 100 * mm, y, f"{label} : {fmt_fr(amount)} €"); y -= 6 * mm
    y -= 10 * mm
    c.setFont("Helvetica", 9)
    c.drawString(x, y, f"Règlement par virement - IBAN : {fmt_iban(inv.seller.iban)}")
    c.save()


def render_siret(inv: Invoice, path: Path):
    """Mise en page B : SIRET, dates en toutes lettres, montants à l'anglaise."""
    c, y = _new_canvas(path)
    x = 20 * mm

    def long_date(d):
        return f"{d.day} {MONTHS[d.month - 1]} {d.year}"

    c.setFont("Helvetica-Bold", 20); c.drawString(x, y, "Facture"); y -= 10 * mm
    c.setFont("Helvetica", 10)
    for line in (f"Émetteur : {inv.seller.name}", inv.seller.address,
                 f"SIRET : {inv.seller.siren}000{random.Random(inv.invoice_number).randint(10, 99)}",
                 f"N° TVA intracom. : {inv.seller.vat_id}", "",
                 f"Client : {inv.buyer.name}", inv.buyer.address, f"SIRET : {inv.buyer.siren}00011", "",
                 f"Facture n° {inv.invoice_number} émise le {long_date(inv.issue_date)}",
                 f"Date limite de paiement : {long_date(inv.due_date)}", ""):
        c.drawString(x, y, line); y -= 5.5 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x, y, "Désignation | Quantité | Prix unitaire | TVA | Montant HT"); y -= 6 * mm
    c.setFont("Helvetica", 9)
    for l in inv.lines:
        c.drawString(x, y, f"{l.description} | {l.quantity} | {l.unit_price:.2f} | {l.vat_rate}% | {l.total_ht:.2f}")
        y -= 5 * mm
    y -= 6 * mm
    c.setFont("Helvetica", 10)
    c.drawString(x, y, f"Montant HT : {inv.total_ht:.2f} EUR"); y -= 5.5 * mm
    c.drawString(x, y, f"Montant TVA : {inv.total_vat:.2f} EUR"); y -= 5.5 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(x, y, f"Net à payer : {inv.total_ttc:.2f} EUR"); y -= 10 * mm
    c.setFont("Helvetica", 9)
    c.drawString(x, y, f"Coordonnées bancaires : IBAN {inv.seller.iban}")
    c.save()


def render_letter(inv: Invoice, path: Path):
    """Mise en page C : facture rédigée façon courrier (petit artisan). Difficile pour des règles."""
    c, y = _new_canvas(path)
    x = 20 * mm
    c.setFont("Helvetica-Bold", 13); c.drawString(x, y, inv.seller.name.upper()); y -= 6 * mm
    c.setFont("Helvetica", 10)
    c.drawString(x, y, f"{inv.seller.address} - entreprise immatriculée sous le n° {inv.seller.siren}"); y -= 12 * mm
    c.drawString(x, y, f"À l'attention de {inv.buyer.name}, {inv.buyer.address}"); y -= 10 * mm
    c.drawString(x, y, f"Paris, le {inv.issue_date:%d.%m.%Y}"); y -= 10 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x, y, f"Objet : notre note d'honoraires réf. {inv.invoice_number}"); y -= 10 * mm
    c.setFont("Helvetica", 10)
    body = (f"Madame, Monsieur, suite à nos interventions ({', '.join(l.description.lower() for l in inv.lines)}), "
            f"nous vous prions de bien vouloir régler la somme de {fmt_fr(inv.total_ht)} euros hors taxes, "
            f"augmentée de la TVA au taux normal ({fmt_fr(inv.total_vat)} euros), "
            f"soit {fmt_fr(inv.total_ttc)} euros, avant le {inv.due_date:%d.%m.%Y}, "
            f"par virement sur notre compte {fmt_iban(inv.seller.iban)}. "
            f"Notre identifiant de TVA est {inv.seller.vat_id}.")
    words, line = body.split(), ""
    for w in words:
        if c.stringWidth(line + " " + w, "Helvetica", 10) > 170 * mm:
            c.drawString(x, y, line); y -= 5.5 * mm; line = w
        else:
            line = f"{line} {w}".strip()
    c.drawString(x, y, line); y -= 12 * mm
    c.drawString(x, y, "Veuillez agréer nos salutations distinguées.")
    c.save()


RENDERERS = {"classic": render_classic, "siret": render_siret, "letter": render_letter}


# ---------------------------------------------------------------- anomalies

def inject(rng, inv: Invoice, kind: str, suppliers) -> Invoice:
    inv = inv.model_copy(deep=True)
    if kind == "TOTALS_MISMATCH":
        inv.total_ttc += Decimal(rng.choice([10, 100, 250]))
    elif kind == "SIREN_INVALID":
        s = list(inv.seller.siren)
        s[4] = str((int(s[4]) + 3) % 10)
        inv.seller.siren = "".join(s)
    elif kind == "IBAN_CHANGED":
        inv.seller.iban = make_iban(rng)
    elif kind == "PAYMENT_TERMS":
        inv.due_date = inv.issue_date + timedelta(days=90)
    return inv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/invoices")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    random.seed(args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    suppliers = make_suppliers(rng)
    truth = []

    # les anomalies tombent sur les dernières factures, une fois l'historique fournisseur constitué
    planned = {args.n - 8: "TOTALS_MISMATCH", args.n - 7: "SIREN_INVALID", args.n - 6: "IBAN_CHANGED",
               args.n - 5: "PAYMENT_TERMS", args.n - 4: "TOTALS_MISMATCH", args.n - 3: "IBAN_CHANGED"}
    for i in range(1, args.n + 1):
        supplier = suppliers[i % len(suppliers)]
        inv = make_invoice(rng, supplier, i)
        anomaly = planned.get(i)
        if anomaly:
            inv = inject(rng, inv, anomaly, suppliers)
        layout = rng.choices(["classic", "siret", "letter"], weights=[5, 4, 2])[0]
        facturx = layout != "letter" and rng.random() < 0.35
        fname = f"{i:03d}_{layout}{'_facturx' if facturx else ''}.pdf"
        path = out / fname
        RENDERERS[layout](inv, path)
        if facturx:
            path.write_bytes(embed_xml(path.read_bytes(), build_cii_xml(inv)))
        truth.append({"file": fname, "layout": layout, "facturx": facturx,
                      "expected_issue": anomaly, "invoice": json.loads(inv.model_dump_json())})

    # doublon : la même facture renvoyée une seconde fois sous un autre nom de fichier
    dup = truth[args.n // 2]
    dup_name = f"{args.n + 1:03d}_doublon_{dup['file']}"
    (out / dup_name).write_bytes((out / dup["file"]).read_bytes())
    truth.append({**dup, "file": dup_name, "expected_issue": "DUPLICATE"})

    (out / "ground_truth.json").write_text(json.dumps(truth, indent=2, ensure_ascii=False))
    n_fx = sum(t["facturx"] for t in truth)
    print(f"{len(truth)} factures générées dans {out} ({n_fx} Factur-X, "
          f"{sum(1 for t in truth if t['expected_issue'])} avec anomalie)")


if __name__ == "__main__":
    main()
