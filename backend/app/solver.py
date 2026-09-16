"""Exact subset dynamic programming for minimum-violation layer ordering.

Problem (from-bottom-to-top permutation of ``n`` unique layers):

* A directed observation ``lower -> upper`` with weight ``w`` is *violated*
  unless ``upper`` appears strictly after ``lower`` in the permutation.
* We seek the permutation minimizing the total weight of violated
  observations; ties are broken by ASCII lexicographic order of the
  sequence of layer ids, and at most the two smallest optimal permutations
  are reported.

The cost of a permutation is additive over prefixes: when a layer ``j`` is
appended to a built prefix (subset ``S``), every observation whose *upper*
is ``j`` and whose *lower* is not yet in the prefix becomes a violation
(that lower can only appear later, i.e. above ``j``).  The cost of placing
``j`` last therefore depends only on ``S``::

    add(j, S) = sum of w over observations (lower -> j) with lower not in S

This subset DP runs over ``2**n`` masks with Python ``int`` cost arithmetic
(weights up to 1_000_000, n <= 20, totals up to ~2e14, all exact).  No
greedy heuristic and no external/general-purpose solver is used.

Memory note: candidate permutations are stored as ``bytes`` of *ASCII
ranks* -- layers are sorted by id, so rank order equals ASCII byte order;
comparing two rank byte strings element by element is therefore exactly
the required id-sequence comparison, at a fraction of tuple memory.
"""

from __future__ import annotations

from typing import List, Sequence, Tuple


def solve(
    layers: Sequence[str],
    observations: Sequence[Tuple[str, str, int]],
) -> dict:
    """Return the optimum status and up to two canonical optimal orders.

    ``observations`` is a sequence of ``(lower_id, upper_id, weight)``
    triples that have already passed full validation (unique ids, no
    dangling/self/duplicate pairs).

    Result keys: ``status`` (``"unique"`` / ``"ambiguous"``), exact ``int``
    ``cost`` / ``second_cost`` and ``order`` / ``second_order`` as layer ids
    from bottom to top.

    The result depends only on the *set* of inputs, never on the order the
    client happened to list them.
    """
    # ASCII rank 0..n-1 makes rank-byte order == layer-id ASCII order.
    ordered = sorted(layers)
    n = len(ordered)
    rank = {layer_id: i for i, layer_id in enumerate(ordered)}

    # incoming[j] = list of (lower rank, weight) for edges lower -> j.
    incoming: List[List[Tuple[int, int]]] = [[] for _ in range(n)]
    for lower_id, upper_id, weight in observations:
        incoming[rank[upper_id]].append((rank[lower_id], weight))

    size = 1 << n
    full = size - 1
    INF = -1  # sentinel: dp[m] == -1 means mask m is unreachable

    # dp[mask] = minimum total cost of the prefix that contains exactly the
    # layers in `mask` (in some order). The empty prefix costs 0.
    dp: List[int] = [INF] * size
    dp[0] = 0

    # best[mask] / second[mask]: the two lexicographically smallest distinct
    # rank sequences among all minimum-cost prefixes building `mask`.
    best: List[bytes | None] = [None] * size
    second: List[bytes | None] = [None] * size
    best[0] = b""

    rank_byte = [bytes((j,)) for j in range(n)]

    for mask in range(size):
        base_cost = dp[mask]
        if base_cost == INF:
            continue
        base_best = best[mask]
        base_second = second[mask]
        remaining = full ^ mask
        while remaining:
            bit = remaining & -remaining
            remaining ^= bit
            j = bit.bit_length() - 1

            # Cost of placing j on top of this prefix: an edge i -> j is
            # satisfied iff i is already in the prefix; otherwise violated.
            add = 0
            for lower_idx, weight in incoming[j]:
                if not (mask >> lower_idx) & 1:
                    add += weight
            cand_cost = base_cost + add
            new_mask = mask | bit
            tail = rank_byte[j]
            cand_best = base_best + tail if base_best is not None else None
            cand_second = base_second + tail if base_second is not None else None

            old_cost = dp[new_mask]
            if old_cost == INF or cand_cost < old_cost:
                dp[new_mask] = cand_cost
                best[new_mask] = cand_best
                second[new_mask] = cand_second
            elif cand_cost == old_cost:
                # Merge up to two candidates, keeping the two smallest
                # distinct rank sequences (== smallest ASCII id sequences).
                a = best[new_mask]
                b = second[new_mask]
                for cand in (cand_best, cand_second):
                    if cand is None:
                        continue
                    if a is None or cand < a:
                        b = a
                        a = cand
                    elif cand != a and (b is None or cand < b):
                        b = cand
                best[new_mask] = a
                second[new_mask] = b

    def to_ids(seq: bytes) -> List[str]:
        return [ordered[r] for r in seq]

    opt_cost = dp[full]
    order = to_ids(best[full])
    second_seq = second[full]

    if second_seq is None:
        return {
            "status": "unique",
            "cost": opt_cost,
            "order": order,
            "second_cost": None,
            "second_order": None,
        }
    return {
        "status": "ambiguous",
        "cost": opt_cost,
        "order": order,
        "second_cost": opt_cost,
        "second_order": to_ids(second_seq),
    }


def evaluate_order(
    layers: Sequence[str],
    observations: Sequence[Tuple[str, str, int]],
    order: Sequence[str],
) -> List[dict]:
    """Recompute each observation's violation for a concrete order.

    Returns one entry per observation with its ``lower``/``upper``/
    ``weight``, positions in the bottom-to-top order, ``violated`` flag
    and contributed ``cost`` so the total can be re-summed line by line.
    Rows are emitted in ASCII order (lower, upper) so input reordering
    cannot change the canonical witness.
    """
    position = {layer_id: pos for pos, layer_id in enumerate(order)}
    rows: List[dict] = []
    for lower_id, upper_id, weight in sorted(observations, key=lambda t: (t[0], t[1])):
        lower_pos = position[lower_id]
        upper_pos = position[upper_id]
        violated = upper_pos <= lower_pos
        rows.append(
            {
                "lower": lower_id,
                "upper": upper_id,
                "weight": weight,
                "lower_position": lower_pos,
                "upper_position": upper_pos,
                "violated": violated,
                "cost": weight if violated else 0,
            }
        )
    return rows
