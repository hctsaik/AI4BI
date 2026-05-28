"""Dynamic schema index for NL2 — Round 035.

Builds keyword → (block_id, column, alias, truncate) mappings at runtime from
loaded DataBlockContracts, so NL2 works on any user-uploaded CSV, not just the
hardcoded semiconductor demo.

The index merges:
1. Dynamic entries inferred from column names and metric names in loaded contracts.
2. Common Chinese ↔ English word synonyms for business columns.
3. Static semiconductor-demo entries (kept as fallback, lower priority).

Usage
-----
    from ai4bi.ai.schema_index import SchemaIndex
    idx = SchemaIndex.build(contracts)
    entry = idx.find_dim("門市")    # → {"block_id": "retail_sales", "column_name": "store_name", ...}
    entry = idx.find_metric("收入")  # → {"block_id": "retail_sales", "metric_name": "revenue"}
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from ai4bi.blocks.contracts import BlockType, DataBlockContract

# ---------------------------------------------------------------------------
# Common business column synonym table (EN stem → list of ZH aliases)
# ---------------------------------------------------------------------------

_EN_TO_ZH: dict[str, list[str]] = {
    "store":      ["門市", "店", "商店", "分店", "門店"],
    "shop":       ["門市", "商店"],
    "city":       ["城市", "縣市", "地區", "地點"],
    "region":     ["地區", "區域", "地點", "城市"],
    "category":   ["品類", "分類", "類別", "類型"],
    "product":    ["商品", "產品", "品項"],
    "item":       ["品項", "商品"],
    "channel":    ["通路", "渠道", "銷售管道"],
    "brand":      ["品牌"],
    "vendor":     ["供應商", "廠商"],
    "customer":   ["客戶", "顧客"],
    "date":       ["日期", "時間"],
    "month":      ["月份", "月"],
    "week":       ["週", "星期"],
    "day":        ["日", "天"],
    "revenue":    ["收入", "營收", "銷售額", "業績"],
    "sales":      ["銷售額", "業績", "銷售"],
    "amount":     ["金額", "總額"],
    "quantity":   ["數量", "件數"],
    "count":      ["數量", "次數", "筆數"],
    "order":      ["訂單", "訂購"],
    "profit":     ["利潤", "獲利"],
    "margin":     ["利潤率", "毛利率"],
    "cost":       ["成本", "費用"],
    "return":     ["退貨", "退回"],
    "rate":       ["比率", "比例", "率"],
    "score":      ["分數", "評分"],
    "name":       ["名稱", "名字"],
}

_ZH_TO_EN: dict[str, str] = {}  # built lazily below

# Columns that indicate date granularity dimension
_DATE_COL_HINTS = frozenset({
    "date", "time", "timestamp", "dt", "ts",
    "order_date", "created_at", "event_date", "sale_date",
    "transaction_date", "report_date",
})

_DATE_TRUNCATE_KEYWORDS: dict[str, str] = {
    "month": "month", "月份": "month", "月": "month",
    "week": "week", "週": "week",
    "day": "day", "daily": "day", "日": "day",
    "year": "year", "年": "year",
    "quarter": "quarter", "季": "quarter",
}


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _col_tokens(col_name: str) -> list[str]:
    """Split snake_case or camelCase into lowercase tokens."""
    # split on _ and spaces first
    parts = re.split(r"[_\s]+", col_name.lower())
    return [p for p in parts if p]


def _is_date_col(col_name: str, data_type: str) -> bool:
    if data_type in ("date", "timestamp", "datetime"):
        return True
    tokens = set(_col_tokens(col_name))
    return bool(tokens & {"date", "time", "ts", "dt", "day", "month", "year",
                          "week", "period", "timestamp", "at", "on", "created", "updated"})


def _build_zh_to_en() -> dict[str, str]:
    zh2en: dict[str, str] = {}
    for en, zhs in _EN_TO_ZH.items():
        for zh in zhs:
            if zh not in zh2en:
                zh2en[zh] = en
    return zh2en


# ---------------------------------------------------------------------------
# Entry types
# ---------------------------------------------------------------------------

@dataclass
class DimEntry:
    block_id: str
    column_name: str
    alias: str
    truncate: Optional[str] = None  # 'month' | 'week' | 'day' | None


@dataclass
class MetricEntry:
    block_id: str
    metric_name: str
    alias: str


# ---------------------------------------------------------------------------
# SchemaIndex
# ---------------------------------------------------------------------------

@dataclass
class SchemaIndex:
    """Runtime keyword index built from loaded DataBlockContracts."""
    _dims: dict[str, DimEntry] = field(default_factory=dict)    # keyword → DimEntry
    _metrics: dict[str, MetricEntry] = field(default_factory=dict)  # keyword → MetricEntry

    @classmethod
    def build(cls, contracts: dict[str, DataBlockContract]) -> "SchemaIndex":
        idx = cls()
        zh2en = _build_zh_to_en()

        for block_id, contract in contracts.items():
            if contract.block_type not in (
                BlockType.fact, BlockType.snapshot_fact, BlockType.target_fact,
                BlockType.dimension, BlockType.date_dimension,
            ):
                continue

            for col in contract.columns:
                col_name = col.name
                is_date = _is_date_col(col_name, col.data_type)
                is_string = col.data_type in ("string", "str", "object", "text", "varchar")

                if not (is_date or is_string):
                    continue

                alias = col_name.replace("_", " ").title()
                entry = DimEntry(
                    block_id=block_id,
                    column_name=col_name,
                    alias=alias,
                    truncate="month" if is_date else None,
                )

                # Register the raw column name and its underscore-split tokens
                keywords: list[str] = [col_name.lower(), col_name.replace("_", " ").lower()]
                for tok in _col_tokens(col_name):
                    keywords.append(tok)
                    # EN token → ZH aliases
                    for zh in _EN_TO_ZH.get(tok, []):
                        keywords.append(zh)

                # For date cols, also register granularity keywords
                if is_date:
                    for gran_kw in _DATE_TRUNCATE_KEYWORDS:
                        gran_entry = DimEntry(
                            block_id=block_id,
                            column_name=col_name,
                            alias=gran_kw.title(),
                            truncate=_DATE_TRUNCATE_KEYWORDS[gran_kw],
                        )
                        idx._dims.setdefault(gran_kw, gran_entry)

                for kw in keywords:
                    idx._dims.setdefault(kw, entry)

            # Register metrics
            for metric in contract.metrics:
                m_name = metric.name
                m_alias = m_name.replace("_", " ").title()
                m_entry = MetricEntry(block_id=block_id, metric_name=m_name, alias=m_alias)

                m_keywords: list[str] = [m_name.lower(), m_name.replace("_", " ").lower()]
                for tok in _col_tokens(m_name):
                    m_keywords.append(tok)
                    for zh in _EN_TO_ZH.get(tok, []):
                        m_keywords.append(zh)
                for kw in m_keywords:
                    idx._metrics.setdefault(kw, m_entry)

        return idx

    def find_dim(self, keyword: str) -> Optional[DimEntry]:
        """Look up a dimension by keyword (case-insensitive)."""
        return self._dims.get(keyword.lower()) or self._dims.get(keyword)

    def find_metric(self, keyword: str) -> Optional[MetricEntry]:
        """Look up a metric by keyword (case-insensitive)."""
        return self._metrics.get(keyword.lower()) or self._metrics.get(keyword)

    def best_dim_match(self, prompt: str, normalized: str) -> Optional[DimEntry]:
        """Find the longest-matching dimension keyword in a prompt."""
        best: Optional[DimEntry] = None
        best_len = 0
        for kw, entry in self._dims.items():
            if (kw in normalized or kw in prompt) and len(kw) > best_len:
                best = entry
                best_len = len(kw)
        return best

    def best_metric_match(self, prompt: str, normalized: str) -> Optional[MetricEntry]:
        """Find the longest-matching metric keyword in a prompt."""
        best: Optional[MetricEntry] = None
        best_len = 0
        for kw, entry in self._metrics.items():
            if (kw in normalized or kw in prompt) and len(kw) > best_len:
                best = entry
                best_len = len(kw)
        return best
