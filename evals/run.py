"""Score local Ollama models on the sample messages.

    python -m evals.run --model qwen2.5:3b --model llama3.2:3b

Each message is sent once with Halo's real system prompt and tools; we grade the model's first
reply (which tool it asks for, with which arguments). Nothing is executed or saved.
"""
import argparse
import json
import os
import sys
import time

from halo.agent import system_prompt
from halo.ollama import Ollama, OllamaError
from halo.tools import TOOLS

from .cases import CASES, NOW
from .grade import CLAIM, grade


def run_model(model: str, url: str, timeout: float, cases=CASES, llm: Ollama | None = None) -> dict:
    llm = llm or Ollama(url, model, timeout)
    llm.chat([{"role": "user", "content": "hi"}])  # warm-up: loading the model is slow, don't time it
    system = {"role": "system", "content": system_prompt(NOW)}
    results = []
    for c in cases:
        messages = [system, *c["history"], {"role": "user", "content": c["text"]}]
        start = time.perf_counter()
        try:
            msg = llm.chat(messages, TOOLS)
            ok, why = grade(c, msg)
            reply = msg["content"].strip()
        except OllamaError as e:
            ok, why, reply = False, f"{e.kind}: {e}", ""
        results.append({"id": c["id"], "group": c["group"], "ok": ok, "why": why, "reply": reply,
                        "claims_booked": bool(CLAIM.search(reply)), "seconds": time.perf_counter() - start})
    groups: dict[str, list[int]] = {}
    for r in results:
        g = groups.setdefault(r["group"], [0, 0])
        g[0] += r["ok"]
        g[1] += 1
    times = [r["seconds"] for r in results]
    return {"model": model, "score": sum(r["ok"] for r in results), "total": len(results), "groups": groups,
            "avg_s": sum(times) / len(times), "max_s": max(times),
            "claims_booked": sum(r["claims_booked"] for r in results), "results": results}


def report(s: dict, verbose: bool = False) -> str:
    pct = round(100 * s["score"] / s["total"])
    lines = [f"\n{s['model']}: {s['score']}/{s['total']} ({pct}%)   avg {s['avg_s']:.1f}s   max {s['max_s']:.1f}s"]
    lines += [f"  {g:<16}{ok}/{n}" for g, (ok, n) in s["groups"].items()]
    if s["claims_booked"]:
        lines.append(f"  WARNING: {s['claims_booked']} repl{'y' if s['claims_booked'] == 1 else 'ies'} "
                     "may say a table is booked/confirmed (rule 4)")
    for r in s["results"]:
        if not r["ok"]:
            lines.append(f"  FAIL {r['id']}: {r['why']}")
        elif verbose:
            lines.append(f"  ok   {r['id']}  {r['reply'][:70]}")
    return "\n".join(lines)


def comparison(summaries: list[dict]) -> str:
    rows = sorted(summaries, key=lambda s: (-s["score"], s["avg_s"]))
    out = ["\nComparison (best first)", f"  {'model':<28}{'score':>8}{'avg s':>8}{'max s':>8}"]
    out += [f"  {s['model']:<28}{s['score']:>5}/{s['total']:<2}{s['avg_s']:>8.1f}{s['max_s']:>8.1f}" for s in rows]
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", action="append", help="Ollama model name; repeat to compare (default: $OLLAMA_MODEL)")
    ap.add_argument("--url", default=os.environ.get("OLLAMA_URL", "http://localhost:11434"))
    ap.add_argument("--timeout", type=float, default=90, help="seconds per message (default 90, more lenient than Halo's 20)")
    ap.add_argument("--json", metavar="PATH", help="also save full results here")
    ap.add_argument("-v", "--verbose", action="store_true", help="show replies for passing cases too")
    args = ap.parse_args(argv)
    models = args.model or [os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")]

    if not Ollama(args.url, models[0]).reachable():
        print(f"Ollama is not reachable at {args.url}. Install it from ollama.com and start it.", file=sys.stderr)
        return 1
    summaries = []
    for model in models:
        print(f"Running {len(CASES)} messages on {model} ...", flush=True)
        try:
            summaries.append(run_model(model, args.url, args.timeout))
        except OllamaError as e:
            print(f"Skipping {model}: {e}. Did you run `ollama pull {model}`?", file=sys.stderr)
            continue
        print(report(summaries[-1], args.verbose))
    if len(summaries) > 1:
        print(comparison(summaries))
    if args.json:
        with open(args.json, "w") as f:
            json.dump(summaries, f, ensure_ascii=False, indent=2)
    return 0 if summaries else 1


if __name__ == "__main__":
    sys.exit(main())
