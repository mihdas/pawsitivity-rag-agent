"""Run the evaluation set against the real graph (Claude + Qdrant).

    python -m scripts.run_evals [--min-accuracy 0.9]

Prints one line per case and exits with code 1 if accuracy is below the threshold,
so it can gate a deployment in CI.
"""

import argparse
import asyncio
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.graph import default_graph  # noqa: E402


async def run(cases_file: Path, min_accuracy: float) -> int:
    cases = yaml.safe_load(cases_file.read_text(encoding="utf-8"))
    graph = default_graph()
    passed = 0
    for case in cases:
        expected = case["expected_status"]
        expected = expected if isinstance(expected, list) else [expected]
        state = await graph.ainvoke({"message": case["question"], "history": []})
        answer = state.get("answer", "")
        ok = state.get("status") in expected
        missing = [w for w in case.get("must_contain", []) or [] if w.lower() not in answer.lower()]
        ok = ok and not missing
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'}  [{state.get('status'):9}] expected={'/'.join(expected):18} "
              f"{case['question'][:60]}" + (f"  missing={missing}" if missing else ""))
        if not ok:
            print(f"      answer: {answer[:200]!r}")
    accuracy = passed / len(cases)
    print(f"\n{passed}/{len(cases)} passed  (accuracy {accuracy:.0%}, required {min_accuracy:.0%})")
    return 0 if accuracy >= min_accuracy else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", type=Path, default=Path(__file__).resolve().parent.parent / "evals" / "cases.yaml")
    ap.add_argument("--min-accuracy", type=float, default=0.9)
    a = ap.parse_args()
    sys.exit(asyncio.run(run(a.cases, a.min_accuracy)))
