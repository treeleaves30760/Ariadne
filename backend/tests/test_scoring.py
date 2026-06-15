"""Tests for paper importance scoring."""

from __future__ import annotations

from app.services.scoring import (
    foundational_score,
    importance_score,
    is_top_venue,
    max_log_cites,
)


def test_is_top_venue():
    assert is_top_venue("Advances in Neural Information Processing Systems")
    assert is_top_venue("NeurIPS 2017")
    assert is_top_venue("CVPR")
    assert not is_top_venue("Some Obscure Workshop")
    assert not is_top_venue(None)


def test_importance_blends_signals():
    mlc = max_log_cites([100, 0, 5])
    high = importance_score(1.0, 100, True, mlc)    # relevant + cited + top venue
    low = importance_score(0.1, 0, False, mlc)      # weak on all
    assert 0.0 <= low < high <= 1.0
    assert high > 0.8


def test_importance_top_venue_bonus():
    mlc = max_log_cites([10, 10])
    with_venue = importance_score(0.5, 10, True, mlc)
    without = importance_score(0.5, 10, False, mlc)
    assert with_venue > without


def test_foundational_score_dominated_by_in_degree():
    mlc = max_log_cites([100, 50, 5])
    hub = foundational_score(10, 10, 50, mlc, False)     # cited by every other paper
    leaf = foundational_score(0, 10, 50, mlc, False)     # same cites, cited by none here
    assert hub > leaf
    assert 0.0 <= leaf < hub <= 1.0


def test_foundational_score_handles_empty_graph():
    # no edges yet (max_in_degree == 0) and no citations → score 0, no divide-by-zero
    assert foundational_score(0, 0, None, 0.0, False) == 0.0
