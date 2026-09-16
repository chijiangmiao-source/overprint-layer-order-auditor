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

from typing import List, Optional, Sequence, Tuple


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


def placement_profile(
    layers: Sequence[str],
    observations: Sequence[Tuple[str, str, int]],
    target: str,
) -> dict:
    """Sensitivity profile: optimum cost with ``target`` pinned at each depth.

    For every depth ``d`` (0 = bottom, n-1 = top) this returns the minimum
    total violation cost among permutations whose position ``d`` is
    ``target``, the increment ``delta`` over the unrestricted global
    optimum, and the ASCII-smallest permutation attaining that pinned
    optimum.

    The whole profile is built with *two* subset passes over the ``n-1``
    other layers instead of re-running a full ``solve`` per depth:

    * Forward pass ``fwd[P]``: cheapest (and ASCII-smallest) order of the
      prefix set ``P`` below the target. Edges ``target -> j`` are always
      violated there (the target is still above every prefix layer), so the
      target acts as a lower rank that is never part of the built mask.
    * Reverse "peel" pass ``rev[Q]``: cheapest order of a suffix set ``Q``
      above the target, built from the top down -- when ``j`` is placed just
      below an already-peeled (above) set ``R``, only edges ``i -> j`` with
      ``i in R`` are violated.

    Pinning the target at depth ``d`` with prefix ``P`` (``|P| = d``) and
    suffix ``Q = others \\ P`` then only joins the two cached states::

        total(d, P) = fwd[P] + add_target(P) + rev[Q]

    where ``add_target(P)`` is the weight of edges ``i -> target`` whose
    lower ``i`` is not in ``P``.  Costs split independently over the two
    fixed subsets, so the ASCII-smallest pinned permutation is the
    ASCII-smallest optimal prefix byte sequence, the target, and the
    ASCII-smallest optimal suffix byte sequence.
    """
    if target not in set(layers):
        raise ValueError(f"unknown target layer {target!r}")

    # Compressed ranks over the n-1 non-target layers preserve ASCII order:
    # deleting one element from a sorted sequence does not change the
    # relative order of the rest.  Lower rank -1 encodes the target itself.
    others = sorted(layer_id for layer_id in layers if layer_id != target)
    n1 = len(others)
    urank = {layer_id: i for i, layer_id in enumerate(others)}

    # incoming[j] = list of (lower code, weight) for edges lower -> j.
    incoming: List[List[Tuple[int, int]]] = [[] for _ in range(n1)]
    incoming_target: List[Tuple[int, int]] = []
    for lower_id, upper_id, weight in observations:
        code = -1 if lower_id == target else urank[lower_id]
        if upper_id == target:
            incoming_target.append((urank[lower_id], weight))
        else:
            incoming[urank[upper_id]].append((code, weight))

    size = 1 << n1
    full = size - 1
    INF = -1
    rank_byte = [bytes((j,)) for j in range(n1)]
    target_byte = bytes((n1,))  # sits at the fixed depth index in joins

    # ---- forward pass: prefixes built bottom-to-top ---------------------
    fwd: List[int] = [INF] * size
    fwd[0] = 0
    fbest: List[bytes | None] = [None] * size
    fbest[0] = b""

    for mask in range(size):
        base = fwd[mask]
        if base == INF:
            continue
        remaining = full ^ mask
        while remaining:
            bit = remaining & -remaining
            remaining ^= bit
            j = bit.bit_length() - 1
            # A lower that is still unplaced (or that is the target, which
            # never belongs to a prefix mask) forces a violation.
            add = 0
            for code, weight in incoming[j]:
                if code < 0 or not ((mask >> code) & 1):
                    add += weight
            new_mask = mask | bit
            cand_cost = base + add
            cand_seq = fbest[mask] + rank_byte[j]
            old = fwd[new_mask]
            if old == INF or cand_cost < old or (
                cand_cost == old and cand_seq < fbest[new_mask]
            ):
                fwd[new_mask] = cand_cost
                fbest[new_mask] = cand_seq

    # ---- reverse pass: suffixes peeled top-to-bottom --------------------
    # rev[mask]: mask is the set already peeled above. Placing j just below
    # it violates exactly the edges i -> j whose lower i is already peeled.
    rev: List[int] = [INF] * size
    rev[0] = 0
    rbest: List[bytes | None] = [None] * size
    rbest[0] = b""

    for mask in range(size):
        base = rev[mask]
        if base == INF:
            continue
        remaining = full ^ mask
        while remaining:
            bit = remaining & -remaining
            remaining ^= bit
            j = bit.bit_length() - 1
            add = 0
            for code, weight in incoming[j]:
                if code >= 0 and ((mask >> code) & 1):
                    add += weight
            new_mask = mask | bit
            cand_cost = base + add
            # j is immediately below every peeled layer in `mask`, so in
            # bottom-to-top reading its byte precedes the stored suffix.
            cand_seq = rank_byte[j] + rbest[mask]
            old = rev[new_mask]
            if old == INF or cand_cost < old or (
                cand_cost == old and cand_seq < rbest[new_mask]
            ):
                rev[new_mask] = cand_cost
                rbest[new_mask] = cand_seq

    def to_ids(seq: bytes) -> List[str]:
        return [others[r] for r in seq]

    # ---- join the two cached states once per feasible prefix mask -------
    pinned: List[Optional[Tuple[int, bytes]]] = [None] * (n1 + 1)
    for pmask in range(size):
        if fwd[pmask] == INF:
            continue
        qmask = full ^ pmask
        at_target = 0
        for code, weight in incoming_target:
            if not ((pmask >> code) & 1):
                at_target += weight
        total = fwd[pmask] + at_target + rev[qmask]
        seq = fbest[pmask] + target_byte + rbest[qmask]
        depth = pmask.bit_count()
        incumbent = pinned[depth]
        if incumbent is None or total < incumbent[0] or (
            total == incumbent[0] and seq < incumbent[1]
        ):
            pinned[depth] = (total, seq)

    depths: List[dict] = []
    # Every permutation pins the target at exactly one depth, so minimizing
    # over the depth rows recovers the unrestricted global optimum -- no
    # separate full solve pass is needed.
    optimal_cost = min(cost for cost, _ in pinned)
    for depth, (cost, seq) in enumerate(pinned):
        prefix_seq = seq[:depth]
        suffix_seq = seq[depth + 1:]
        order = to_ids(prefix_seq) + [target] + to_ids(suffix_seq)
        depths.append(
            {
                "depth": depth,
                "cost": cost,
                "delta": cost - optimal_cost,
                "order": order,
            }
        )

    return {"target": target, "optimal_cost": optimal_cost, "depths": depths}


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
