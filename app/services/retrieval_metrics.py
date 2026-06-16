"""IR retrieval metrics for evaluation.

Standard IR metrics (recall@k, precision@k, MRR@k, MAP@k, NDCG@k) ported from
Tencent/WeKnora (MIT License) — `internal/application/service/metric/`. Adapted
from Go to Python pure functions; semantics 1:1 with the upstream
implementation, including the multi-GT-set aggregation rule (per-set average
for recall/precision/MRR/MAP; union for NDCG, mirroring WeKnora's choice).

Reference: https://github.com/Tencent/WeKnora
License: MIT (Tencent), 2025

Why pure functions and not a service singleton: these are stateless metric
calculations, used by eval scripts for offline analysis. No DI or runtime state.

Multi-GT-set semantics (kept identical to WeKnora):
- recall/precision/mrr/map: each gt_set is treated as an independent
  "ground-truth aspect"; the metric is computed once per gt_set against the
  same `retrieved` list, then averaged. Most P5/P6 callers will pass a single
  gt_set wrapped in a 1-element outer list.
- ndcg: all gt_sets are unioned into one relevance set before scoring (this
  matches WeKnora's `ndcg.go` implementation).

The `k` parameter (None = use all retrieved) was added uniformly across all
five metrics to align with standard IR notation (recall@k / NDCG@k); WeKnora's
upstream implementation only exposes k on NDCG. Setting k=None reproduces
WeKnora's exact behavior on the other four metrics.
"""

from __future__ import annotations

import math
from collections.abc import Hashable, Sequence


def _normalize_gt_sets(gt_sets: Sequence[Sequence[Hashable]]) -> list[set[Hashable]]:
    """Convert the outer sequence of gt sequences to a list of frozenset-like sets."""
    return [set(gt) for gt in gt_sets]


def _truncate(retrieved: Sequence[Hashable], k: int | None) -> Sequence[Hashable]:
    if k is None or k >= len(retrieved):
        return retrieved
    if k < 0:
        raise ValueError(f"k must be non-negative; got {k}")
    return retrieved[:k]


def recall_at_k(
    gt_sets: Sequence[Sequence[Hashable]],
    retrieved: Sequence[Hashable],
    k: int | None = None,
) -> float:
    """Recall@k averaged across gt_sets.

    For each gt_set, compute |retrieved[:k] ∩ gt_set| / |gt_set|, then average.
    Returns 0.0 if either gt_sets or retrieved is empty.
    """
    sets = _normalize_gt_sets(gt_sets)
    if not sets:
        return 0.0
    truncated = list(_truncate(retrieved, k))
    if not truncated:
        return 0.0

    total = 0.0
    for gt in sets:
        if not gt:
            continue
        hits = sum(1 for x in truncated if x in gt)
        total += hits / len(gt)
    return total / len(sets)


def precision_at_k(
    gt_sets: Sequence[Sequence[Hashable]],
    retrieved: Sequence[Hashable],
    k: int | None = None,
) -> float:
    """Precision@k averaged across gt_sets.

    For each gt_set, compute |retrieved[:k] ∩ gt_set| / |retrieved[:k]|,
    then average. Returns 0.0 if either gt_sets or retrieved is empty.
    """
    sets = _normalize_gt_sets(gt_sets)
    if not sets:
        return 0.0
    truncated = list(_truncate(retrieved, k))
    if not truncated:
        return 0.0

    denom = len(truncated)
    total = 0.0
    for gt in sets:
        hits = sum(1 for x in truncated if x in gt)
        total += hits / denom
    return total / len(sets)


def mrr_at_k(
    gt_sets: Sequence[Sequence[Hashable]],
    retrieved: Sequence[Hashable],
    k: int | None = None,
) -> float:
    """Mean Reciprocal Rank@k averaged across gt_sets.

    For each gt_set, find the 1-indexed position of the first retrieved
    element that is also in gt_set; reciprocal rank = 1/position (or 0 if
    none found within the first k). Returns the mean across gt_sets.
    Returns 0.0 if gt_sets is empty.
    """
    sets = _normalize_gt_sets(gt_sets)
    if not sets:
        return 0.0
    truncated = list(_truncate(retrieved, k))
    if not truncated:
        return 0.0

    total = 0.0
    for gt in sets:
        for i, doc in enumerate(truncated):
            if doc in gt:
                total += 1.0 / (i + 1)
                break
    return total / len(sets)


def map_at_k(
    gt_sets: Sequence[Sequence[Hashable]],
    retrieved: Sequence[Hashable],
    k: int | None = None,
) -> float:
    """Mean Average Precision@k averaged across gt_sets.

    For each gt_set: compute AP by iterating retrieved[:k]; whenever a
    relevant doc is hit at rank j (1-indexed), add (cumulative_hits / j)
    to AP; finally divide AP by the total number of relevant hits found
    in the truncated window. Returns the mean AP across gt_sets.
    Returns 0.0 if gt_sets is empty.
    """
    sets = _normalize_gt_sets(gt_sets)
    if not sets:
        return 0.0
    truncated = list(_truncate(retrieved, k))

    total_ap = 0.0
    for gt in sets:
        ap = 0.0
        hits = 0
        for j, doc in enumerate(truncated):
            if doc in gt:
                hits += 1
                ap += hits / (j + 1)
        if hits > 0:
            ap /= hits
        total_ap += ap
    return total_ap / len(sets)


def ndcg_at_k(
    gt_sets: Sequence[Sequence[Hashable]],
    retrieved: Sequence[Hashable],
    k: int | None = None,
) -> float:
    """Normalized Discounted Cumulative Gain@k.

    Mirrors WeKnora's `ndcg.go` semantics: all gt_sets are UNIONED into a
    single relevance set (unlike the other four metrics which average per-set).
    Binary relevance (1 if doc in any gt_set, 0 otherwise). DCG uses the
    standard log2(i+2) discount; IDCG places all relevant docs first.
    Returns 0.0 if IDCG is 0 (no relevant docs).
    """
    truncated = list(_truncate(retrieved, k))

    # Union all gt sets into a single relevance set; also count total relevant
    # in GT (used to determine IDCG length, mirroring WeKnora upstream).
    relevance_set: set[Hashable] = set()
    total_relevant_in_gt = 0
    for gt in gt_sets:
        total_relevant_in_gt += len(gt)
        relevance_set.update(gt)

    if not truncated or not relevance_set:
        return 0.0

    # DCG: sum (2^rel - 1) / log2(i + 2) for each rank
    dcg = 0.0
    for i, doc in enumerate(truncated):
        rel = 1 if doc in relevance_set else 0
        dcg += (2 ** rel - 1) / math.log2(i + 2)

    # IDCG: ideal ranking has min(total_relevant_in_gt, len(truncated)) ones
    # at the front of the same-length list, zeros after. Each rel=1 contributes
    # 1/log2(i+2) (since (2^1 - 1) = 1).
    ideal_count = min(total_relevant_in_gt, len(truncated))
    idcg = 0.0
    for i in range(ideal_count):
        idcg += 1 / math.log2(i + 2)

    if idcg == 0:
        return 0.0
    return dcg / idcg


__all__ = [
    "recall_at_k",
    "precision_at_k",
    "mrr_at_k",
    "map_at_k",
    "ndcg_at_k",
]
