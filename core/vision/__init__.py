"""Optional visual evidence adapters.

These modules never write archive relations directly. They only provide
ranking/evidence to the review layer unless a higher-level policy explicitly
accepts a candidate.
"""

from .order_visual_ranker import OrderVisualRanker, VisualEvidenceCandidate
from .chinese_clip_adapter import ChineseClipAdapter, SemanticVisualCandidate

__all__ = [
    "OrderVisualRanker",
    "VisualEvidenceCandidate",
    "ChineseClipAdapter",
    "SemanticVisualCandidate",
]

