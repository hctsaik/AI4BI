"""Report exports from the same accepted snapshot, without silent query skips."""
from __future__ import annotations

import json
import csv
import io
import zipfile
from importlib.metadata import version
from pathlib import Path
import re
import textwrap

import pandas as pd
from .core import run_query
from .errors import AppError


def export_suffix(format):
    return "csv.zip" if format == "csv" else format


def apply_cartesian_format(ax, settings, horizontal=False):
    baseline = settings.get("baseline")
    if baseline:
        if baseline["status"] == "ready":
            draw = ax.axvline if horizontal else ax.axhline
            draw(baseline["value"], color="#e45756", linestyle=":", linewidth=2)
        ax.set_title(baseline["label"] if baseline["status"] == "ready" else baseline["reason"], parse_math=False)
    ax.set_xlabel(settings["y_title"] if horizontal else settings["x_title"], parse_math=False)
    ax.set_ylabel(settings["x_title"] if horizontal else settings["y_title"], parse_math=False)
    if horizontal:
        ax.set_xscale(settings["y_scale"])
        ax.set_xlim(left=settings["y_min"], right=settings["y_max"])
    else:
        ax.set_yscale(settings["y_scale"])
        ax.set_ylim(bottom=settings["y_min"], top=settings["y_max"])
    if settings["show_legend"]:
        placement = {"top": ("lower center", (.5, 1.02)), "bottom": ("upper center", (.5, -.2)),
                     "left": ("upper right", (-.1, 1)), "right": ("upper left", (1.02, 1))}
        location, anchor = placement[settings["legend_position"]]
        legend = ax.legend(loc=location, bbox_to_anchor=anchor)
        for text in legend.get_texts():
            text.set_parse_math(False)


def pdf_bars(ax, bar, settings, style):
    horizontal = bar["orientation"] == "horizontal"
    mode = bar["mode"]
    count = len(bar["series"])
    width = .8 / max(1, count) if mode == "group" else .8
    bases = [0.] * len(bar["categories"])
    colors = ["#2874a6", "#20a397", "#e7a645", "#735da8", "#c56574", "#5d8290"]
    for index, series in enumerate(bar["series"]):
        positions, values, starts = [], [], []
        for point in series["points"]:
            category, value = point["category_index"], point["value"]
            positions.append(category - .4 + width*(index+.5) if mode == "group" else category)
            values.append(value if value is not None else float("nan"))
            starts.append(bases[category] if mode == "stack" else 0.)
            if mode == "stack" and value is not None:
                bases[category] += value
        color = colors[index % len(colors)] if bar["grouped"] else style.get("extra", {}).get("color", style.get("extra", {}).get("bar_color", colors[index % len(colors)]))
        options = dict(label=series["name"], color=color, edgecolor="white", linewidth=.6, alpha=.65 if mode == "overlay" else 1)
        bars = ax.barh(positions, values, height=width, left=starts, **options) if horizontal else ax.bar(positions, values, width=width, bottom=starts, **options)
        if settings["data_labels"]:
            ax.bar_label(bars, labels=[settings["labels"][series["metric_key"]][p["row_index"]] for p in series["points"]], padding=3)
    labels = [c["label"] for c in bar["categories"]]
    if horizontal:
        ax.set_yticks(range(len(labels)), labels)
    else:
        ax.set_xticks(range(len(labels)), labels)
        ax.tick_params(axis="x", rotation=45)
    apply_cartesian_format(ax, settings, horizontal)


def export_tables(result):
    from .pivot import matrix_tables
    for vid, visual in result["visuals"].items():
        if visual.get("pivot"):
            for table in matrix_tables(visual):
                yield vid, table
        else:
            yield vid, visual


def spc_tables(snapshot, result):
    """A common complete table projection for every export format."""
    for aid, analysis in result.get("spc_analyses", {}).items():
        metadata = {**analysis["settings"], "status": analysis["status"], "notice": analysis["notice"],
            **{key: analysis[key] for key in ("entity_count", "input_rows", "used_rows", "excluded_rows", "snapshot_id", "revision", "execution_contract")},
            "outlier_count": len(analysis["outliers"]["rows"]),
            **{key: (analysis["limits"] or {}).get(key) for key in ("mean", "sigma", "ucl", "lcl")},
            **{key: json.dumps(analysis.get(key), ensure_ascii=False) for key in
               ("data_versions", "filters", "applied_filters", "selected_query_filters", "drill_context", "filter_bookmark_id")},
            "persistent_filters": json.dumps(snapshot["report"].get("web_extensions", {}).get("persistent_filters", []), ensure_ascii=False),
            "global_filters": json.dumps(snapshot["report"].get("global_filters", {}), ensure_ascii=False)}
        yield aid, "summary", {"columns": ["field", "value"], "rows": [{"field": key, "value": value} for key, value in metadata.items()]}
        yield aid, "points", {"columns": ["entity", "value"], "rows": analysis["points"]}
        yield aid, "outliers", analysis["outliers"]


def commonality_tables(snapshot, result):
    """Complete, format-neutral commonality metadata and statistical rows."""
    for aid, analysis in result.get("commonality_analyses", {}).items():
        metadata = {**analysis["settings"],
            **{key: analysis[key] for key in ("status", "notice", "analysis_contract", "population_count",
                "qualifying_count", "comparison_count", "unmeasured_group_count", "unexposed_group_count",
                "excluded_detail_rows", "excluded_outcome_rows", "snapshot_id", "revision", "execution_contract")},
            **{key: analysis.get(key) for key in ("data_versions", "filters", "applied_filters",
                "selected_query_filters", "drill_context", "filter_bookmark_id")},
            "persistent_filters": snapshot["report"].get("web_extensions", {}).get("persistent_filters", []),
            "global_filters": snapshot["report"].get("global_filters", {}),
            "p_value_note": "One-sided Fisher; rounded to 4 decimals; no multiple-testing correction; association is not causation."}
        metadata = {key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
                    for key, value in metadata.items()}
        yield aid, "summary", {"columns": ["field", "value"],
                               "rows": [{"field": key, "value": value} for key, value in metadata.items()]}
        yield aid, "entities", {"columns": ["entity", "qualifying_count", "coverage_percent", "lift", "p_value"],
                                "rows": analysis["rows"]}


def crossfact_tables(snapshot, result):
    """Complete cross-fact projections shared by CSV, Excel and PDF."""
    for aid, analysis in result.get("crossfact_analyses", {}).items():
        metadata = {**analysis["settings"], **{key: analysis[key] for key in (
            "analysis_contract", "status", "field_types", "sources", "aligned_count", "paired_count",
            "missing_pair_count", "zero_denominator_count", "correlation_status", "cohort_status",
            "requested_quantiles", "actual_quantiles", "notice", "snapshot_id", "revision", "execution_contract",
            "data_versions", "filters", "applied_filters", "selected_query_filters", "drill_context", "filter_bookmark_id")},
            "persistent_filters": snapshot["report"].get("web_extensions", {}).get("persistent_filters", []),
            "global_filters": snapshot["report"].get("global_filters", {})}
        metadata = {key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
                    for key, value in metadata.items()}
        yield aid, "summary", {"columns": ["field", "value"],
                               "rows": [{"field": key, "value": value} for key, value in metadata.items()]}
        yield aid, "aligned", {"columns": ["key", "a", "b", "result"], "rows": analysis["rows"]}
        yield aid, "correlation", {"columns": ["status", "r", "n", "direction", "strength"],
                                   "rows": [{"status": analysis["correlation_status"],
                                             **(analysis["correlation"] or {"r": None, "n": analysis["paired_count"],
                                                                          "direction": None, "strength": None})}]}
        yield aid, "cohorts", {"columns": ["bucket", "range", "count", "mean_b"], "rows": analysis["cohorts"]}


def rfm_tables(snapshot, result):
    for aid, analysis in result.get("rfm_analyses", {}).items():
        metadata = {**analysis["settings"], **{key: value for key, value in analysis.items() if key not in {"settings", "rows"}},
            "persistent_filters": snapshot["report"].get("web_extensions", {}).get("persistent_filters", []),
            "global_filters": snapshot["report"].get("global_filters", {})}
        yield aid, "summary", {"columns": ["field", "value"], "rows": [
            {"field": key, "value": json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value}
            for key, value in metadata.items()]}
        yield aid, "customers", {"columns": ["customer", "last_purchase", "recency_days", "frequency", "monetary",
                                             "r", "f", "m", "segment", "at_risk"], "rows": analysis["rows"]}


def pdf_rfm_pages(pdf, snapshot, result, footer):
    for aid, part, table in rfm_tables(snapshot, result):
        analysis = result["rfm_analyses"][aid]
        frame = pd.DataFrame(table["rows"], columns=table["columns"])
        if frame.empty:
            frame = pd.DataFrame([{"status": "目前範圍沒有可分析客戶", "anchor": analysis["anchor"]}])
        pdf_table_pages(pdf, frame, f"RFM · {analysis['name']} | {part}", f"{footer} | {aid}")


def change_tables(snapshot, result):
    """Complete change-v2 values; keep decimal strings intact in every format."""
    for aid, analysis in result.get("change_analyses", {}).items():
        metadata = {**analysis["settings"], **{key: analysis[key] for key in (
            "status", "anchor", "windows", "additive", "group_count", "overall_current", "overall_previous",
            "overall_delta", "timezone", "metric_formula", "metric_unit", "notice", "snapshot_id", "revision",
            "execution_contract", "data_versions", "filters", "drill_context", "filter_bookmark_id")},
            "persistent_filters": snapshot["report"].get("web_extensions", {}).get("persistent_filters", []),
            "global_filters": snapshot["report"].get("global_filters", {})}
        yield aid, "summary", {"columns": ["field", "value"], "rows": [
            {"field": key, "value": json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value}
            for key, value in metadata.items()]}
        yield aid, "groups", {"columns": ["group", "current", "previous", "delta", "delta_pct", "contribution_pct"],
                               "rows": analysis["rows"]}


def pdf_change_pages(pdf, snapshot, result, footer):
    for aid, part, table in change_tables(snapshot, result):
        analysis = result["change_analyses"][aid]
        frame = pd.DataFrame(table["rows"], columns=table["columns"])
        if frame.empty:
            frame = pd.DataFrame([{"status": analysis["status"], "notice": analysis["notice"]}])
        pdf_table_pages(pdf, frame, f"{analysis['name']} | {part}", f"{footer} | {aid}")


def analysis_excel(writer, snapshot, result, used):
    for family, tables in (("SPC", spc_tables), ("CM", commonality_tables), ("CF", crossfact_tables), ("CH", change_tables), ("RFM", rfm_tables)):
        for index, (aid, part, table) in enumerate(tables(snapshot, result), 1):
            base = f"{family}_{index:03d}_{part}"
            sheet, counter = base, 1
            while sheet.casefold() in used:
                counter += 1
                sheet = f"{base}_{counter}"
            used.add(sheet.casefold())
            pd.DataFrame(table["rows"], columns=table["columns"]).to_excel(writer, sheet_name=sheet, index=False)
            writer.sheets[sheet].write_comment(0, 0, aid)


def pdf_commonality_pages(pdf, snapshot, result, footer):
    for aid, part, table in commonality_tables(snapshot, result):
        analysis = result["commonality_analyses"][aid]
        frame = pd.DataFrame(table["rows"], columns=table["columns"])
        if frame.empty:
            frame = pd.DataFrame([{"status": analysis["status"], "notice": analysis["notice"]}])
        pdf_table_pages(pdf, frame, f"{analysis['name']} | {part}", f"{footer} | {aid}")


def pdf_crossfact_pages(pdf, snapshot, result, footer):
    for aid, part, table in crossfact_tables(snapshot, result):
        analysis = result["crossfact_analyses"][aid]
        frame = pd.DataFrame(table["rows"], columns=table["columns"])
        if frame.empty:
            status = analysis["cohort_status"] if part == "cohorts" else analysis["status"]
            frame = pd.DataFrame([{"status": status, "notice": analysis["notice"]}])
        pdf_table_pages(pdf, frame, f"{analysis['name']} | {part}", f"{footer} | {aid}")


def write_csv_table(archive, filename, table):
    protected = []
    def cell(value, row, column):
        if value is None:
            return ""
        if isinstance(value, str) and (value.startswith(("\t", "\r", "\n")) or value.lstrip().startswith(("=", "+", "-", "@"))):
            protected.append([row, column])
            return "'" + value
        return value
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, quoting=csv.QUOTE_ALL, lineterminator="\r\n")
    columns = table["columns"]
    writer.writerow([cell(name, 0, i) for i, name in enumerate(columns)])
    for row_index, row in enumerate(table["rows"], 1):
        writer.writerow([cell(row.get(name), row_index, i) for i, name in enumerate(columns)])
    archive.writestr(filename, stream.getvalue().encode("utf-8-sig"))
    return protected


def csv_bundle(output,snapshot,result):
    """One table per CSV; typed companion preserves NULLs and protected text."""
    entries=[]
    with zipfile.ZipFile(output,"w",compression=zipfile.ZIP_DEFLATED) as archive:
        for index,(vid,visual) in enumerate(export_tables(result),1):
            pid,spec=next((pid,v) for pid,p in snapshot["report"]["pages"].items() for key,v in p["visuals"].items() if key==vid)
            filename=f"tables/{index:03d}.csv"
            columns=visual["columns"]
            protected=write_csv_table(archive,filename,visual)
            entries.append({"file":filename,"page_id":pid,"visual_id":vid,
                            "title":spec["visualization"].get("title",vid),"columns":columns,
                            "row_count":len(visual["rows"]),"protected_cells":protected,
                            **({"pivot_part":visual["pivot_part"]} if "pivot_part" in visual else {})})
        for family, tables in (("spc", spc_tables), ("commonality", commonality_tables), ("crossfact", crossfact_tables), ("change", change_tables), ("rfm", rfm_tables)):
            analyses = result.get(family + "_analyses", {})
            analysis_numbers = {aid: index for index, aid in enumerate(analyses, 1)}
            for aid, part, table in tables(snapshot, result):
                filename = f"{family}/{analysis_numbers[aid]:03d}-{part}.csv"
                protected = write_csv_table(archive, filename, table)
                entries.append({"file": filename, "analysis_id": aid, "kind": family + "_" + part,
                                "page_id": analyses[aid]["page_id"], "title": analyses[aid]["name"],
                                "columns": table["columns"], "row_count": len(table["rows"]), "protected_cells": protected})
        manifest={"format_version":2,"encoding":"utf-8-sig","delimiter":",","quoting":"all",
                  "null_encoding":"empty field; use analysis.json for original null versus empty string",
                  "text_protection":"apostrophe prefixed; protected_cells uses zero-based row/column, header row 0",
                  "snapshot_id":result["snapshot_id"],"revision":snapshot["revision"],
                  "execution_contract":result.get("execution_contract"),
                  "as_of":snapshot.get("as_of"),"executed_core_version":version("ai4bi"),
                  "exploration_page_id":result.get("exploration_page_id"),
                  "exploration_filters":snapshot.get("filters",[]),
                  "filter_bookmark_id":snapshot.get("filter_bookmark_id"),
                  "drill_state":snapshot.get("drill_state",{}),
                  "datasets":[{"dataset_id":d["dataset_id"],"version":d["version"]} for d in snapshot.get("datasets",[])],
                  "tables":entries}
        archive.writestr("manifest.json",json.dumps(manifest,ensure_ascii=False,indent=2).encode("utf-8"))
        archive.writestr("analysis.json",json.dumps({"report":snapshot["report"],"analysis":result},ensure_ascii=False,indent=2).encode("utf-8"))


def pdf_table_pages(pdf, frame, title, footer):
    """Split both axes and long cells while retaining every row and column."""
    from matplotlib import pyplot as plt
    for offset in range(0, len(frame.columns), 6):
        section = frame.iloc[:, offset:offset+6]
        headers = ["\n".join(textwrap.wrap(str(c), 18)) for c in section.columns]
        batch, labels, heights, units = [], [], [], 0

        def flush():
            if not batch:
                return
            fig, ax = plt.subplots(figsize=(11, 8.5))
            try:
                fig.suptitle(title, parse_math=False)
                fig.text(.05, .035, footer, fontsize=8)
                fig.text(.05, .065, f"Columns {offset+1}–{offset+len(section.columns)} / {len(frame.columns)}", fontsize=8)
                ax.axis("off")
                table = ax.table(cellText=batch, colLabels=headers, rowLabels=labels, loc="upper center", cellLoc="left")
                table.auto_set_font_size(False)
                table.set_fontsize(8)
                for (row, col), cell in table.get_celld().items():
                    cell.get_text().set_parse_math(False)
                    cell.set_height(.032 * (max(h.count("\n")+1 for h in headers)+.5 if row == 0 else heights[row-1]+.5))
                    if row == 0:
                        cell.set_facecolor("#e5eff5")
                fig.tight_layout(rect=[.04,.10,.98,.93])
                pdf.savefig(fig)
            finally:
                plt.close(fig)

        for index, row in enumerate(section.itertuples(index=False, name=None), 1):
            wrapped = [[piece for line in str(value).split("\n") for piece in (textwrap.wrap(line,18,drop_whitespace=False,replace_whitespace=False) or [""])] for value in row]
            for start in range(0, max(map(len, wrapped)), 4):
                fragment = ["\n".join(lines[start:start+4]) for lines in wrapped]
                height = max(text.count("\n")+1 for text in fragment)
                if batch and units + height + .5 > 22:
                    flush(); batch, labels, heights, units = [], [], [], 0
                batch.append(fragment); heights.append(height); units += height+.5
                labels.append(str(index) + (" +" if start else ""))
        flush()


def pdf_spc_pages(pdf, snapshot, result, footer):
    from matplotlib import pyplot as plt
    for aid, analysis in result.get("spc_analyses", {}).items():
        fig, ax = plt.subplots(figsize=(11, 8.5))
        try:
            fig.suptitle(textwrap.fill("SPC · " + analysis["name"], 50), fontsize=14, parse_math=False)
            points, limits = analysis["points"], analysis["limits"]
            if points:
                ax.plot(range(len(points)), [p["value"] for p in points], label="value", color="#2874a6")
                ticks = sorted({round(i * (len(points)-1) / 11) for i in range(12)})
                ax.set_xticks(ticks, [str(points[i]["entity"]) for i in ticks], rotation=45, ha="right")
                for label in ax.get_xticklabels():
                    label.set_parse_math(False)
                if limits:
                    for key, color in (("mean", "#20a397"), ("ucl", "#ba3347"), ("lcl", "#ba3347")):
                        ax.axhline(limits[key], label=f"{key} = {limits[key]:.6g}", color=color, linestyle="--")
                    outliers = [i for i, point in enumerate(points) if point["value"] > limits["ucl"] or point["value"] < limits["lcl"]]
                    if outliers:
                        ax.scatter(outliers, [points[i]["value"] for i in outliers], color="#ba3347", label="outliers", zorder=4)
                ax.legend()
                ax.set_xlabel(analysis["entity_column"], parse_math=False)
                ax.set_ylabel(analysis["value_column"], parse_math=False)
            else:
                ax.axis("off")
                ax.text(.5, .5, "沒有可分析的數值", ha="center", transform=ax.transAxes)
            status = {"ready": "掃描完成", "empty": "沒有可分析的數值", "insufficient_groups": "實體不足 3 組，無法計算界限", "zero_variance": "各實體數值相同，無法判斷離群"}[analysis["status"]]
            fig.text(.05, .12, f"{status} · {analysis['entity_count']} 個實體 · 使用 {analysis['used_rows']}/{analysis['input_rows']} 列 · k={analysis['k']} · {analysis['aggregation']}", parse_math=False)
            fig.text(.05, .08, textwrap.fill(analysis["notice"], 85), fontsize=8, parse_math=False)
            fig.text(.05, .025, footer + " | " + aid, fontsize=7, parse_math=False)
            fig.tight_layout(rect=[.03, .18, .97, .88])
            pdf.savefig(fig)
        finally:
            plt.close(fig)
        for table_aid, part, table in spc_tables(snapshot, {"spc_analyses": {aid: analysis}}):
            label = {"summary": "設定與來源", "points": "全部實體數值", "outliers": "離群實體"}[part]
            pdf_table_pages(pdf, pd.DataFrame(table["rows"], columns=table["columns"]),
                            textwrap.fill("SPC · " + analysis["name"] + " · " + label, 50), footer + " | " + table_aid)


def export_snapshot(root: Path, snapshot: dict, directory: Path) -> dict:
    # Re-query the fixed data versions, and fail explicitly if any visual fails.
    result = run_query(root, {**snapshot, "include_spc": True, "include_commonality": True, "include_crossfact": True, "include_change": True, "include_rfm": True})
    from .change_analysis import delivery_checks as change_checks
    change_checks(snapshot.get("report", {}), result)
    from .rfm import delivery_checks as rfm_checks
    rfm_checks(snapshot["report"], result)
    from .crossfact import delivery_checks as crossfact_checks
    crossfact_checks(snapshot["report"], result)
    if any(v["status"] != "ready" for v in result["visuals"].values()):
        raise AppError("EXPORT_QUERY_FAILED", "部分圖表無法查詢，請修正後再匯出。")
    if any(v.get("truncated") for v in result["visuals"].values()):
        raise AppError("EXPORT_LIMIT", "結果超過目前完整匯出上限，請縮小範圍；不會輸出截斷資料。")
    expected = {item["analysis_id"] for item in snapshot["report"].get("web_extensions", {}).get("spc_analyses", [])}
    if set(result.get("spc_analyses", {})) != expected:
        raise AppError("EXPORT_QUERY_FAILED", "SPC 分析結果不完整，無法匯出。")
    from .commonality import delivery_checks
    delivery_checks(snapshot["report"], result)
    format = snapshot["format"]
    output = directory / ("export." + export_suffix(format))
    if format == "json":
        output.write_text(json.dumps({"report": snapshot["report"], "analysis": result}, ensure_ascii=False, indent=2), encoding="utf-8")
    elif format == "csv":
        csv_bundle(output,snapshot,result)
    elif format == "xlsx":
        used = set()
        with pd.ExcelWriter(output, engine="xlsxwriter", engine_kwargs={"options": {"strings_to_formulas": False, "strings_to_urls": False}}) as writer:
            pd.DataFrame([{"report_revision": snapshot["revision"], "snapshot_id": result["snapshot_id"],
                           "exploration_page_id":result["exploration_page_id"],
                           "filter_bookmark_id":snapshot.get("filter_bookmark_id"),
                           "drill_state":json.dumps(snapshot.get("drill_state",{}),ensure_ascii=False),
                           "persistent_filters":json.dumps(snapshot["report"].get("web_extensions",{}).get("persistent_filters",[]),ensure_ascii=False),
                           "exploration_filters":json.dumps(snapshot.get("filters",[]),ensure_ascii=False),
                           "execution_contract":result.get("execution_contract")}]).to_excel(writer, sheet_name="來源與版本", index=False)
            for vid, visual in export_tables(result):
                title = next(v["visualization"].get("title", vid) for p in snapshot["report"]["pages"].values() for key, v in p["visuals"].items() if key == vid)
                base = re.sub(r"[\[\]:*?/\\]", "", title or vid).strip("'")[:25].strip("'") or "Data"
                sheet = base
                counter = 1
                while sheet.casefold() in used or sheet == "來源與版本":
                    counter += 1
                    sheet = base[:24] + f"_{counter}"
                used.add(sheet.casefold())
                part = visual.get("pivot_part")
                start = 3 if part else 0
                pd.DataFrame(visual["rows"], columns=visual["columns"]).to_excel(writer, sheet_name=sheet, index=False, startrow=start)
                comparison = visual.get("kpi", {}).get("comparison")
                if comparison:
                    comparison_rows = []
                    for period in ("current", "previous"):
                        window = comparison[f"{period}_window"]
                        comparison_rows.append({"period": period, "start_inclusive": window[0] if window else None,
                            "end_exclusive": window[1] if window else None, "value": comparison[period],
                            "delta": comparison["delta"] if period == "current" else None,
                            "delta_percent": comparison["delta_percent"] if period == "current" else None,
                            "timezone": comparison["timezone"], "filter_policy": comparison["filter_policy"], "reason": comparison["reason"]})
                    pd.DataFrame(comparison_rows).to_excel(writer, sheet_name=sheet, index=False, startrow=len(visual["rows"])+3)
                sparkline = visual.get("kpi", {}).get("sparkline")
                if sparkline:
                    offset = len(visual["rows"]) + (8 if comparison else 3)
                    pd.DataFrame(sparkline["points"], columns=["date", "value"]).to_excel(writer, sheet_name=sheet, index=False, startrow=offset)
                    writer.sheets[sheet].write_string(offset + len(sparkline["points"]) + 2, 0, sparkline["caption"])
                if part:
                    worksheet = writer.sheets[sheet]
                    worksheet.write_string(0, 0, f"{part['metric']['key']} | {part['part']}/{part['parts']}")
                    worksheet.write_string(1, 0, part["note"])
                    worksheet.freeze_panes(4, 1)
            analysis_excel(writer, snapshot, result, used)
    else:
        import matplotlib
        matplotlib.use("Agg")
        from matplotlib import pyplot as plt, font_manager
        from matplotlib.backends.backend_pdf import PdfPages
        available = {f.name for f in font_manager.fontManager.ttflist}
        for font in ("Microsoft JhengHei", "Microsoft YaHei", "Noto Sans CJK TC"):
            if font in available:
                plt.rcParams["font.sans-serif"] = [font]
                break
        else:
            raise AppError("EXPORT_FONT_MISSING", "PDF 中文字型不存在，請安裝或隨部署包提供中文字型。")
        plt.rcParams["axes.unicode_minus"] = False
        plt.rcParams["pdf.fonttype"] = 42
        with PdfPages(output) as pdf:
            pdf.infodict()["Subject"] = "Execution contract: " + str(result.get("execution_contract", "unspecified"))
            footer = f"Revision {snapshot['revision']} | {result['snapshot_id'][:16]} | Exploration page: {result['exploration_page_id'] or 'none'}"
            for vid, visual in export_tables(result):
                spec = next(v for p in snapshot["report"]["pages"].values() for key, v in p["visuals"].items() if key == vid)
                # Drill execution may replace dimension aliases. Render the
                # accepted query, while leaving the saved report unchanged.
                spec = {**spec, "query": visual.get("query", spec["query"])}
                frame = pd.DataFrame(visual["rows"], columns=visual["columns"])
                kind = spec["visualization"]["visual_type"]
                sparkline = visual.get("kpi", {}).get("sparkline")
                if sparkline:
                    from datetime import date
                    from .kpi import finite
                    fig, ax = plt.subplots(figsize=(11, 7))
                    try:
                        fig.suptitle(str(spec["visualization"].get("title", vid)) + " — 逐日趨勢", parse_math=False)
                        fig.text(.05, .08, sparkline["caption"], fontsize=9, parse_math=False)
                        fig.text(.05, .03, footer, fontsize=8, parse_math=False)
                        valid = [p for p in sparkline["points"] if finite(p["value"])]
                        magnitude = max([abs(p["value"]) for p in valid], default=0)
                        scale = magnitude if magnitude > 1e100 else 1
                        previous = None
                        for point in sparkline["points"]:
                            if not finite(point["value"]):
                                previous = None
                                continue
                            day, value = date.fromisoformat(point["date"]), point["value"] / scale
                            ax.plot([day], [value], marker="o", color="#2563eb")
                            if previous and (day-previous[0]).days == 1:
                                ax.plot([previous[0], day], [previous[1], value], color="#2563eb")
                            previous = day, value
                        ax.set_xlabel("日期（UTC）")
                        ax.set_ylabel("指標" if scale == 1 else f"指標 / {scale:g}")
                        if not valid:
                            ax.text(.5,.5,sparkline["reason"] or "目前沒有資料",transform=ax.transAxes,ha="center",wrap=True)
                        fig.autofmt_xdate()
                        fig.tight_layout(rect=[0,.13,1,.94]); pdf.savefig(fig)
                    finally:
                        plt.close(fig)
                if kind == "pie_chart":
                    pie = visual.get("pie")
                    if not pie or pie.get("version") != 1:
                        raise AppError("INVALID_PIE", "圓餅圖匯出缺少相容資料。")
                    title = spec["visualization"].get("title", vid)
                    fig, ax = plt.subplots(figsize=(11, 7))
                    try:
                        fig.suptitle(title, parse_math=False); fig.text(.05, .02, footer, fontsize=8)
                        ax.set_title(f"指標：{pie['metric_key']}；排除 {pie['excluded_count']} 筆非有限權重", parse_math=False)
                        if pie["status"] != "ready":
                            ax.axis("off"); ax.text(.5, .5, pie["reason"], ha="center", wrap=True)
                        else:
                            settings = pie["settings"]
                            labels = ["\n".join([s["label"], *([f"{s['percent']:.2f}%"] if settings["show_percent"] else []),
                                                *([str(s["value"])] if settings["data_labels"] else [])]) for s in pie["slices"]]
                            wedges, _ = ax.pie([s["value"] for s in pie["slices"]], labels=labels,
                                colors=["#2874a6", "#20a397", "#e7a645", "#735da8", "#c56574", "#5d8290"],
                                startangle=90, counterclock=False, wedgeprops={"width": 1-settings["hole"], "edgecolor": "white"},
                                textprops={"parse_math": False})
                            if settings["show_legend"]:
                                position = settings["legend_position"]
                                location, anchor = {"top": ("lower center", (.5, 1.05)), "bottom": ("upper center", (.5, -.05)),
                                    "left": ("center right", (-.15, .5)), "right": ("center left", (1.15, .5))}[position]
                                legend = ax.legend(wedges, [s["label"] for s in pie["slices"]], loc=location, bbox_to_anchor=anchor,
                                                   ncol=3 if position in ("top", "bottom") else 1)
                                for label in legend.get_texts(): label.set_parse_math(False)
                        fig.tight_layout(rect=[0, .05, 1, .94]); pdf.savefig(fig)
                    finally:
                        plt.close(fig)
                    if not frame.empty: pdf_table_pages(pdf, frame, title + " — 完整資料", footer)
                    continue
                if kind == "scatter":
                    data = visual.get("scatter")
                    if not data or data.get("version") != 1:
                        raise AppError("INVALID_SCATTER", "散點圖匯出缺少相容座標。")
                    fig, ax = plt.subplots(figsize=(11, 7))
                    try:
                        title = spec["visualization"].get("title", vid)
                        fig.suptitle(title, parse_math=False)
                        fig.text(.05, .02, footer, fontsize=8)
                        groups = {}
                        for point in data["points"]:
                            key = (type(point["group"]).__name__, json.dumps(point["group"]))
                            groups.setdefault(key, []).append(point)
                        maximum = max((p["size"] or 0 for p in data["points"]), default=0)
                        colors = ["#2874a6", "#20a397", "#e7a645", "#735da8", "#c56574", "#5d8290"]
                        markers = ["o", "s", "D", "+", "^", "v"]
                        for index, points in enumerate(groups.values()):
                            sizes = [max(49, 1600*(p["size"] or 0)/maximum) if data["size_key"] and maximum else 81 for p in points]
                            group = points[0]["group"]
                            label = str(group) if group is not None else "（空值）" if data["group_key"] else "全部"
                            ax.scatter([p["x"] for p in points], [p["y"] for p in points], s=sizes,
                                       color=colors[index % len(colors)], marker=markers[index % len(markers)], label=label, alpha=.8)
                        for fit in data.get("trendlines", []):
                            if fit["status"] != "ready":
                                continue
                            key = (type(fit["group"]).__name__, json.dumps(fit["group"]))
                            index = list(groups).index(key)
                            ax.plot(fit["x"], fit["y"], linestyle="--", color=colors[index % len(colors)],
                                    label="_nolegend_")
                        ax.set_xlabel(spec["visualization"].get("x_axis_label") or data["x_key"], parse_math=False)
                        ax.set_ylabel(spec["visualization"].get("y_axis_label") or data["y_key"] or "列序號（從 0 起）", parse_math=False)
                        ax.set_title(f"散點 {len(data['points'])} 筆；排除 {data['excluded_count']} 筆非有限座標" +
                                     (f" · {data['trendline'].upper()}" if data.get("trendline") else ""))
                        if data["group_key"] and groups and spec["visualization"].get("show_legend", True):
                            legend = ax.legend()
                            for label in legend.get_texts():
                                label.set_parse_math(False)
                        fig.tight_layout(rect=[0, .04, 1, .94]); pdf.savefig(fig)
                    finally:
                        plt.close(fig)
                    if not frame.empty:
                        pdf_table_pages(pdf, frame, title + " — 完整資料", footer)
                    if data.get("trendlines"):
                        fitted = [{"群組": fit["group"] if data["group_key"] else "全部", "方法": fit["method"].upper(),
                                   "筆數": fit["n"], "結果": fit.get("reason", "擬合完成"),
                                   "線性係數": f"斜率 {fit['slope']}；截距 {fit['intercept']}" if fit["slope"] is not None else "—",
                                   "R²": fit["r_squared"]}
                                  for fit in data["trendlines"]]
                        pdf_table_pages(pdf, pd.DataFrame(fitted), title + " — 趨勢擬合結果", footer)
                    continue
                if kind == "map":
                    from .geographic_pdf import geographic_page
                    title = spec["visualization"].get("title", vid)
                    geographic_page(pdf, spec, visual, title, footer)
                    if not frame.empty:
                        pdf_table_pages(pdf, frame, title + " — 完整資料", footer)
                    continue
                if visual.get("histogram"):
                    histogram = visual["histogram"]
                    fig, ax = plt.subplots(figsize=(11, 7))
                    try:
                        fig.suptitle(spec["visualization"].get("title", vid))
                        fig.text(.05, .02, footer, fontsize=8)
                        ax.bar([(r["lower"]+r["upper"])/2 for r in visual["rows"]],
                               [r["count"] for r in visual["rows"]],
                               width=[(r["upper"]-r["lower"])*.95 for r in visual["rows"]])
                        ax.set_xlabel(histogram["field"]["key"]); ax.set_ylabel("筆數")
                        ax.set_title(f"有效 {histogram['valid_count']} 筆；排除 {histogram['excluded_count']} 筆")
                        fig.tight_layout(rect=[0,.04,1,.94]); pdf.savefig(fig)
                    finally:
                        plt.close(fig)
                    continue
                if "pivot_part" in visual:
                    part = visual["pivot_part"]
                    title = f"{spec['visualization'].get('title',vid)} | {part['metric']['key']} | {part['part']}/{part['parts']}"
                    pdf_table_pages(pdf, frame, title, footer + "\n" + part["note"])
                    continue
                multi_kpi = kind == "kpi_card" and (len(frame) != 1 or len(spec["query"]["metrics"]) != 1 or bool(spec["query"]["dimensions"]))
                if not frame.empty and (kind not in ("kpi_card", "bar_chart", "line_chart") or multi_kpi):
                    pdf_table_pages(pdf, frame, spec["visualization"].get("title",vid),
                                    footer)
                    continue
                fig, ax = plt.subplots(figsize=(11, 7))
                fig.suptitle(spec["visualization"].get("title", vid))
                fig.text(0.05, 0.02, footer, fontsize=8)
                try:
                    dims, metrics = spec["query"]["dimensions"], spec["query"]["metrics"]
                    metric = (metrics[0].get("alias") or metrics[0]["metric_name"]) if metrics else None
                    dim = (dims[0].get("alias") or dims[0]["column_name"]) if dims else None
                    kind = spec["visualization"]["visual_type"]
                    if frame.empty:
                        ax.axis("off"); ax.text(.5,.5,"目前沒有資料",ha="center")
                    elif kind == "kpi_card" and metric:
                        value = frame[metric].iloc[0]
                        label = "—" if pd.isna(value) else f"{value:,.2f}" if isinstance(value, (int, float)) else str(value)
                        kpi = visual.get("kpi")
                        if kpi:
                            label = kpi["label"] + kpi["unit"]
                        comparison = kpi.get("comparison") if kpi else None
                        ax.axis("off"); ax.text(.5,.72 if comparison else .5,label,ha="center",fontsize=36,parse_math=False)
                        if kpi:
                            lines = [kpi["reason"]] if kpi["reason"] else []
                            if kpi["rag"]:
                                lines.append(kpi["rag"]["label"])
                            if kpi["pacing"]:
                                lines.append(kpi["pacing"]["label"])
                                if kpi["pacing"]["reason"]:
                                    lines.append(kpi["pacing"]["reason"])
                            if comparison:
                                lines.extend(comparison["captions"])
                                if comparison["reason"]:
                                    lines.append(comparison["reason"])
                            ax.text(.5,.55 if comparison else .32,"\n".join(lines),ha="center",va="top",fontsize=12,parse_math=False,wrap=True)
                    elif kind == "bar_chart" and visual.get("bar"):
                        pdf_bars(ax, visual["bar"], visual["chart_format"], spec["visualization"])
                    elif kind in ("bar_chart", "line_chart") and dim and metric:
                        x = list(range(len(frame)))
                        width = .8 / len(metrics)
                        for index, item in enumerate(metrics):
                            column = item.get("alias") or item["metric_name"]
                            if kind == "bar_chart":
                                positions = [value - .4 + width*(index+.5) for value in x]
                                bars = ax.bar(positions, frame[column], width=width, label=column)
                                if visual.get("chart_format", {}).get("data_labels"):
                                    ax.bar_label(bars, labels=visual["chart_format"]["labels"][column], padding=3)
                            else:
                                ax.plot(x, frame[column], marker="o", label=column)
                                if visual.get("chart_format", {}).get("data_labels"):
                                    for position, value, label in zip(x, frame[column], visual["chart_format"]["labels"][column]):
                                        if pd.notna(value):
                                            ax.annotate(label, (position, value), xytext=(0, 5), textcoords="offset points", ha="center", parse_math=False)
                        ax.set_xticks(x, frame[dim].astype(str))
                        ax.tick_params(axis="x",rotation=45)
                        settings = visual.get("chart_format")
                        if settings:
                            apply_cartesian_format(ax, settings)
                        elif len(metrics) > 1:
                            ax.legend()
                    else:
                        plt.close(fig)
                        pdf_table_pages(pdf, frame, spec["visualization"].get("title",vid),
                                        f"Revision {snapshot['revision']} | {result['snapshot_id'][:16]}")
                        continue
                    fig.tight_layout(rect=[0,.04,1,.94]); pdf.savefig(fig)
                    if visual.get("bar", {}).get("grouped"):
                        pdf_table_pages(pdf, frame, spec["visualization"].get("title", vid) + " — 完整資料", footer)
                finally:
                    plt.close(fig)
            pdf_spc_pages(pdf, snapshot, result, footer)
            pdf_commonality_pages(pdf, snapshot, result, footer)
            pdf_crossfact_pages(pdf, snapshot, result, footer)
            pdf_change_pages(pdf, snapshot, result, footer)
            pdf_rfm_pages(pdf, snapshot, result, footer)
    return {"filename": "report." + export_suffix(format), "format": format, "snapshot_id": result["snapshot_id"],
            "revision": snapshot["revision"]}
