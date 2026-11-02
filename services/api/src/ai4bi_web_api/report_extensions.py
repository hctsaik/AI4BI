"""Versioned report-local calculations; immutable source contracts remain unchanged."""
from __future__ import annotations

import copy
import math
import re
from uuid import uuid4
from typing import Literal
from pydantic import ConfigDict, Field, FiniteFloat, model_validator
from ai4bi.blocks.contracts import MetricDefinition, DisaggregationMethod
from ai4bi.query_spec import BlockRef, MetricRef, VisualQuerySpec
from .schemas import StrictModel, SpcSettings, CommonalitySettings, CrossFactSettings, ChangeSettings, RfmSettings
from .errors import AppError
from .bookmarks import Bookmark
from .filters import PersistentCondition, ScopedExecutor, condition_leaves, validate_references, prune_removed_filters


class Calculation(StrictModel):
    block_id: str = Field(min_length=1, max_length=100)
    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
    formula: str = Field(min_length=1, max_length=2000)


class ParameterRange(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    minimum: FiniteFloat
    maximum: FiniteFloat
    step: FiniteFloat

    @model_validator(mode="after")
    def valid_range(self):
        span = self.maximum - self.minimum
        if not math.isfinite(span) or span <= 0 or not 0 < self.step <= span or not math.isfinite(span / self.step):
            raise ValueError("參數範圍必須由小至大，步長須大於零且不超過範圍。")
        return self


class Scenario(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    scenario_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    name: str = Field(min_length=1, max_length=80)
    parameters: dict[str, FiniteFloat] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def valid_scenario(self):
        if self.name != self.name.strip() or not self.name.strip():
            raise ValueError("情境名稱不得空白或含頭尾空白。")
        if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name) for name in self.parameters):
            raise ValueError("Invalid scenario parameter name")
        return self


class SavedSpcAnalysis(SpcSettings):
    analysis_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    name: str = Field(min_length=1, max_length=80)
    page_id: str = Field(min_length=1, max_length=100)
    selected_component_id: str | None = Field(default=None, min_length=1, max_length=100)
    entity_type: str = Field(min_length=1, max_length=100)
    value_type: str = Field(min_length=1, max_length=100)
    analysis_contract: Literal["spc-entity-v2"] = "spc-entity-v2"

    @model_validator(mode="after")
    def valid_name(self):
        if self.name != self.name.strip() or not self.name.strip():
            raise ValueError("SPC 名稱不得空白或含頭尾空白。")
        return self


class SavedCommonalityAnalysis(CommonalitySettings):
    analysis_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    name: str = Field(min_length=1, max_length=80)
    page_id: str = Field(min_length=1, max_length=100)
    selected_component_id: str | None = Field(default=None, min_length=1, max_length=100)
    field_types: dict[str, str] = Field(min_length=4, max_length=4)
    analysis_contract: Literal["commonality-v1"] = "commonality-v1"

    @model_validator(mode="after")
    def valid_name(self):
        if self.name != self.name.strip() or not self.name.strip():
            raise ValueError("Commonality 名稱不得空白或含頭尾空白。")
        return self


class SavedCrossFactAnalysis(CrossFactSettings):
    analysis_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    name: str = Field(min_length=1, max_length=80)
    page_id: str = Field(min_length=1, max_length=100)
    selected_component_id: str | None = Field(default=None, min_length=1, max_length=100)
    field_types: dict[str, dict[str, str]] = Field(min_length=2, max_length=2)
    analysis_contract: Literal["crossfact-v1"] = "crossfact-v1"

    @model_validator(mode="after")
    def valid_name(self):
        if self.name != self.name.strip() or not self.name.strip():
            raise ValueError("跨表分析名稱不得空白或含頭尾空白。")
        return self


class SavedChangeAnalysis(ChangeSettings):
    analysis_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    name: str = Field(min_length=1, max_length=80)
    page_id: str = Field(min_length=1, max_length=100)
    selected_component_id: str | None = Field(default=None, min_length=1, max_length=100)
    field_types: dict[str, str] = Field(min_length=2, max_length=2)
    metric_signature: str = Field(pattern=r"^[a-f0-9]{64}$")
    analysis_contract: Literal["change-v2"] = "change-v2"

    @model_validator(mode="after")
    def valid_name(self):
        if self.name != self.name.strip() or not self.name.strip():
            raise ValueError("變化拆解名稱不得空白或含頭尾空白。")
        return self


class SavedRfmAnalysis(RfmSettings):
    analysis_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    name: str = Field(min_length=1, max_length=80)
    page_id: str = Field(min_length=1, max_length=100)
    selected_component_id: str | None = Field(default=None, min_length=1, max_length=100)
    field_types: dict[str, str] = Field(min_length=3, max_length=3)
    analysis_contract: Literal["rfm-v1"] = "rfm-v1"

    @model_validator(mode="after")
    def valid_name(self):
        if self.name != self.name.strip() or not self.name.strip():
            raise ValueError("RFM名稱不得空白或含頭尾空白。")
        return self


class ReportExtensions(StrictModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal[1] = 1
    parameters: dict[str, FiniteFloat] = Field(default_factory=dict, max_length=50)
    parameter_ranges: dict[str, ParameterRange] = Field(default_factory=dict, max_length=50)
    scenarios: list[Scenario] = Field(default_factory=list, max_length=30)
    spc_analyses: list[SavedSpcAnalysis] = Field(default_factory=list, max_length=30)
    commonality_analyses: list[SavedCommonalityAnalysis] = Field(default_factory=list, max_length=30)
    crossfact_analyses: list[SavedCrossFactAnalysis] = Field(default_factory=list, max_length=30)
    change_analyses: list[SavedChangeAnalysis] = Field(default_factory=list, max_length=30)
    rfm_analyses: list[SavedRfmAnalysis] = Field(default_factory=list, max_length=30)
    bookmarks: list[Bookmark] = Field(default_factory=list, max_length=30)
    persistent_filters: list[PersistentCondition] = Field(default_factory=list,max_length=100)
    calculated_metrics: list[Calculation] = Field(default_factory=list, max_length=50)
    page_order: list[str] | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def parameter_names(self):
        if len({i.analysis_id for i in self.rfm_analyses}) != len(self.rfm_analyses) or len({i.name.casefold() for i in self.rfm_analyses}) != len(self.rfm_analyses):
            raise ValueError("Duplicate RFM names or identifiers")
        if len({item.analysis_id for item in self.change_analyses}) != len(self.change_analyses) or len({item.name.casefold() for item in self.change_analyses}) != len(self.change_analyses):
            raise ValueError("變化拆解設定識別碼與名稱不可重複。")
        if len({item.analysis_id for item in self.crossfact_analyses}) != len(self.crossfact_analyses) or len({item.name.casefold() for item in self.crossfact_analyses}) != len(self.crossfact_analyses):
            raise ValueError("跨表分析設定識別碼與名稱不可重複。")
        if len({item.analysis_id for item in self.commonality_analyses}) != len(self.commonality_analyses) or len({item.name.casefold() for item in self.commonality_analyses}) != len(self.commonality_analyses):
            raise ValueError("Commonality IDs and names must be unique")
        if len({item.analysis_id for item in self.spc_analyses}) != len(self.spc_analyses) or len({item.name.casefold() for item in self.spc_analyses}) != len(self.spc_analyses):
            raise ValueError("SPC 設定識別碼與名稱不可重複。")
        if len({item.filter_id for item in self.persistent_filters}) != len(self.persistent_filters):
            raise ValueError("持久篩選識別碼不可重複。")
        if sum(len(condition_leaves(item)) for item in self.persistent_filters)>100:
            raise ValueError("持久篩選含群組內條件最多 100 個。")
        if len({item.bookmark_id for item in self.bookmarks}) != len(self.bookmarks) or len({item.name.casefold() for item in self.bookmarks}) != len(self.bookmarks):
            raise ValueError("書籤識別碼與名稱不可重複。")
        if len({item.scenario_id for item in self.scenarios}) != len(self.scenarios) or len({item.name.casefold() for item in self.scenarios}) != len(self.scenarios):
            raise ValueError("情境識別碼與名稱不可重複。")
        if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", name) for name in self.parameters):
            raise ValueError("Invalid parameter name")
        for name, limits in self.parameter_ranges.items():
            if name not in self.parameters or not limits.minimum <= self.parameters[name] <= limits.maximum:
                raise ValueError("範圍必須對應既有參數，且參數值須在範圍內。")
        return self


def extensions(body: dict) -> ReportExtensions:
    extra = ReportExtensions.model_validate(body.get("web_extensions", {}))
    if extra.page_order is not None and (len(extra.page_order) != len(set(extra.page_order)) or set(extra.page_order) != set(body.get("pages", {}))):
        raise AppError("INVALID_PAGE_ORDER", "頁面順序必須完整包含所有頁面且不可重複。")
    return extra


def ordered_report(body: dict) -> dict:
    order = extensions(body).page_order
    return {**body, "pages": {key: body["pages"][key] for key in order}} if order is not None else body


def scenario_command(body: dict, kind: str, payload: dict) -> dict:
    expected = {"name"} if kind == "save_scenario" else {"scenario_id", "name"} if kind == "rename_scenario" else {"scenario_id"}
    if set(payload) != expected:
        raise AppError("INVALID_SCENARIO", "情境命令欄位不完整或含有額外欄位。")
    extra = extensions(body).model_dump()
    scenarios = extra["scenarios"]
    item = next((item for item in scenarios if item["scenario_id"] == payload.get("scenario_id")), None)
    if kind != "save_scenario" and item is None:
        raise AppError("SCENARIO_NOT_FOUND", "找不到此情境。", 404)
    if kind in ("save_scenario", "rename_scenario"):
        name = payload["name"]
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
            raise AppError("INVALID_SCENARIO", "情境名稱須為 1 至 80 字。")
        name = name.strip()
        if any(other is not item and other["name"].casefold() == name.casefold() for other in scenarios):
            raise AppError("DUPLICATE_SCENARIO", "已有相同名稱的情境，請使用更新操作或其他名稱。")
    if kind in ("save_scenario", "update_scenario") and not extra["parameters"]:
        raise AppError("INVALID_SCENARIO", "請先建立參數再保存情境。")
    if kind == "save_scenario":
        if len(scenarios) >= 30:
            raise AppError("SCENARIO_LIMIT", "每份報表最多保存 30 組參數情境。")
        scenarios.append({"scenario_id":"scenario_" + uuid4().hex,"name":name,"parameters":dict(extra["parameters"])})
    elif kind == "rename_scenario":
        item["name"] = name
    elif kind == "update_scenario":
        item["parameters"] = dict(extra["parameters"])
    elif kind == "delete_scenario":
        scenarios.remove(item)
    elif kind == "apply_scenario":
        for key, value in item["parameters"].items():
            limits = extra["parameter_ranges"].get(key)
            if key not in extra["parameters"] or (limits and not limits["minimum"] <= value <= limits["maximum"]):
                raise AppError("SCENARIO_INCOMPATIBLE", "情境包含已刪除的參數或超出目前範圍的數值；請以目前值更新情境。", 409)
        extra["parameters"].update(item["parameters"])
    else:
        raise AppError("INVALID_SCENARIO", "不支援的情境操作。")
    result = copy.deepcopy(body)
    result["web_extensions"] = extra
    return result


def duplicate_page(body: dict, page_id) -> dict:
    if not isinstance(page_id, str) or page_id not in body["pages"]:
        raise AppError("INVALID_PAGE", "找不到要複製的頁面。")
    source = body["pages"][page_id]
    if len(body["pages"]) >= 30 or sum(len(page["visuals"]) for page in body["pages"].values()) + len(source["visuals"]) > 100:
        raise AppError("REPORT_LIMIT", "複製後將超過報表頁數或圖表數量上限。")
    result = copy.deepcopy(body)
    extra = extensions(body).model_dump()
    order = list(extra["page_order"] or body["pages"])
    new_id = "page_" + uuid4().hex
    page = copy.deepcopy(source)
    page["page_id"] = new_id
    names = {item.get("display_name") or item["title"] for item in body["pages"].values()}
    original_name = (source.get("display_name") or source["title"])[:135]
    name, index = original_name + " 副本", 2
    while name in names:
        name = f"{original_name} 副本 {index}"
        index += 1
    page["title"] = page["display_name"] = name
    replacements = {vid:"visual_" + uuid4().hex for vid in page["visuals"]}
    page["visuals"] = {replacements[vid]:visual for vid, visual in page["visuals"].items()}
    page["visual_order"] = [replacements[vid] for vid in source["visual_order"]]
    for vid, visual in page["visuals"].items():
        visual["component_id"] = visual["query"]["spec_id"] = vid
    result["pages"][new_id] = page
    copies = []
    for item in extra["persistent_filters"]:
        if item["page_id"] == page_id:
            copied = copy.deepcopy(item)
            copied.update(filter_id="filter_"+uuid4().hex,page_id=new_id)
            if copied["visual_id"]:
                copied["visual_id"] = replacements[copied["visual_id"]]
            copies.append(copied)
    extra["persistent_filters"].extend(copies)
    for collection, prefix in (("spc_analyses", "spc"), ("commonality_analyses", "commonality"), ("crossfact_analyses", "crossfact"), ("change_analyses", "change"), ("rfm_analyses", "rfm")):
        names = {item["name"].casefold() for item in extra[collection]}
        for item in list(extra[collection]):
            if item["page_id"] != page_id:
                continue
            if len(extra[collection]) >= 30:
                raise AppError(prefix.upper() + "_SETTINGS_LIMIT", "複製後將超過每份報表同類分析 30 組設定上限。")
            copied = copy.deepcopy(item)
            stem, index = item["name"][:65] + " 副本", 2
            name = stem
            while name.casefold() in names:
                name = f"{stem} {index}"
                index += 1
            names.add(name.casefold())
            copied.update(analysis_id=prefix + "_" + uuid4().hex, name=name, page_id=new_id,
                          selected_component_id=replacements.get(item["selected_component_id"]))
            extra[collection].append(copied)
    order.insert(order.index(page_id)+1, new_id)
    extra["page_order"] = order
    result["web_extensions"] = extra
    return result


def report_executor(body: dict, contracts: dict, *, validate_calculations=False, page_id=None, visual_id=None):
    from .filters import validate_aggregate_filters
    validate_aggregate_filters(body)
    extra = extensions(body)
    from .spc import validate_saved_analyses
    validate_saved_analyses(body, contracts, extra.spc_analyses)
    from .commonality import validate_saved_analyses as validate_commonality
    validate_commonality(body, contracts, extra.commonality_analyses)
    from .crossfact import validate_saved_analyses as validate_crossfact
    validate_crossfact(body, contracts, extra.crossfact_analyses)
    from .change_analysis import validate_saved_analyses as validate_change
    validate_change(body, contracts, extra.change_analyses)
    from .rfm import validate_saved_analyses as validate_rfm
    validate_rfm(body, contracts, extra.rfm_analyses)
    enriched = {key: value.model_copy(update={"metrics": list(value.metrics)}) for key, value in contracts.items()}
    for item in extra.calculated_metrics:
        contract = enriched.get(item.block_id)
        if contract is None:
            raise AppError("SOURCE_UNAVAILABLE", "計算指標引用了不存在的資料來源。")
        if any(metric.name == item.name for metric in contract.metrics):
            raise AppError("DUPLICATE_METRIC", "計算指標名稱與現有指標重複。")
        contract.metrics.append(MetricDefinition(name=item.name, formula=item.formula,
            disaggregation_method=DisaggregationMethod.none, description="Report calculation"))
    validate_references(body,enriched,extra.persistent_filters)
    from .comparison import ComparisonExecutor
    executor = ScopedExecutor(ComparisonExecutor(extra_contracts=enriched, parameters=extra.parameters),body,extra.persistent_filters,page_id,visual_id)
    if validate_calculations:
        for item in extra.calculated_metrics:
            executor.run(VisualQuerySpec("validate_calculation", [BlockRef(item.block_id)],
                                        metrics=[MetricRef(item.block_id, item.name)]))
    return executor, enriched


def prune_removed_content(body: dict, source: dict) -> dict:
    body = prune_removed_filters(body, source)
    extra = body.get("web_extensions", {})
    removed = set(source["pages"]) - set(body["pages"])
    for collection in ("spc_analyses", "commonality_analyses", "crossfact_analyses", "change_analyses", "rfm_analyses"):
        if collection in extra:
            extra[collection] = [item for item in extra[collection] if item.get("page_id") not in removed]
    return body


def preserve_extensions(body: dict, source: dict) -> dict:
    if "web_extensions" in source:
        extra = extensions(source).model_dump()
        if extra["page_order"] is not None:
            existing = extra["page_order"]
            extra["page_order"] = [key for key in existing if key in body["pages"]] + [key for key in body["pages"] if key not in existing]
        body["web_extensions"] = extra
    return prune_removed_content(body,source)
