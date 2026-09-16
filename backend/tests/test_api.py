"""End-to-end API tests: validation, canonical witnesses, exact integers."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


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


def post(payload):
    return client.post("/api/solve", json=payload)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_greedy_trap_unique_response_and_resummable_witness():
    r = post(GREEDY_TRAP)
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "unique"
    assert d["cost"] == 11
    assert d["order"] == ["A", "B", "C", "D"]
    assert d["second_order"] is None

    w = d["witness"]
    assert w["order"] == d["order"]
    assert w["cost"] == d["cost"]
    assert sum(row["cost"] for row in w["observations"]) == d["cost"]
    # Positions must be consistent with the order and each row's flag must
    # match its contributed cost.
    for row in w["observations"]:
        assert row["lower_position"] == d["order"].index(row["lower"])
        assert row["upper_position"] == d["order"].index(row["upper"])
        expected_violation = row["upper_position"] <= row["lower_position"]
        assert row["violated"] is expected_violation
        assert row["cost"] == (row["weight"] if expected_violation else 0)


def test_ambiguous_returns_two_optimal_witnesses():
    payload = {
        "layers": ["C", "A", "B"],
        "observations": [{"lower": "A", "upper": "B", "weight": 5}],
    }
    d = post(payload).json()
    assert d["status"] == "ambiguous"
    assert d["order"] == ["A", "B", "C"]
    assert d["second_order"] == ["A", "C", "B"]
    assert d["cost"] == d["second_cost"] == 0
    assert d["second_witness"]["order"] == d["second_order"]
    assert sum(r["cost"] for r in d["second_witness"]["observations"]) == 0


def test_all_errors_returned_together_sorted_by_json_pointer():
    payload = {
        "layers": ["A", "A", "bad id!", "B"],
        "observations": [
            {"lower": "A", "upper": "A", "weight": 1},          # self loop
            {"lower": "A", "upper": "B", "weight": 1},
            {"lower": "A", "upper": "B", "weight": 2},          # duplicate pair
            {"lower": "X", "upper": "B", "weight": 3},          # dangling lower
            {"lower": "A", "upper": "Y", "weight": 0},          # dangling upper + bad weight
        ],
    }
    r = post(payload)
    assert r.status_code == 422
    errors = r.json()["errors"]
    pointers = [e["pointer"] for e in errors]
    assert pointers == sorted(pointers), pointers

    # Every distinct defect is present in the single response.
    joined = "\n".join(f"{e['pointer']}: {e['message']}" for e in errors)
    assert "/layers/1" in joined and "duplicate" in joined
    assert "/layers/2" in joined
    assert "/observations" not in pointers  # observations is non-empty
    assert any(p == "/observations/0" and "self loop" in m for p, m in
               ((e["pointer"], e["message"]) for e in errors))
    assert any(p == "/observations/2" and "duplicate" in m for p, m in
               ((e["pointer"], e["message"]) for e in errors))
    assert "/observations/3/lower" in pointers
    assert "/observations/4/upper" in pointers
    assert "/observations/4/weight" in pointers
    assert len(errors) >= 7


def test_empty_observations_is_invalid():
    r = post({"layers": ["A", "B"], "observations": []})
    assert r.status_code == 422
    assert r.json()["errors"][0]["pointer"] == "/observations"


def test_errors_are_not_dropped_when_layers_also_invalid():
    # Regression: an invalid `layers` field must not hide the empty-list
    # error on `observations`, and vice versa.
    r = post({"observations": []})
    pointers = [e["pointer"] for e in r.json()["errors"]]
    assert "/layers" in pointers
    assert "/observations" in pointers
    assert pointers == sorted(pointers)

    r = post({"layers": "not-a-list", "observations": []})
    pointers = [e["pointer"] for e in r.json()["errors"]]
    assert "/layers" in pointers
    assert "/observations" in pointers

    # Wrong layer COUNT plus empty observations must both surface.
    r = post({"layers": ["A"], "observations": []})
    pointers = [e["pointer"] for e in r.json()["errors"]]
    assert "/layers" in pointers and "/observations" in pointers


def test_dangling_reports_even_without_valid_layer_universe():
    # Dangling references must be reported even when `layers` is missing;
    # no valid layer universe is required to know these ids are absent.
    r = post({"observations": [{"lower": "X", "upper": "Y", "weight": 1}]})
    pointers = [e["pointer"] for e in r.json()["errors"]]
    assert "/layers" in pointers
    assert "/observations/0/lower" in pointers
    assert "/observations/0/upper" in pointers


def test_malformed_listed_id_is_not_also_reported_as_dangling():
    # "bad id" IS listed (fails the id pattern at /layers/0); referencing it
    # must not add a redundant dangling-reference error.
    r = post({"layers": ["bad id", "B"],
              "observations": [{"lower": "bad id", "upper": "B", "weight": 1}]})
    pointers = [e["pointer"] for e in r.json()["errors"]]
    assert pointers == ["/layers/0"]

    # A truly unlisted id alongside a malformed listed id is still dangling.
    r = post({"layers": ["bad id", "B"],
              "observations": [{"lower": "bad id", "upper": "ghost", "weight": 1}]})
    pointers = [e["pointer"] for e in r.json()["errors"]]
    assert pointers == ["/layers/0", "/observations/0/upper"]


@pytest.mark.parametrize("count", [0, 1, 21])
def test_layer_count_bounds(count):
    r = post({"layers": [f"L{i}" for i in range(count)],
              "observations": [{"lower": "L0", "upper": "L1", "weight": 1}]
              if count >= 2 else []})
    assert r.status_code == 422
    assert any(e["pointer"] == "/layers" for e in r.json()["errors"])


@pytest.mark.parametrize("weight", [0, -1, 1_000_001])
def test_weight_bounds(weight):
    r = post({"layers": ["A", "B"],
              "observations": [{"lower": "A", "upper": "B", "weight": weight}]})
    assert r.status_code == 422
    assert any(e["pointer"] == "/observations/0/weight" for e in r.json()["errors"])


def test_strict_integer_weight_rejects_bool_and_float():
    for bad in (True, 1.5, "7"):
        r = post({"layers": ["A", "B"],
                  "observations": [{"lower": "A", "upper": "B", "weight": bad}]})
        assert r.status_code == 422, (bad, r.status_code)
        assert any(e["pointer"] == "/observations/0/weight" for e in r.json()["errors"])


def test_unknown_fields_rejected():
    r = post({"layers": ["A", "B"],
              "observations": [{"lower": "A", "upper": "B", "weight": 1, "note": "x"}]})
    assert r.status_code == 422
    assert any("note" in e["pointer"] for e in r.json()["errors"])


def test_invalid_json_body():
    r = client.post("/api/solve", content=b"{not json",
                    headers={"content-type": "application/json"})
    assert r.status_code == 422
    assert r.json()["errors"][0]["pointer"] == ""


def test_input_reordering_gives_identical_canonical_witness():
    shuffled = {
        "layers": ["D", "A", "C", "B"],
        "observations": list(reversed(GREEDY_TRAP["observations"])),
    }
    a = post(GREEDY_TRAP).json()
    b = post(shuffled).json()
    assert a["status"] == b["status"]
    assert a["cost"] == b["cost"]
    assert a["order"] == b["order"]
    assert a["witness"] == b["witness"]


def test_exact_integer_arithmetic_large_weights():
    # Complete bidirected graph on 20 layers (190 pairs) at weight 1_000_000
    # stays exact (no float leakage): a chain satisfies one direction of
    # each unordered pair and violates the other, i.e. C(20,2)=190 edges.
    layers = [f"L{i:02d}" for i in range(20)]
    observations = [
        {"lower": layers[i], "upper": layers[j], "weight": 1_000_000}
        for i in range(20) for j in range(20) if i != j
    ]
    started = time.perf_counter()
    r = post({"layers": layers, "observations": observations})
    elapsed = time.perf_counter() - started
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["cost"] == 190 * 1_000_000
    assert isinstance(d["cost"], int)
    assert sum(row["cost"] for row in d["witness"]["observations"]) == d["cost"]
    assert elapsed < 30, f"20-layer DP too slow: {elapsed:.1f}s"


# ---------------------------------------------------------------------------
# POST /api/placement-profile
# ---------------------------------------------------------------------------

PROFILE_PROBLEM = {
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


def post_profile(payload):
    return client.post("/api/placement-profile", json=payload)


def test_profile_shape_and_pin_constraints():
    r = post_profile({**PROFILE_PROBLEM, "target": "C"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["target"] == "C"
    assert d["optimal_cost"] == 11
    assert [row["depth"] for row in d["depths"]] == [0, 1, 2, 3]
    assert len(d["depths"] ) == 4
    # Exactly one row per layer, and every reported order puts the target at
    # exactly the depth of that row.
    for row in d["depths"]:
        assert len(row["order"]) == 4
        assert row["order"][row["depth"]] == "C"
        assert set(row["order"]) == {"A", "B", "C", "D"}
        assert isinstance(row["cost"], int) and isinstance(row["delta"], int)
        assert row["cost"] >= d["optimal_cost"]
        assert row["delta"] == row["cost"] - d["optimal_cost"]
    # The unrestricted optimum A,B,C,D sits at depth 2 with zero increment.
    by_depth = {row["depth"]: row for row in d["depths"]}
    assert by_depth[2]["cost"] == 11 and by_depth[2]["delta"] == 0
    assert by_depth[2]["order"] == ["A", "B", "C", "D"]
    assert all(row["delta"] > 0 for depth, row in by_depth.items() if depth != 2)


def test_profile_costs_match_witness_recompute():
    # The pinned cost must be the real violation sum of the reported order.
    from app.solver import evaluate_order

    triples = [(o["lower"], o["upper"], o["weight"]) for o in PROFILE_PROBLEM["observations"]]
    d = post_profile({**PROFILE_PROBLEM, "target": "B"}).json()
    for row in d["depths"]:
        total = sum(x["cost"] for x in evaluate_order(PROFILE_PROBLEM["layers"], triples, row["order"]))
        assert total == row["cost"]


def test_profile_unknown_target_is_422_at_target_pointer():
    r = post_profile({**PROFILE_PROBLEM, "target": "Z"})
    assert r.status_code == 422
    errors = r.json()["errors"]
    pointers = [e["pointer"] for e in errors]
    assert pointers == ["/target"], pointers
    assert "Z" in errors[0]["message"]


def test_profile_unknown_target_merges_with_other_errors_sorted():
    payload = {
        "layers": ["A", "B"],
        "observations": [{"lower": "A", "upper": "B", "weight": 0}],
        "target": "X",
    }
    r = post_profile(payload)
    assert r.status_code == 422
    pointers = [e["pointer"] for e in r.json()["errors"]]
    assert pointers == sorted(pointers)
    assert "/observations/0/weight" in pointers and "/target" in pointers


def test_profile_unknown_target_reported_when_observations_malformed():
    # Regression: when `observations` fails its *type* check the semantic
    # validator returns early; the unknown-target error (which only needs the
    # layers list) must still be reported in the same response.
    r = post_profile({"layers": ["A", "B"], "observations": "not-a-list", "target": "Z"})
    assert r.status_code == 422
    pointers = [e["pointer"] for e in r.json()["errors"]]
    assert "/observations" in pointers, pointers  # Pydantic type error
    assert "/target" in pointers, pointers  # unknown target must not be hidden
    assert pointers == sorted(pointers), pointers

    # Same guarantee when observations is missing entirely.
    r = post_profile({"layers": ["A", "B"], "target": "Z"})
    assert r.status_code == 422
    pointers = [e["pointer"] for e in r.json()["errors"]]
    assert "/observations" in pointers and "/target" in pointers
    assert pointers == sorted(pointers)

    # An invalid (non-string) target reports only the Pydantic type error.
    r = post_profile({"layers": ["A", "B"],
                      "observations": [{"lower": "A", "upper": "B", "weight": 1}],
                      "target": 7})
    assert r.status_code == 422
    pointers = [e["pointer"] for e in r.json()["errors"]]
    assert pointers == ["/target"], pointers


def test_profile_rejects_invalid_problem_like_solve():
    r = post_profile({"layers": ["A", "A"],
                      "observations": [{"lower": "A", "upper": "A", "weight": 1}],
                      "target": "A"})
    assert r.status_code == 422
    pointers = [e["pointer"] for e in r.json()["errors"]]
    assert "/layers/1" in pointers and "/observations/0" in pointers


def test_profile_rejects_bad_json_and_extra_fields():
    r = client.post("/api/placement-profile", content=b"{bad",
                    headers={"content-type": "application/json"})
    assert r.status_code == 422
    assert r.json()["errors"][0]["pointer"] == ""

    r = post_profile({**PROFILE_PROBLEM, "target": "A", "extra": 1})
    assert r.status_code == 422
    assert any("extra" in e["pointer"] for e in r.json()["errors"])


def test_profile_requires_target_field():
    r = post_profile(PROFILE_PROBLEM)
    assert r.status_code == 422
    assert any(e["pointer"] == "/target" for e in r.json()["errors"])


def test_profile_reorder_invariant():
    a = post_profile({**PROFILE_PROBLEM, "target": "D"}).json()
    shuffled = {
        "layers": ["D", "A", "C", "B"],
        "observations": list(reversed(PROFILE_PROBLEM["observations"])),
        "target": "D",
    }
    b = post_profile(shuffled).json()
    assert a == b


def test_solve_still_ignores_target_field():
    # /api/solve must keep its exact request contract: an unexpected field
    # is rejected (it always was), proving no schema drift.
    r = client.post("/api/solve", json={**PROFILE_PROBLEM, "target": "A"})
    assert r.status_code == 422
