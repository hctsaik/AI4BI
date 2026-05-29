"""Market-basket affinity — Round 077.

"Which products are bought together?" — pure-pandas co-occurrence over baskets
(rows sharing the same basket key, e.g. customer+date+store), bypassing the
executor's no-self-join limit. Returns the top product pairs by lift.

support(A,B)  = baskets containing both / total baskets
confidence    = baskets with both / baskets with A
lift          = confidence / support(B)   (>1 ⇒ positively associated)
"""

from __future__ import annotations

from itertools import combinations

import pandas as pd


def basket_affinity(
    df: pd.DataFrame,
    product_col: str,
    basket_cols: list[str],
    top_n: int = 15,
    min_baskets: int = 2,
) -> pd.DataFrame:
    """Return top product pairs by lift.

    Columns: [商品A, 商品B, 同買次數, 信心度, 提升度].
    """
    needed = [product_col, *basket_cols]
    if any(c not in df.columns for c in needed):
        return pd.DataFrame()
    work = df[needed].dropna()
    if work.empty:
        return pd.DataFrame()

    # products per basket (unique)
    baskets = work.groupby(basket_cols)[product_col].apply(lambda s: sorted(set(s)))
    baskets = baskets[baskets.apply(len) >= 2]  # only multi-item baskets form pairs
    if baskets.empty:
        return pd.DataFrame()

    # Count item presence across ALL baskets (incl single-item) for support of B.
    all_baskets = work.groupby(basket_cols)[product_col].apply(lambda s: set(s))
    n_all = int(len(all_baskets))
    item_count: dict = {}
    for items in all_baskets:
        for it in items:
            item_count[it] = item_count.get(it, 0) + 1

    pair_count: dict = {}
    for items in baskets:
        for a, b in combinations(items, 2):
            key = tuple(sorted((a, b)))
            pair_count[key] = pair_count.get(key, 0) + 1

    rows = []
    for (a, b), co in pair_count.items():
        if co < min_baskets:
            continue
        conf = co / item_count.get(a, 1)            # P(B|A)
        support_b = item_count.get(b, 1) / n_all     # P(B)
        lift = conf / support_b if support_b else 0.0
        rows.append({"商品A": a, "商品B": b, "同買次數": co,
                     "信心度": round(conf, 2), "提升度": round(lift, 2)})
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows).sort_values(["提升度", "同買次數"], ascending=False)
    return out.head(top_n).reset_index(drop=True)
