"""Agent conversationnel : pose une question en français sur tes factures, Claude choisit les outils.

Usage : python -m factuagent.agent "Quels fournisseurs ont changé d'IBAN ce mois-ci ?"
Nécessite ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import inspect
import json
import os
import sys
import typing

import anthropic

from .tools import TOOL_NAMES, InvoiceTools

SYSTEM = ("Tu es l'assistant comptabilité fournisseurs d'une PME française. Tu réponds en français, "
          "de façon concise et chiffrée, en t'appuyant uniquement sur les résultats des outils. "
          "Tu signales clairement les risques (doublons, changement d'IBAN, totaux incohérents) "
          "et tu ne valides jamais un paiement toi-même.")

PY_TO_JSON = {str: "string", int: "integer", float: "number", bool: "boolean"}


def tool_schema(fn) -> dict:
    props, required = {}, []
    hints = typing.get_type_hints(fn)
    for name, p in inspect.signature(fn).parameters.items():
        t = hints.get(name, str)
        base = next((a for a in typing.get_args(t) if a is not type(None)), t)
        props[name] = {"type": PY_TO_JSON.get(base, "string")}
        if p.default is inspect.Parameter.empty:
            required.append(name)
    return {"name": fn.__name__, "description": (fn.__doc__ or "").strip(),
            "input_schema": {"type": "object", "properties": props, "required": required}}


def run(question: str, max_turns: int = 8) -> str:
    tools = InvoiceTools()
    fns = {n: getattr(tools, n) for n in TOOL_NAMES}
    client = anthropic.Anthropic()
    model = os.environ.get("FACTUAGENT_AGENT_MODEL", "claude-sonnet-5-5")
    messages = [{"role": "user", "content": question}]
    for _ in range(max_turns):
        resp = client.messages.create(model=model, max_tokens=2000, system=SYSTEM,
                                      tools=[tool_schema(f) for f in fns.values()], messages=messages)
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            return "".join(b.text for b in resp.content if b.type == "text")
        results = []
        for b in resp.content:
            if b.type == "tool_use":
                print(f"  → {b.name}({json.dumps(b.input, ensure_ascii=False)})", file=sys.stderr)
                out = fns[b.name](**b.input)
                results.append({"type": "tool_result", "tool_use_id": b.id,
                                "content": json.dumps(out, default=str, ensure_ascii=False)[:20000]})
        messages.append({"role": "user", "content": results})
    return "Nombre maximal d'étapes atteint."


if __name__ == "__main__":
    print(run(" ".join(sys.argv[1:]) or "Quelles factures dois-je contrôler en priorité ?"))
