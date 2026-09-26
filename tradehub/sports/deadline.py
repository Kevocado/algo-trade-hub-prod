"""The scan-budget rule, in one place.

The orchestrator, the feed client and the reviewer all spend the same budget, so the question
"how much time is left?" and "is it still worth an OpenRouter call?" must have one answer. A
second copy of the 60-second margin in the reviewer would drift from the orchestrator's, and the
drift would be invisible.
"""

from __future__ import annotations

import time
from typing import Callable

# Stop spending the remaining scan budget on LLM calls once this little is left. Reviewing is
# the optional part of the sports step; the edges are already computed and get written either
# way, just with tier=unreviewed.
REVIEW_STOP_MARGIN_SECONDS = 60
# Floor for a clamped HTTP timeout, so a request that is about to be abandoned still gets a
# positive timeout instead of failing as a programming error.
MIN_TIMEOUT_SECONDS = 1.0

# Indirected through a module global so tests can drive a clock without monkeypatching the
# stdlib `time` module out from under everything else running in the process.
_clock: Callable[[], float] = time.monotonic


def remaining_seconds(deadline: float, clock: Callable[[], float] | None = None) -> float:
    """Seconds left before `deadline`; negative once it has passed.

    `clock` is injectable so a caller that owns its own clock (the ALFRED fetcher, which passes
    one down for testability) does not have to reach into this module's global.
    """
    return deadline - (clock or _clock)()


def should_review(deadline: float) -> bool:
    """Whether there is enough of the scan budget left to spend on reviewer calls.

    `>=`, not `>`: the margin is a floor on the time a call may consume, so exactly 60s left is
    still enough for one call. With `>`, a call landing exactly on the boundary was skipped and
    the edge silently read `unreviewed`.
    """
    return remaining_seconds(deadline) >= REVIEW_STOP_MARGIN_SECONDS


def clamp_timeout(timeout: float, deadline: float | None, floor: float = MIN_TIMEOUT_SECONDS) -> float:
    """Never let a request's own timeout outlive the scan budget.

    A configured 60s OpenRouter timeout is fine with 10 minutes left and fatal with 20 seconds
    left: the call would sit there past the deadline once per candidate.
    """
    if deadline is None:
        return timeout
    return min(timeout, max(floor, remaining_seconds(deadline)))
