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
