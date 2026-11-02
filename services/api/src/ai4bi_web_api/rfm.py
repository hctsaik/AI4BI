"""Validated RFM input boundary; callers must supply governed, scoped rows."""
from datetime import date
from decimal import Decimal, localcontext
from numbers import Integral, Real

import pandas as pd

from .errors import AppError

ANALYSIS_CONTRACT = "rfm-v1"
MAX_CUSTOMERS = 10000


def settings_identity(body, contracts, settings):
    contract = contracts.get(settings.block_id)
    columns = {c.name: c.data_type.lower() for c in contract.columns} if contract else {}
    allowed = {"customer_column": {"string", "str", "object", "integer", "int", "int32", "int64"},
        "date_column": {"date", "datetime", "timestamp"},
        "monetary_column": {"number", "numeric", "decimal", "float", "float32", "float64", "double", "integer", "int", "int32", "int64"}}
    if (contract is None or contract.block_type.value not in {"fact", "snapshot_fact", "target_fact"}
            or len({getattr(settings, name) for name in allowed}) != 3
            or any(columns.get(getattr(settings, name)) not in types for name, types in allowed.items())):
        raise AppError("RFM_SETTINGS_INCOMPATIBLE", "RFM 來源或欄位型別不相容，請更新設定。", 409)
    try:
        date.fromisoformat(settings.anchor)
    except ValueError as exc:
        raise AppError("RFM_SETTINGS_INCOMPATIBLE", "RFM 截止日不是有效日期。", 409) from exc
    return {"field_types": {name: columns[getattr(settings, name)] for name in allowed}}


def validate_saved_analyses(body, contracts, definitions):
    if not definitions:
        return
    from ai4bi.report.models import ExecutableReportSpec
    report = ExecutableReportSpec.from_dict(body)
    for item in definitions:
        identity = settings_identity(body, contracts, item)
        page = report.pages.get(item.page_id)
        if (page is None or item.selected_component_id and item.selected_component_id not in page.visuals
                or page and not any(item.block_id in v.query.all_block_ids for v in page.visuals.values())
                or item.field_types != identity["field_types"]):
            raise AppError("RFM_SETTINGS_INCOMPATIBLE", "RFM 欄位型別或頁面引用已變更，請更新或刪除設定。", 409)


def run_rfm(root, snapshot):
    from .core import load_contracts
    from .publications import check_execution_runtime
    check_execution_runtime(root, snapshot)
    if snapshot.get("analysis_contract") != ANALYSIS_CONTRACT:
        raise AppError("RFM_INCOMPATIBLE", "RFM 版本已變更，請重新執行。", 409)
    return analyze_snapshot(snapshot, load_contracts(root, snapshot["datasets"]))


def analyze_snapshot(snapshot, contracts):
    from ai4bi.blocks.datastore import materialize_dataframe
    from ai4bi.report.models import ExecutableReportSpec
    from .schemas import RfmSettings
    from .analysis_scope import exploration_context
    from .drilling import validate_snapshot, assistant_drill_executor, assistant_source_contracts
    from .report_extensions import report_executor
    from .core import clean

    if snapshot.get("analysis_contract") != ANALYSIS_CONTRACT:
        raise AppError("RFM_INCOMPATIBLE", "RFM 版本已變更，請重新執行。", 409)
    validate_snapshot(snapshot)
    settings = RfmSettings.model_validate({k: snapshot[k] for k in RfmSettings.model_fields})
    try:
        anchor = date.fromisoformat(settings.anchor)
    except ValueError as exc:
        raise AppError("RFM_SETTINGS_INVALID", "RFM 截止日不是有效日期。") from exc
    page, filters, serialized = exploration_context(snapshot, contracts, analysis="RFM")
    selected = snapshot.get("selected_component_id")
    report = ExecutableReportSpec.from_dict(snapshot["report"])
    bid = settings.block_id
    if page is None or not any(bid in v.query.all_block_ids for v in report.pages[page].visuals.values()):
        raise AppError("INVALID_RFM_CONTEXT", "RFM 來源必須用於目前探索頁面。")
    contract = contracts.get(bid)
    columns = {c.name: c.data_type.lower() for c in contract.columns} if contract else {}
    if (contract is None or contract.block_type.value not in {"fact", "snapshot_fact", "target_fact"}
            or columns.get(settings.customer_column) not in {"string", "str", "object", "integer", "int", "int32", "int64"}
            or columns.get(settings.date_column) not in {"date", "datetime", "timestamp"}
            or columns.get(settings.monetary_column) not in {"number", "numeric", "decimal", "float", "float32", "float64", "double", "integer", "int", "int32", "int64"}):
        raise AppError("RFM_SETTINGS_INVALID", "請選擇有效的客戶、日期與金額欄位。")
    executor, contracts = report_executor(snapshot["report"], contracts, page_id=page, visual_id=selected)
    _, context = assistant_drill_executor(executor, snapshot["report"], contracts, selected, snapshot.get("drill_state", {}))
    if context and context["block_id"] != bid:
        raise AppError("INVALID_RFM_CONTEXT", "RFM 來源必須與鑽取路徑一致。")
    selected_filters = []
    if selected:
        selected_filters = executor._apply_active_filters(report.pages[page].visuals[selected].query, report.merged_filters()).filters
    scoped = assistant_source_contracts(executor, {bid: contracts[bid]}, context,
        extra_filters=[*selected_filters, *filters], preserve_numeric_precision=True)
    result = analyze(materialize_dataframe(scoped[bid]), customer_column=settings.customer_column,
        date_column=settings.date_column, monetary_column=settings.monetary_column, anchor=anchor)
    return clean({**result, "settings": settings.model_dump(), "snapshot_id": snapshot["snapshot_id"],
        "revision": snapshot["revision"], "execution_contract": snapshot["execution_contract"],
        "exploration_page_id": page, "selected_component_id": selected, "drill_context": context,
        "filters": serialized, "applied_filters": [f for f in serialized if f["block_id"] == bid],
        "selected_query_filters": [f for f in selected_filters if f.block_id == bid],
        "filter_bookmark_id": snapshot.get("filter_bookmark_id"),
        "data_versions": {d["dataset_id"]: d["version"] for d in snapshot["datasets"]}})


def _amount(value):
    if isinstance(value, bool) or not isinstance(value, (Real, Decimal)):
        raise AppError("RFM_AMOUNT_INVALID", "RFM 金額必須為有限數值。")
    result = Decimal(str(value))
    if not result.is_finite():
        raise AppError("RFM_AMOUNT_INVALID", "RFM 金額必須為有限數值。")
    if result.adjusted() > 308 or result.as_tuple().exponent < -1000:
        raise AppError("RFM_AMOUNT_INVALID", "RFM 金額超出支援的數值範圍。")
    return result


def _wire(value):
    if value == value.to_integral_value() and abs(value) <= 2**53 - 1:
        return int(value)
    number = float(value)
    if abs(value) <= 2**53 - 1 and Decimal(str(number)) == value:
        return number
    return format(value, "f")


def analyze(rows, *, customer_column, date_column, monetary_column, anchor):
    """Distinct UTC purchase days, explicit cutoff, pinned relative quintiles.

    Missing customer/date rows are counted and excluded. Malformed dates or
    amounts fail, rather than silently changing the customer population.
    Negative spend is retained (net refunds); risk is a relative recency flag,
    not a calibrated churn probability. This function does not load sources.
    """
    from ai4bi.analysis.rfm import compute_rfm

    columns = [customer_column, date_column, monetary_column]
    if (type(anchor) is not date or any(not isinstance(c, str) or not c for c in columns)
            or len(set(columns)) != 3 or not rows.columns.is_unique
            or any(c not in rows.columns for c in columns)):
        raise AppError("RFM_SETTINGS_INVALID", "RFM 需要不同的客戶、日期、金額欄位與固定截止日。")
    work = rows[columns].copy()
    work.columns = ["customer", "day", "amount"]
    missing = work.customer.isna() | work.day.isna()
    missing_count = int(missing.sum())
    work = work.loc[~missing].copy()
    families = set()
    for value in work.customer:
        family = "string" if isinstance(value, str) and value else "integer" if isinstance(value, Integral) and not isinstance(value, bool) else None
        if family is None:
            raise AppError("RFM_CUSTOMER_INVALID", "客戶識別碼必須為非空文字或整數。")
        families.add(family)
    if len(families) > 1:
        raise AppError("RFM_CUSTOMER_INVALID", "客戶識別碼型別不可混用。")
    if any(isinstance(value, (Real, Decimal)) for value in work.day):
        raise AppError("RFM_DATE_INVALID", "購買日期包含無效值。")
    try:
        work["day"] = pd.to_datetime(work.day, errors="raise", format="mixed", utc=True).dt.tz_localize(None).dt.normalize()
    except (ValueError, TypeError, OverflowError) as exc:
        raise AppError("RFM_DATE_INVALID", "購買日期包含無效值。") from exc
    if work.day.isna().any():
        raise AppError("RFM_DATE_INVALID", "購買日期包含無效值。")
    future = work.day > pd.Timestamp(anchor)
    future_count = int(future.sum())
    work = work.loc[~future].copy()
    amounts = [_amount(value) for value in work.amount]
    work["amount"] = amounts
    customers = int(work.customer.nunique())
    if customers > MAX_CUSTOMERS:
        raise AppError("RFM_CUSTOMER_LIMIT", "客戶數超過 10,000，請縮小分析範圍。")
    result = {"analysis_contract": ANALYSIS_CONTRACT, "anchor": anchor.isoformat(),
              "source_rows": len(rows), "included_rows": len(work),
              "excluded_missing_identity_or_date": missing_count, "excluded_after_anchor": future_count,
              "customer_count": customers, "frequency_basis": "distinct_utc_purchase_days",
              "risk_basis": "relative_recency_quintile", "rows": []}
    if not customers:
        return result
    # Enough significant digits for exact sums even with cancellation and scales.
    high = max(v.adjusted() for v in amounts)
    low = min(v.as_tuple().exponent for v in amounts)
    with localcontext() as ctx:
        ctx.prec = max(28, high - low + len(str(len(amounts))) + 3)
        table = compute_rfm(work, "customer", "day", "amount", anchor=anchor)
    if len(table) != customers:
        raise AppError("RFM_RESULT_INVALID", "RFM 核心未回傳完整客戶結果。", 500)
    # Stable customer identity breaks equal-value ties independently of input order.
    table = table.sort_values(["流失風險", "累計金額", "customer"], ascending=[False, False, True])
    for row in table.to_dict("records"):
        customer = row["customer"]
        if isinstance(customer, Integral):
            customer = int(customer)
            if abs(customer) > 2**53 - 1:
                customer = str(customer)
        result["rows"].append({"customer": customer, "last_purchase": row["最近購買"].isoformat(),
            "recency_days": int(row["距今天數"]), "frequency": int(row["購買次數"]),
            "monetary": _wire(row["累計金額"]), "r": int(row["R"]), "f": int(row["F"]),
            "m": int(row["M"]), "segment": row["分群"], "at_risk": bool(row["流失風險"])})
    return result


def settings_command(body, kind, payload, contracts):
    import copy
    from uuid import uuid4
    from pydantic import ValidationError
    from .schemas import RfmSettings
    from .report_extensions import extensions, SavedRfmAnalysis
    action = kind.removesuffix("_rfm_analysis")
    expected = {"save": {"name", "settings", "page_id", "selected_component_id"},
                "update": {"analysis_id", "settings", "page_id", "selected_component_id"},
                "rename": {"analysis_id", "name"}, "delete": {"analysis_id"}}
    if action not in expected or set(payload) != expected[action]:
        raise AppError("INVALID_RFM_SETTINGS", "RFM命令欄位不完整或含額外欄位。")
    extra = extensions(body).model_dump()
    items = extra["rfm_analyses"]
    found = next((item for item in items if item["analysis_id"] == payload.get("analysis_id")), None)
    if action != "save" and found is None:
        raise AppError("RFM_SETTINGS_NOT_FOUND", "找不到RFM設定。", 404)
    if "name" in payload:
        name = payload["name"]
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise AppError("INVALID_RFM_SETTINGS", "RFM名稱須為 1 至 80 字。")
        name = name.strip()
        if any(item is not found and item["name"].casefold() == name.casefold() for item in items):
            raise AppError("DUPLICATE_RFM_SETTINGS", "已有同名RFM設定。")
    if action == "delete":
        items.remove(found)
    elif action == "rename":
        found["name"] = name
    else:
        if action == "save" and len(items) >= 30:
            raise AppError("RFM_SETTINGS_LIMIT", "每份報表最多保存 30 組RFM。")
        try:
            settings = RfmSettings.model_validate(payload["settings"])
            definition = SavedRfmAnalysis.model_validate({**settings.model_dump(),
                "analysis_id": found["analysis_id"] if found else "rfm_" + uuid4().hex,
                "name": found["name"] if found else name, "page_id": payload["page_id"],
                "selected_component_id": payload["selected_component_id"],
                **settings_identity(body, contracts, settings), "analysis_contract": ANALYSIS_CONTRACT})
        except (ValidationError, TypeError) as exc:
            raise AppError("INVALID_RFM_SETTINGS", "RFM設定包含無效參數。") from exc
        validate_saved_analyses(body, contracts, [definition])
        if found is None:
            items.append(definition.model_dump())
        else:
            found.update(definition.model_dump())
    result = copy.deepcopy(body)
    result["web_extensions"] = extra
    return result


def run_saved_analyses(snapshot, contracts):
    from .report_extensions import extensions
    from .bookmarks import exploration_page
    definitions = extensions(snapshot["report"]).rfm_analyses
    validate_saved_analyses(snapshot["report"], contracts, definitions)
    active_page = exploration_page(snapshot["report"], snapshot)
    results = {}
    for item in definitions:
        page = snapshot["report"]["pages"][item.page_id]
        scoped = {**snapshot, **item.model_dump(), "exploration_page_id": item.page_id,
                  "filters": snapshot.get("filters", []) if item.page_id == active_page else [],
                  "drill_state": {vid: state for vid, state in snapshot.get("drill_state", {}).items() if vid in page["visuals"]}}
        results[item.analysis_id] = {**analyze_snapshot(scoped, contracts), "analysis_id": item.analysis_id,
                                   "name": item.name, "page_id": item.page_id, "settings": item.model_dump()}
    delivery_checks(snapshot["report"], {"rfm_analyses": results})
    return results


def _delivery_invalid():
    raise AppError("RFM_DELIVERY_INVALID", "RFM 結果不完整或與保存設定不符，請重新分析。", 409)


def validate_delivery_checks(body, checks):
    from .report_extensions import extensions
    from .storage import digest
    definitions = extensions(body).rfm_analyses
    if not definitions and checks is None:
        return
    if not isinstance(checks, dict) or set(checks) != {d.analysis_id for d in definitions}:
        _delivery_invalid()
    for definition in definitions:
        receipt = checks[definition.analysis_id]
        if (not isinstance(receipt, dict) or receipt.get("analysis_contract") != ANALYSIS_CONTRACT
                or receipt.get("settings_signature") != digest(definition.model_dump())
                or receipt.get("anchor") != definition.anchor
                or type(receipt.get("customer_count")) is not int
                or not 0 <= receipt["customer_count"] <= MAX_CUSTOMERS):
            _delivery_invalid()


def delivery_checks(body, result):
    """Check complete RFM projections; source authorization belongs to execution."""
    from collections import Counter
    import re
    from ai4bi.analysis.rfm import _segment
    from .report_extensions import extensions
    from .storage import digest
    definitions = extensions(body).rfm_analyses
    analyses = result.get("rfm_analyses", {})
    if not isinstance(analyses, dict) or set(analyses) != {d.analysis_id for d in definitions}:
        _delivery_invalid()
    checks = {}
    for definition in definitions:
        if set(definition.field_types) != {"customer_column", "date_column", "monetary_column"}:
            _delivery_invalid()
        item = analyses[definition.analysis_id]
        if (not isinstance(item, dict) or item.get("settings") != definition.model_dump()
                or item.get("analysis_id") != definition.analysis_id or item.get("name") != definition.name
                or item.get("page_id") != definition.page_id or item.get("exploration_page_id") != definition.page_id
                or item.get("selected_component_id") != definition.selected_component_id
                or item.get("analysis_contract") != ANALYSIS_CONTRACT or item.get("anchor") != definition.anchor
                or item.get("frequency_basis") != "distinct_utc_purchase_days"
                or item.get("risk_basis") != "relative_recency_quintile"):
            _delivery_invalid()
        counts = [item.get(k) for k in ("customer_count", "source_rows", "included_rows",
                    "excluded_missing_identity_or_date", "excluded_after_anchor")]
        if any(type(v) is not int or v < 0 for v in counts):
            _delivery_invalid()
        customers, total, included, missing, future = counts
        rows = item.get("rows")
        if (not isinstance(rows, list) or customers != len(rows) or customers > MAX_CUSTOMERS
                or customers > included or included + missing + future != total or (customers == 0) != (included == 0)):
            _delivery_invalid()
        identities, values, days = set(), [], 0
        for row in rows:
            if not isinstance(row, dict):
                _delivery_invalid()
            customer = row.get("customer")
            if not (isinstance(customer, str) and customer or type(customer) is int and abs(customer) <= 2**53 - 1):
                _delivery_invalid()
            integer_identity = definition.field_types["customer_column"] in {"integer", "int", "int32", "int64"}
            if integer_identity:
                if isinstance(customer, str) and (not re.fullmatch(r"-?[1-9]\d*", customer) or abs(int(customer)) <= 2**53 - 1):
                    _delivery_invalid()
                identity = ("integer", int(customer))
            else:
                if not isinstance(customer, str):
                    _delivery_invalid()
                identity = ("string", customer)
            if identity in identities:
                _delivery_invalid()
            identities.add(identity)
            for key in ("recency_days", "frequency", "r", "f", "m"):
                value = row.get(key)
                if type(value) is not int or value < (0 if key == "recency_days" else 1):
                    _delivery_invalid()
            if any(row[k] > 5 for k in ("r", "f", "m")) or type(row.get("at_risk")) is not bool:
                _delivery_invalid()
            try:
                anchor = date.fromisoformat(item["anchor"])
                last = date.fromisoformat(row["last_purchase"])
                if row["last_purchase"] != last.isoformat() or (anchor - last).days != row["recency_days"]:
                    _delivery_invalid()
                raw = row["monetary"]
                if isinstance(raw, str):
                    if not re.fullmatch(r"-?\d+(?:\.\d+)?", raw):
                        _delivery_invalid()
                    amount = _amount(Decimal(raw))
                    if _wire(amount) != raw:
                        _delivery_invalid()
                else:
                    amount = _amount(raw)
                    encoded = _wire(amount)
                    if isinstance(encoded, str):
                        _delivery_invalid()
            except (KeyError, ValueError, TypeError, ArithmeticError, AppError):
                _delivery_invalid()
            values.append(amount)
            days += row["frequency"]
        if days > included:
            _delivery_invalid()
        # Exact average-rank quintiles: ceil(5 * (first+last) / (2*N)).
        def scores(sequence, reverse=False):
            counts = Counter(sequence)
            ranked, first = {}, 1
            for value in sorted(counts):
                last = first + counts[value] - 1
                score = ((first + last) * 5 + 2 * customers - 1) // (2 * customers)
                ranked[value] = 6 - score if reverse else score
                first = last + 1
            return [ranked[value] for value in sequence]
        rs = scores([row["recency_days"] for row in rows], True)
        fs = scores([row["frequency"] for row in rows])
        ms = scores(values)
        for row, r, f, m in zip(rows, rs, fs, ms):
            if ((row["r"], row["f"], row["m"]) != (r, f, m)
                    or row["at_risk"] != (r <= 2) or row.get("segment") != _segment(r, f, m)):
                _delivery_invalid()
        checks[definition.analysis_id] = {"analysis_contract": ANALYSIS_CONTRACT,
            "settings_signature": digest(definition.model_dump()), "anchor": definition.anchor,
            "customer_count": customers}
    validate_delivery_checks(body, checks)
    return checks
