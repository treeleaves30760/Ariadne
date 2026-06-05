"""Tests for paper importance scoring."""

from __future__ import annotations

from app.services.scoring import importance_score, is_top_venue, max_log_cites


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
