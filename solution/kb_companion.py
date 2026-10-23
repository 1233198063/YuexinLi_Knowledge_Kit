"""
The companion runtime (companion/, the owner's second build of this assessment, merged unchanged from
github.com/yushengzheng421-cmd/knowledge at the commit in companion/SOURCE_COMMIT) as a specialist.

Measured on every development bank, handler by handler, it beats this system on a few kinds of page:
membership routes and application links, mobile wallets, contact routes, the privacy policy's correction
procedure, card offers, the list of credit cards, rates the site doesn't publish (share-secured, construction
loans) and the homebuyer grants. It is weaker everywhere else, including fees, branches, mortgages and generic
search. So only answers from those handlers are used, and only for questions this system answers from text,
not from its rate tables. Handlers with evidence only on the companion's own tuning bank are left out.
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

    def specialist_answer(self, question: str, as_of):
        """The companion's answer if one of its specialist handlers produced it, else None."""
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
        if "_join_answer" in routes and OTHER_MEMBERSHIP.search(question):
            return None       # "the automatic museum-membership benefit" is not about joining the credit union
        return copy.deepcopy(answer)


# another organisation's membership, or what members get, is not how to join: its join handler fires on any
# "membership"
OTHER_MEMBERSHIP = re.compile(r"[a-z]-membership\b|\bmembership\s+(?:benefits?|perks?|discounts?)\b", re.I)
