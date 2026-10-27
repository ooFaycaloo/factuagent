"""Évalue le pipeline contre la vérité terrain : précision par champ et détection d'anomalies.

Usage : python eval/evaluate.py --data data/invoices [--llm] [--out eval/report.md]
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from factuagent.pipeline import Pipeline  # noqa: E402
from factuagent.store import Store  # noqa: E402

FIELDS = ["invoice_number", "issue_date", "due_date", "seller.name", "seller.siren", "seller.vat_id",
          "seller.iban", "buyer.name", "total_ht", "total_vat", "total_ttc", "n_lines"]
# un SIREN modifié rend aussi le n° de TVA incohérent : ce n'est pas un faux positif
IMPLIED = {"SIREN_INVALID": {"VAT_INVALID"}}


def get(d: dict, path: str):
    if path == "n_lines":
        return len(d.get("lines") or [])
    for k in path.split("."):
        d = (d or {}).get(k)
    return d


def same(a, b) -> bool:
    if a is None or b is None:
        return a == b
    try:
        return Decimal(str(a)) == Decimal(str(b))
    except Exception:
        return str(a).strip().lower() == str(b).strip().lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/invoices")
    ap.add_argument("--llm", action="store_true", help="utiliser Claude (ANTHROPIC_API_KEY requis)")
    ap.add_argument("--out", default="eval/report.md")
    args = ap.parse_args()

    data = Path(args.data)
    truth = json.loads((data / "ground_truth.json").read_text())
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(Path(tmp) / "eval.duckdb")
        pipe = Pipeline(store, use_llm=args.llm)

        field_ok = defaultdict(int)
        field_n = defaultdict(int)
        by_method = defaultdict(lambda: [0, 0])
        by_layout = defaultdict(lambda: [0, 0])
        tp = fn = fp = 0
        rows = []
        for t in truth:
            res = pipe.process(data / t["file"])
            got = json.loads(res.invoice.model_dump_json()) if res.invoice else {}
            n_ok = 0
            for f in FIELDS:
                ok = bool(got) and same(get(got, f), get(t["invoice"], f))
                field_ok[f] += ok
                field_n[f] += 1
                n_ok += ok
            by_method[res.method][0] += n_ok
            by_method[res.method][1] += len(FIELDS)
            by_layout[t["layout"]][0] += n_ok
            by_layout[t["layout"]][1] += len(FIELDS)

            detected = {i.code for i in res.issues if i.severity in ("error", "warning")}
            detected.discard("EXTRACTION_FAILED")
            expected = {t["expected_issue"]} if t["expected_issue"] else set()
            allowed = expected | set().union(*(IMPLIED.get(e, set()) for e in expected))
            tp += len(expected & detected)
            fn += len(expected - detected)
            extra = detected - allowed
            fp += len(extra)
            rows.append((t["file"], res.method, res.status, n_ok, ",".join(sorted(expected)) or "-",
                         ",".join(sorted(detected)) or "-", ",".join(sorted(extra)) or ""))
        store.close()

    total_ok = sum(field_ok.values())
    total_n = sum(field_n.values())
    recall = tp / (tp + fn) if tp + fn else 0
    precision = tp / (tp + fp) if tp + fp else 0
    mode = "Claude (LLM) + Factur-X" if args.llm else "règles + Factur-X (sans LLM)"

    lines = [f"# Rapport d'évaluation — {mode}", "",
             f"- Factures évaluées : **{len(truth)}**",
             f"- Précision globale par champ : **{total_ok / total_n:.1%}** ({total_ok}/{total_n})",
             f"- Anomalies : rappel **{recall:.0%}** ({tp}/{tp + fn}), précision **{precision:.0%}** "
             f"({fp} fausse(s) alerte(s))", "",
             "## Par méthode d'extraction", "", "| Méthode | Précision champs |", "|---|---|"]
    lines += [f"| {m} | {ok / n:.1%} |" for m, (ok, n) in sorted(by_method.items())]
    lines += ["", "## Par mise en page", "", "| Mise en page | Précision champs |", "|---|---|"]
    lines += [f"| {l} | {ok / n:.1%} |" for l, (ok, n) in sorted(by_layout.items())]
    lines += ["", "## Par champ", "", "| Champ | Précision |", "|---|---|"]
    lines += [f"| {f} | {field_ok[f] / field_n[f]:.1%} |" for f in FIELDS]
    lines += ["", "## Détail", "", "| Fichier | Méthode | Statut | Champs OK | Anomalie attendue | Détectée | Fausse alerte |",
              "|---|---|---|---|---|---|---|"]
    lines += [f"| {r[0]} | {r[1]} | {r[2]} | {r[3]}/{len(FIELDS)} | {r[4]} | {r[5]} | {r[6]} |" for r in rows]
    report = "\n".join(lines) + "\n"
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(report)
    print("\n".join(lines[:6]))
    print(f"\nRapport complet : {args.out}")


if __name__ == "__main__":
    main()
