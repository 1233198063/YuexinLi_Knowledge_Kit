"""Qualified service-fee compatibility experiment, with an immutable Parent spine.

Owner: integration coder. Remove/reject if source controls or independent review
cannot establish the bounded fee lane. enable_fee_fallback=False restores Parent.
"""
import copy
import importlib.util
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parent
_PARENT_ROOT = _ROOT / 'parent_runtime'
sys.path.insert(0, str(_PARENT_ROOT))
_spec = importlib.util.spec_from_file_location('_fee_compatibility_parent', _PARENT_ROOT / 'solution.py')
_parent = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _parent
_spec.loader.exec_module(_parent)

from fee_fallback import FeeFallback
from percent_display import format_conflicts


class FeeCompatibilityKnowledge:
    def __init__(self, enable_fee_fallback=True, enable_percent_display=True):
        self._fee_fallback = FeeFallback()
        self._enable_fee_fallback = enable_fee_fallback
        self._enable_percent_display = enable_percent_display
        self._spine = _parent.build()

    def __getattr__(self, name):
        # Preserve Parent's inspection surface without changing its receiver.
        return getattr(self._spine, name)

    def ingest(self, snapshot):
        self._fee_fallback.clear()
        return self._spine.ingest(snapshot)

    def answer(self, question, as_of=None):
        # Parent completes its entire answer first, including guards and composition.
        # Historical fallback results never enter Parent's cache or its subrequests.
        original = self._spine.answer(question, as_of)
        if not self._enable_fee_fallback or original.confident or original.sources or original.conflict_note:
            return copy.deepcopy(original)
        q = _parent.normalize_question(str(question).strip())
        selected_date = as_of or _parent.date_in_question(q, self.contexts[-1].date[:4] if self.contexts else None)
        ctx = self._at(selected_date)
        if ctx is None:
            return copy.deepcopy(original)
        raw = self._fee_fallback.answer(self.contexts, ctx, q, selected_date)
        if raw is None:
            return copy.deepcopy(original)
        return _parent.Answer(raw['text'], [_parent.Source(**s) for s in raw['sources']],
                              raw['confident'], raw.get('conflict_note'))

    def conflicts(self):
        original = self._spine.conflicts()
        return format_conflicts(original) if self._enable_percent_display else copy.deepcopy(original)


def build_parent():
    return _parent.build()


def build(enable_fee_fallback=True, enable_percent_display=True):
    return FeeCompatibilityKnowledge(enable_fee_fallback, enable_percent_display)
