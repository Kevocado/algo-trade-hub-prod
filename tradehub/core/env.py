"""
Explicit, opt-in loading of the developer-local `.env` file.

Why this module exists
----------------------
`load_dotenv()` called with no path walks *upward* from the calling file and
dumps whatever it finds into `os.environ`. For a long time that call sat at
module scope inside library modules (`core/supabase_client.py:12` and nine
others), so merely *importing* anything under `tradehub.*` pulled the
gitignored developer-local `.env` into the process environment. Two
measurable consequences, both of which were real:

* The test suite was not hermetic. A developer's `FRED_API_KEY` decided which
  branch of `alfred_vintages.fetch_vintages` ran, so one commit passed on CI
  (fresh checkout, no `.env`) and failed on a laptop holding one. That is the
  whole explanation for the "order-dependent pre-existing failure" that several
  engineers measured on the same commit in two working trees.
* Every value in that file -- the Supabase service-role key, exchange API keys,
  `FRED_API_KEY` -- was loaded into `os.environ` for the entire session, one
  traceback, `--pdb` session or debug dump away from a transcript.

So the rule this module exists to enforce:

    Importing any `tradehub.*` module has no effect on `os.environ`.

Loading the file is an entrypoint's job and is done explicitly, from
`load_local_env()` below. In production this is a no-op: the container gets
real variables from compose and the image contains no `.env` (the Dockerfile
copies only `tradehub/`, `shared/` and `market_sentiment_tool/backend/`), so
there is nothing to find and the call returns False.

Precedence is `override=False` throughout: a variable already present in the
process environment wins. That is what makes production safe -- a real
container variable is never clobbered by a stale local file -- and it is the
same precedence `shared/config.py` already documents.
"""

from __future__ import annotations

import os
from pathlib import Path

# tradehub/core/env.py -> tradehub/core -> tradehub -> <repo root>
REPO_ROOT = Path(__file__).resolve().parents[2]


def env_path() -> Path:
    """The developer-local dotenv file this repo expects at its root."""
    return REPO_ROOT / ".env"


def load_local_env(*, override: bool = False, env_file: Path | None = None) -> bool:
    """Load the repo-root `.env` into `os.environ` if it exists.

    Call this from a process entrypoint -- the API app, a CLI script, a job --
    and nowhere else. Returns True when the file existed and was read.

    `override=False` (the default) means variables that are already set win, so
    an explicit environment always beats a file. Only a genuine developer-local
    convenience should be reading a file at all; production never does.
    """
    path = env_file if env_file is not None else env_path()
    if not path.is_file():
        return False

    from dotenv import load_dotenv

    load_dotenv(dotenv_path=path, override=override)
    return True


__all__ = ["REPO_ROOT", "env_path", "load_local_env", "os"]
