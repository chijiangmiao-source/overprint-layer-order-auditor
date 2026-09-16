#!/usr/bin/env python3
"""One-shot acceptance checks run by the `verify` compose service.

Uses only the Python standard library so the verifier image needs no
installed dependencies. It exercises:

  1. API health endpoint.
  2. Web container serving the SPA and proxying /api to the API service.
  3. A greedy-trap instance solved to the known global optimum.
  4. An ambiguous instance returning the two ASCII-minimal optima.
  5. An invalid instance returning ALL errors, sorted by JSON Pointer.
  6. Witness rows re-summing exactly to the reported integer total.
  7. The placement profile: one row per layer, target pinned at every
     depth, costs/deltas/orders re-derived independently, and an unknown
     target rejected with a 422 pointing at /target.

Exits 0 only when every check passes.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

API_BASE = os.environ.get("API_BASE", "http://api:8000")
WEB_BASE = os.environ.get("WEB_BASE", "http://web:80")

failures: list[str] = []
checks = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global checks
    checks += 1
    mark = "PASS" if condition else "FAIL"
    print(f"[{mark}] {name}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(f"{name}: {detail}")


def wait_for(url: str, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if resp.status == 200:
                    return True
        except Exception as exc:  # noqa: BLE001
            last = repr(exc)
            time.sleep(1.0)
    print(f"[wait] giving up on {url}: {last}")
    return False


def post_json(url: str, payload: dict) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def get(url: str) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


GREEDY_TRAP = {
    "layers": ["A", "B", "C", "D"],
    "observations": [
        {"lower": "A", "upper": "B", "weight": 8},
        {"lower": "A", "upper": "C", "weight": 1},
        {"lower": "A", "upper": "D", "weight": 3},
        {"lower": "B", "upper": "A", "weight": 1},
        {"lower": "B", "upper": "C", "weight": 7},
        {"lower": "C", "upper": "A", "weight": 1},
        {"lower": "C", "upper": "D", "weight": 8},
        {"lower": "D", "upper": "A", "weight": 9},
    ],
}


def main() -> int:
    print("== waiting for services ==")
    if not wait_for(f"{API_BASE}/api/health"):
        return 1
    if not wait_for(WEB_BASE + "/"):
        return 1

    print("== 1. health ==")
    status, body = get(f"{API_BASE}/api/health")
    check("api health 200 + ok", status == 200 and json.loads(body)["status"] == "ok",
          f"status={status} body={body!r}")

    print("== 2. web SPA + reverse proxy ==")
    status, body = get(WEB_BASE + "/")
    check("web serves index.html", status == 200 and b"<div id=\"root\"" in body,
          f"status={status}")
    status, body = get(f"{WEB_BASE}/api/health")
    check("nginx proxies /api -> api", status == 200 and b"ok" in body, f"status={status}")

    # All business checks go through the WEB proxy, proving the full path.
    print("== 3. global optimum on the greedy trap ==")
    status, data = post_json(f"{WEB_BASE}/api/solve", GREEDY_TRAP)
    check("solve 200", status == 200, f"status={status} data={data}")
    if status == 200:
        check("status unique", data["status"] == "unique", str(data.get("status")))
        check("cost is exact 11", data["cost"] == 11 and isinstance(data["cost"], int),
              str(data.get("cost")))
        check("order A,B,C,D bottom->top", data["order"] == ["A", "B", "C", "D"],
              str(data.get("order")))
        check("no second optimum", data["second_order"] is None, str(data.get("second_order")))
        rows = data["witness"]["observations"]
        check("witness rows == observations", len(rows) == 8, str(len(rows)))
        check("witness re-sums to total", sum(r["cost"] for r in rows) == data["cost"],
              f"sum={sum(r['cost'] for r in rows)} total={data['cost']}")
        for r in rows:
            expected = r["upper_position"] <= r["lower_position"]
            check(f"row {r['lower']}->{r['upper']} flag/positions consistent",
                  r["violated"] is expected and r["cost"] == (r["weight"] if expected else 0),
                  str(r))

    print("== 4. ambiguous tie -> two ASCII-minimal optima ==")
    tie = {"layers": ["C", "A", "B"],
           "observations": [{"lower": "A", "upper": "B", "weight": 5}]}
    status, data = post_json(f"{WEB_BASE}/api/solve", tie)
    check("tie solve 200", status == 200, str(data))
    if status == 200:
        check("status ambiguous", data["status"] == "ambiguous", data["status"])
        check("first optimum A,B,C", data["order"] == ["A", "B", "C"], str(data["order"]))
        check("second optimum A,C,B", data["second_order"] == ["A", "C", "B"],
              str(data["second_order"]))
        check("equal optimal cost 0", data["cost"] == 0 and data["second_cost"] == 0,
              f"{data['cost']}/{data['second_cost']}")
        check("two witnesses differ", data["witness"]["order"] != data["second_witness"]["order"])

    print("== 5. invalid submission: all errors at once, pointer-sorted ==")
    bad = {
        "layers": ["A", "A", "bad id!", "B"],
        "observations": [
            {"lower": "A", "upper": "A", "weight": 1},
            {"lower": "A", "upper": "B", "weight": 1},
            {"lower": "A", "upper": "B", "weight": 2},
            {"lower": "X", "upper": "B", "weight": 3},
            {"lower": "A", "upper": "Y", "weight": 0},
        ],
    }
    status, data = post_json(f"{WEB_BASE}/api/solve", bad)
    check("invalid -> 422", status == 422, str(status))
    if status == 422:
        pointers = [e["pointer"] for e in data["errors"]]
        check("errors sorted by JSON Pointer", pointers == sorted(pointers), str(pointers))
        joined = " ".join(pointers)
        for needed in ["/layers/1", "/layers/2", "/observations/0", "/observations/2",
                       "/observations/3/lower", "/observations/4/upper",
                       "/observations/4/weight"]:
            check(f"reported {needed}", needed in pointers, joined)
        check("all defects in a single response", len(pointers) >= 7, str(pointers))

    print("== 5b. invalid layers must not hide observation errors ==")
    status, data = post_json(f"{WEB_BASE}/api/solve", {"observations": []})
    check("missing layers + empty obs -> 422", status == 422, str(status))
    if status == 422:
        pointers = [e["pointer"] for e in data["errors"]]
        check("both /layers and /observations reported together",
              "/layers" in pointers and "/observations" in pointers, str(pointers))
        check("still pointer-sorted", pointers == sorted(pointers), str(pointers))

    status, data = post_json(
        f"{WEB_BASE}/api/solve",
        {"observations": [{"lower": "X", "upper": "Y", "weight": 1}]},
    )
    if status == 422:
        pointers = [e["pointer"] for e in data["errors"]]
        check("dangling refs reported without any layer universe",
              "/observations/0/lower" in pointers and "/observations/0/upper" in pointers,
              str(pointers))

    print("== 6. input reordering leaves state/cost/canonical witness unchanged ==")
    shuffled = {"layers": ["D", "A", "C", "B"],
                "observations": list(reversed(GREEDY_TRAP["observations"]))}
    _, a = post_json(f"{API_BASE}/api/solve", GREEDY_TRAP)
    _, b = post_json(f"{API_BASE}/api/solve", shuffled)
    check("reordered status/cost/order identical",
          (a["status"], a["cost"], a["order"]) == (b["status"], b["cost"], b["order"]),
          f'{a["status"]},{a["cost"]},{a["order"]} vs {b["status"]},{b["cost"]},{b["order"]}')
    check("reordered canonical witness identical", a["witness"] == b["witness"])

    print("== 7. placement profile: one row per depth, target pinned ==")
    import itertools

    def violation_total(order, observations):
        pos = {lid: i for i, lid in enumerate(order)}
        return sum(w for lo, up, w in observations if pos[up] <= pos[lo])

    for target in ("A", "B", "C", "D"):
        status, data = post_json(
            f"{WEB_BASE}/api/placement-profile", {**GREEDY_TRAP, "target": target}
        )
        check(f"[{target}] profile 200", status == 200, f"status={status} data={data}")
        if status != 200:
            continue
        n = len(GREEDY_TRAP["layers"])
        depths = data["depths"]
        check(f"[{target}] exactly n rows (one per depth)", len(depths) == n,
              f"got {len(depths)} for n={n}")
        check(f"[{target}] optimal_cost matches /api/solve",
              data["optimal_cost"] == a["cost"], f'{data["optimal_cost"]} vs {a["cost"]}')
        depths_ok = all(row["depth"] == i for i, row in enumerate(depths))
        check(f"[{target}] depths numbered 0..n-1", depths_ok, str([r["depth"] for r in depths]))
        pin_ok = all(row["order"][row["depth"]] == target for row in depths)
        check(f"[{target}] every order pins target at its depth", pin_ok)
        perms_ok = all(
            len(row["order"]) == n and set(row["order"]) == set(GREEDY_TRAP["layers"])
            for row in depths
        )
        check(f"[{target}] every order is a permutation of the layers", perms_ok)

        # Independent n! enumeration of the exact per-depth minima and the
        # ASCII-smallest optimal pinned order.
        triples = [(o["lower"], o["upper"], o["weight"])
                   for o in GREEDY_TRAP["observations"]]
        layer_ids = GREEDY_TRAP["layers"]
        truth = {}
        for perm in itertools.permutations(sorted(layer_ids)):
            d = perm.index(target)
            c = violation_total(perm, triples)
            truth.setdefault(d, []).append((c, list(perm)))
        for row in depths:
            cands = truth[row["depth"]]
            min_c = min(c for c, _ in cands)
            min_order = sorted(p for c, p in cands if c == min_c)[0]
            check(f"[{target}] depth {row['depth']} exact min cost",
                  row["cost"] == min_c, f'{row["cost"]} vs {min_c}')
            check(f"[{target}] depth {row['depth']} ascii-min optimal order",
                  row["order"] == min_order, f'{row["order"]} vs {min_order}')
            check(f"[{target}] depth {row['depth']} delta vs global optimum",
                  row["delta"] == min_c - a["cost"],
                  f'{row["delta"]} vs {min_c - a["cost"]}')
            check(f"[{target}] depth {row['depth']} reported cost is real",
                  violation_total(row["order"], triples) == row["cost"],
                  str(row))

    print("== 7b. profile unknown target -> 422 at /target ==")
    status, data = post_json(f"{WEB_BASE}/api/placement-profile",
                             {**GREEDY_TRAP, "target": "Z"})
    check("unknown target -> 422", status == 422, str(status))
    if status == 422:
        pointers = [e["pointer"] for e in data["errors"]]
        check("error points at /target", pointers == ["/target"], str(pointers))
        check("errors pointer-sorted", pointers == sorted(pointers), str(pointers))

    print("== 7c. profile inherits problem validation like /api/solve ==")
    status, data = post_json(f"{WEB_BASE}/api/placement-profile",
                             {"layers": ["A", "A"],
                              "observations": [{"lower": "A", "upper": "A", "weight": 1}],
                              "target": "X"})
    check("invalid problem + unknown target -> 422", status == 422, str(status))
    if status == 422:
        pointers = [e["pointer"] for e in data["errors"]]
        check("target and problem errors merged + sorted",
              pointers == sorted(pointers) and "/target" in pointers
              and "/layers/1" in pointers, str(pointers))

    # Unknown target must not be hidden when `observations` itself fails its
    # type check (the semantic validator returns early on a non-list).
    status, data = post_json(f"{WEB_BASE}/api/placement-profile",
                             {"layers": ["A", "B"], "observations": "not-a-list",
                              "target": "Z"})
    check("malformed observations + unknown target -> 422", status == 422, str(status))
    if status == 422:
        pointers = [e["pointer"] for e in data["errors"]]
        check("both /observations type error and /target reported",
              "/observations" in pointers and "/target" in pointers
              and pointers == sorted(pointers), str(pointers))

    print("== 7d. /api/solve request contract unchanged ==")
    status, _ = post_json(f"{WEB_BASE}/api/solve", {**GREEDY_TRAP, "target": "A"})
    check("extra target field rejected by /api/solve", status == 422, str(status))

    print()
    print(f"== {checks - len(failures)}/{checks} checks passed ==")
    if failures:
        print("ACCEPTANCE FAILED:")
        for f in failures:
            print("  -", f)
        return 1
    print("ACCEPTANCE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
