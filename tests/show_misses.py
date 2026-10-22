"""Print the questions of a harness run that were not fully correct:  python tests/show_misses.py results/sim tests/sim_eval.jsonl"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
run, evalfile = sys.argv[1], sys.argv[2]
ev = {d["id"]: d for d in map(json.loads, open(evalfile, encoding="utf-8"))}
for r in map(json.loads, open(f"{run}/per_question.jsonl", encoding="utf-8")):
    e = ev[r["id"]]
    if r["correctness"] < 1 and (e.get("must_include") or e["category"] == "should_refuse"):
        print(f"{r['id']} [{r['category']}] corr={r['correctness']} missed={r['missed']} traps={r['trap_hits']} as_of={e.get('as_of')}")
        print("   Q:", e["question"])
        print("   GOT:", r["answer"]["text"][:260].replace("\n", " / "))
