"""Exhaustive cross-checks of the subset DP against brute-force permutations.

Every small instance is enumerated completely (all n! orders, all lex
optimal orders) and compared with the dynamic program, so the DP is
checked against an independent, obviously-correct reference rather than
hand-picked expectations.
"""

from __future__ import annotations

import itertools
import random

import pytest

from app.solver import evaluate_order, placement_profile, solve


def brute_force(layers, observations):
    """Independent O(n! * m) reference: return (cost, sorted opt orders)."""
    best_cost = None
    best_orders = []
    for perm in itertools.permutations(sorted(layers)):
        rows = evaluate_order(list(perm), observations, list(perm))
        total = sum(r["cost"] for r in rows)
        if best_cost is None or total < best_cost:
            best_cost = total
            best_orders = [list(perm)]
        elif total == best_cost:
            best_orders.append(list(perm))
    best_orders.sort()
    return best_cost, best_orders


def check_case(layers, observations):
    result = solve(layers, observations)
    bf_cost, bf_orders = brute_force(layers, observations)

    assert result["cost"] == bf_cost
    assert result["order"] == bf_orders[0]
    if len(bf_orders) >= 2:
        assert result["status"] == "ambiguous"
        assert result["second_order"] == bf_orders[1]
        assert result["second_cost"] == bf_cost
    else:
        assert result["status"] == "unique"
        assert result["second_order"] is None

    # Every witness row must re-sum to the reported exact total.
    for order in [result["order"]] + (
        [result["second_order"]] if result["second_order"] else []
    ):
        rows = evaluate_order(layers, observations, order)
        assert sum(r["cost"] for r in rows) == result["cost"]
        for r in rows:
            assert r["violated"] == (r["cost"] == r["weight"] and r["weight"] > 0)
            assert r["cost"] == (r["weight"] if r["upper_position"] <= r["lower_position"] else 0)


def test_exhaustive_n2_n3_all_graphs():
    # n=2: 2 possible directed pairs; n=3: 6 possible pairs.
    for n in (2, 3):
        layers = [chr(ord("A") + i) for i in range(n)]
        pairs = list(itertools.permutations(layers, 2))
        # Enumerate every subset of edges with weights drawn from a small
        # alphabet (keeps the full factorial sweep tractable while still
        # covering every graph shape and many weight patterns).
        weight_choices = [1, 1, 3, 8]
        rng = random.Random(42 + n)
        for mask in range(1, 1 << len(pairs)):
            edges = []
            for k, (a, b) in enumerate(pairs):
                if mask >> k & 1:
                    edges.append((a, b, rng.choice(weight_choices)))
            check_case(layers, edges)


def test_exhaustive_n4_random_instances():
    rng = random.Random(2024)
    layers = ["A", "B", "C", "D"]
    pairs = list(itertools.permutations(layers, 2))
    for _ in range(400):
        edges = []
        for a, b in pairs:
            if rng.random() < 0.45:
                edges.append((a, b, rng.randint(1, 12)))
        if not edges:
            continue
        check_case(layers, edges)


def test_greedy_trap_unique_optimum():
    # Locally cheapest-first placement misses the global optimum.
    # Greedy: B,C,D,A -> cost 12 ; DP optimum A,B,C,D -> cost 11, unique.
    edges = [
        ("A", "B", 8), ("A", "C", 1), ("A", "D", 3),
        ("B", "A", 1), ("B", "C", 7),
        ("C", "A", 1), ("C", "D", 8),
        ("D", "A", 9),
    ]
    result = solve(["A", "B", "C", "D"], edges)
    assert result == {
        "status": "unique",
        "cost": 11,
        "order": ["A", "B", "C", "D"],
        "second_cost": None,
        "second_order": None,
    }

    # Demonstrate the greedy failure explicitly.
    incoming = {x: [] for x in "ABCD"}
    for a, b, w in edges:
        incoming[b].append((a, w))

    def add_cost(j, built):
        return sum(w for low, w in incoming[j] if low not in built)

    built = []
    remaining = set("ABCD")
    while remaining:
        nxt = min(remaining, key=lambda x: (add_cost(x, set(built)), x))
        built.append(nxt)
        remaining.remove(nxt)
    assert built == ["B", "C", "D", "A"]
    rows = evaluate_order(["A", "B", "C", "D"], edges, built)
    assert sum(r["cost"] for r in rows) == 12  # strictly worse than DP


def test_non_equal_weight_cycle():
    # Directed 3-cycle A->B 100, B->C 100, C->A 1. Every permutation must
    # break at least one edge; unequal weights make the unique cheapest
    # break be the light edge C->A. An unweighted solver would see a
    # three-way tie here.
    edges = [("A", "B", 100), ("B", "C", 100), ("C", "A", 1)]
    result = solve(["A", "B", "C"], edges)
    assert result["status"] == "unique"
    assert result["order"] == ["A", "B", "C"]
    assert result["cost"] == 1
    rows = { (r["lower"], r["upper"]): r for r in evaluate_order(["A", "B", "C"], edges, result["order"]) }
    assert rows[("A", "B")]["violated"] is False
    assert rows[("B", "C")]["violated"] is False
    assert rows[("C", "A")]["violated"] is True

    # Breaking either heavy edge instead costs two orders of magnitude more.
    for alt_order in (["B", "C", "A"], ["C", "A", "B"]):
        alt_rows = evaluate_order(["A", "B", "C"], edges, alt_order)
        assert sum(r["cost"] for r in alt_rows) == 100
    bf_cost, _ = brute_force(["A", "B", "C"], edges)
    assert bf_cost == 1


def test_symmetric_tie_returns_two_ascii_minima():
    # Single edge A->B weight 5 among A,B,C: any order with A before B has
    # cost 0. The two ASCII-smallest such permutations are A,B,C and A,C,B.
    edges = [("A", "B", 5)]
    result = solve(["C", "A", "B"], edges)
    assert result["status"] == "ambiguous"
    assert result["cost"] == 0
    assert result["order"] == ["A", "B", "C"]
    assert result["second_order"] == ["A", "C", "B"]
    assert result["second_cost"] == 0


def test_reordering_inputs_is_invisible():
    edges = [
        ("A", "B", 8), ("A", "C", 1), ("A", "D", 3),
        ("B", "A", 1), ("B", "C", 7),
        ("C", "A", 1), ("C", "D", 8), ("D", "A", 9),
    ]
    base = solve(["A", "B", "C", "D"], edges)
    shuffled_layers = ["D", "A", "C", "B"]
    shuffled_edges = list(reversed(edges))
    again = solve(shuffled_layers, shuffled_edges)
    assert again == base


# ---------------------------------------------------------------------------
# Placement profile (target pinned at each depth)
# ---------------------------------------------------------------------------

def brute_profile(layers, observations, target):
    """Independent O(n!) reference: {depth: (min cost, ASCII-min order)}."""
    per_depth = {}
    for perm in itertools.permutations(sorted(layers)):
        depth = perm.index(target)
        total = sum(r["cost"] for r in evaluate_order(layers, observations, list(perm)))
        per_depth.setdefault(depth, []).append((total, list(perm)))
    out = {}
    for depth, candidates in per_depth.items():
        best = min(c for c, _ in candidates)
        out[depth] = (best, sorted(p for c, p in candidates if c == best)[0])
    return out


def check_profile_case(layers, observations, target=None):
    targets = [target] if target is not None else sorted(layers)
    for t in targets:
        result = placement_profile(layers, observations, t)
        bf = brute_profile(layers, observations, t)
        opt = solve(layers, observations)["cost"]

        assert result["target"] == t
        assert result["optimal_cost"] == opt
        assert len(result["depths"]) == len(layers)

        by_depth = {row["depth"]: row for row in result["depths"]}
        assert sorted(by_depth) == list(range(len(layers)))
        for depth in range(len(layers)):
            row = by_depth[depth]
            bcost, border = bf[depth]
            assert row["cost"] == bcost
            assert row["order"] == border
            assert row["order"][depth] == t
            assert row["delta"] == bcost - opt
            assert row["delta"] >= 0
        assert min(row["cost"] for row in result["depths"]) == opt
        assert {row["depth"]: row["order"] for row in result["depths"]} == \
            {d: o for d, (_, o) in bf.items()}


def test_profile_exhaustive_n2_n3_all_graphs():
    for n in (2, 3):
        layers = [chr(ord("A") + i) for i in range(n)]
        pairs = list(itertools.permutations(layers, 2))
        weight_choices = [1, 1, 3, 8]
        rng = random.Random(4242 + n)
        for mask in range(1, 1 << len(pairs)):
            edges = []
            for k, (a, b) in enumerate(pairs):
                if mask >> k & 1:
                    edges.append((a, b, rng.choice(weight_choices)))
            for t in layers:
                check_profile_case(layers, edges, t)


def test_profile_exhaustive_n4_random_instances():
    rng = random.Random(202405)
    layers = ["A", "B", "C", "D"]
    pairs = list(itertools.permutations(layers, 2))
    for _ in range(150):
        edges = []
        for a, b in pairs:
            if rng.random() < 0.45:
                edges.append((a, b, rng.randint(1, 12)))
        if not edges:
            continue
        check_profile_case(layers, edges)  # all four targets each time


def test_profile_greedy_trap_known_values():
    edges = [
        ("A", "B", 8), ("A", "C", 1), ("A", "D", 3),
        ("B", "A", 1), ("B", "C", 7),
        ("C", "A", 1), ("C", "D", 8),
        ("D", "A", 9),
    ]
    layers = ["A", "B", "C", "D"]
    profile = placement_profile(layers, edges, "C")
    assert profile["optimal_cost"] == 11
    by_depth = {row["depth"]: row for row in profile["depths"]}
    # Global optimum A,B,C,D pins C at depth 2: delta 0 there, >0 elsewhere.
    expected = {
        0: (12, ["C", "D", "A", "B"]),
        1: (12, ["B", "C", "D", "A"]),
        2: (11, ["A", "B", "C", "D"]),
        3: (13, ["D", "A", "B", "C"]),
    }
    for depth, (cost, order) in expected.items():
        assert by_depth[depth]["cost"] == cost
        assert by_depth[depth]["order"] == order
        assert by_depth[depth]["delta"] == cost - 11
    assert [d["order"][d["depth"]] for d in profile["depths"]] == ["C"] * 4


def test_profile_unknown_target_raises():
    with pytest.raises(ValueError):
        placement_profile(["A", "B"], [("A", "B", 1)], "Z")


def test_profile_reorder_invariant():
    edges = [
        ("A", "B", 8), ("A", "C", 1), ("A", "D", 3),
        ("B", "A", 1), ("B", "C", 7),
        ("C", "A", 1), ("C", "D", 8), ("D", "A", 9),
    ]
    base = placement_profile(["D", "A", "C", "B"], list(reversed(edges)), "A")
    again = placement_profile(["A", "B", "C", "D"], edges, "A")
    assert base == again
