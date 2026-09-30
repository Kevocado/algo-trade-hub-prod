"""Guards for the v2 spec §9 cuts: what was deleted stays deleted, and nothing imports it."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODE = [p for p in (ROOT / "tradehub").rglob("*.py") if "__pycache__" not in p.parts]


def test_the_finbert_sentiment_filter_is_gone_and_nothing_imports_it():
    assert not (ROOT / "tradehub/core/sentiment_filter.py").exists()
    offenders = []
    for path in CODE:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            if any("sentiment_filter" in n or n.split(".")[0] in {"transformers", "torch"} for n in names):
                offenders.append(f"{path.relative_to(ROOT)}: {names}")
    assert not offenders, offenders



def test_the_feature_contract_still_lists_the_neutral_news_column():
    # The column stays so stored model feature lists still line up; it is constant 0.0 (no news source).
    source = (ROOT / "tradehub/core/feature_engineering.py").read_text(encoding="utf-8")
    assert "'hourly_news_sentiment'," in source and "df['hourly_news_sentiment'] = 0.0" in source
