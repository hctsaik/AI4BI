"""Validated UTC date buckets for report dimensions and legacy seasonality."""
from ai4bi.analysis.executor import _qualified, _quote
from .errors import AppError


GRAINS = {"day", "week", "month", "quarter", "year", "hour", "weekday", "dow", "dayofweek"}


def date_grain(dimension, contracts):
    value = dimension.truncate_date_to
    if value is None or value == "":
        return None
    if not isinstance(value, str) or value.lower() not in GRAINS:
        raise AppError("INVALID_DATE_GRAIN", "日期粒度須為日、週、月、季、年、星期或小時。")
    contract = contracts.get(dimension.block_id)
    field = next((c for c in contract.columns if c.name == dimension.column_name), None) if contract else None
    if field is None or field.data_type.lower() not in {"date", "datetime", "timestamp"}:
        raise AppError("INVALID_DATE_GRAIN", "日期分組只能使用日期或時間欄位。")
    return value.lower()


def validate_date_dimensions(query, contracts):
    for dimension in query.dimensions:
        date_grain(dimension, contracts)


def date_dimension_sql(dimension, contracts):
    grain = date_grain(dimension, contracts)
    if grain is None:
        return None
    # Naive timestamps are interpreted under the executor's explicit UTC session.
    # Convert offset-bearing strings before truncation, preserving UTC day edges.
    instant = f"(CAST({_qualified(dimension.block_id, dimension.column_name)} AS TIMESTAMPTZ) AT TIME ZONE 'UTC')"
    if grain in {"weekday", "dow", "dayofweek"}:
        value = f"DAYNAME(CAST({instant} AS DATE))"
    elif grain == "hour":
        value = f"EXTRACT(hour FROM {instant})"
    else:
        value = f"DATE_TRUNC('{grain}', CAST({instant} AS DATE))"
    return value + " AS " + _quote(dimension.alias or dimension.column_name)
