"""Offline, independently labeled S4 evaluation; no paid/model calls."""
from .contracts import digest, split_digest
from .evaluate import evaluate, validate_promotion, validate_report

__all__ = ["digest", "split_digest", "evaluate", "validate_promotion", "validate_report"]
