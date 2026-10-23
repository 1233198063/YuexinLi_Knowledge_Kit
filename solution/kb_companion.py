"""
The companion runtime (companion/, the owner's second build of this assessment, merged unchanged from
github.com/yushengzheng421-cmd/knowledge at the commit in companion/SOURCE_COMMIT) as a specialist.

Its typed handlers (deposits, loans, services, facts, features, product details) answer text questions about
pages it knows well: membership routes, wallets, contact routes, the correction policy, card offers and lists,
unpublished rates, grants, programs. Its answer is used only when this system would answer from text, not from its
rate tables, and one of those handlers produced it - never its generic search or its guards:
- its eight named specialists (SPECIALISTS, measured better on the dev banks outside its own tuning bank) replace
  this system's answer;
- its broad modules, which a fresh blind set (pre-registered, run once) showed worth adding (.836 against .819),
  only for open answer kinds, never its facts module or the general part of its services module, and only when
  their answer holds at least as much of what was asked as this system's (solution.asked_covered): they answer
  any question about a product with what they know of it, a rate table for an FAQ question about the product.
"""
import copy
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "companion"
SPECIALISTS = {"services": ("_join_answer", "_wallet_answer", "_contact_answer", "_policy_correction_answer", "_offer_answer"),
               "loans": ("_cards", "_unpublished", "_grant")}


class Companion:
    def __init__(self):
        for d in (ROOT, ROOT / "parent_runtime"):
            if str(d) not in sys.path:
                sys.path.append(str(d))      # after this system's own folders: its module names never shadow ours
        spec = importlib.util.spec_from_file_location("_companion_solution", ROOT / "solution.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        self.system = module.build()
        self.routes = []                     # specialist handlers that answered during the current call
        self.cache = {}
        for module_name, names in SPECIALISTS.items():
            module = next(m for m in self.system._spine.modules if m.__name__.endswith(module_name))
            for name in names:
                setattr(module, name, self._recording(getattr(module, name), name))
        # its broad handler modules are recorded too (weighed against this system's answer by the caller); its
        # generic search and its guards are still not used
        for module in self.system._spine.modules:
            module.answer = self._recording(module.answer, "module:" + module.__name__)

    def _recording(self, handler, name):
        def call(*args):
            reply = handler(*args)
            if reply:
                self.routes.append(name)
            return reply
        return call

    def ingest(self, snapshot) -> None:
        self.system.ingest(snapshot)
        self.cache.clear()

    def specialist_answer(self, question: str, as_of, broad: bool = True):
        """The companion's answer if one of its handlers produced it, else None. broad=False: only the eight named
        specialist handlers (for questions asking a typed value - a phone number, hours, an address, a branch, a
        date or status, an amount - where its other modules measured worse than this system). Returns (answer,
        named): named is False when only its broad modules answered, which the caller weighs against its own."""
        key = (question, as_of)
        if key not in self.cache:
            self.routes.clear()
            try:
                answer = self.system.answer(question, as_of)
            except Exception:
                answer = None
            self.cache[key] = (answer, tuple(self.routes))
        answer, routes = self.cache[key]
        if answer is None or not routes or not (answer.confident or "_unpublished" in routes):
            return None       # (its "the site doesn't publish that rate" handler answers by declining)
        if "_join_answer" in routes and (OTHER_MEMBERSHIP.search(question) or other_program(question)):
            return None       # "the automatic museum-membership benefit" is not about joining the credit union
        named = [r for r in routes if not r.startswith("module:")]
        modules = {r for r in routes if r.startswith("module:")}
        if not named and (not broad or modules <= {m for m in modules if m.endswith(("facts", "services"))}):
            return None       # its facts module and the general part of its services module (beyond the named
            # specialists) measured worse than this system on every dev bank outside its own tuning bank
        return copy.deepcopy(answer), bool(named)


def other_program(question: str) -> bool:
    """'the Money Makeover's membership eligibility', 'may nonmember employees join Financial Wellness': the
    question is about another named program's eligibility, not about joining the credit union."""
    from kb_search import name_phrases
    return any(not {w.lower() for w in words} & JOIN_WORDS for words in name_phrases(question))


JOIN_WORDS = {"dupaco", "rural", "ideas", "network", "membership", "member", "members", "credit", "union", "join"}
# another organisation's membership, or what members get, is not how to join: its join handler fires on any
# "membership"
OTHER_MEMBERSHIP = re.compile(r"[a-z]-membership\b|\bmembership\s+(?:benefits?|perks?|discounts?)\b", re.I)
