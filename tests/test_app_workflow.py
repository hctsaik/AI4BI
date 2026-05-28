from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest


APP_PATH = Path(__file__).parent.parent / "ai4bi" / "ui" / "app.py"


def _click(app: AppTest, label: str) -> None:
    next(button for button in app.button if button.label == label).click().run(timeout=20)


def _new_app() -> AppTest:
    return AppTest.from_file(str(APP_PATH)).run(timeout=20)


def _visual_selectbox(app: AppTest):
    """Return the '① 選擇圖表' selectbox, looked up by its stable widget key."""
    return next(sb for sb in app.selectbox if sb.key == "selected_component_id")


def test_style_prompt_previews_applies_and_undoes_without_changing_metrics():
    app = _new_app()
    original_metrics = [(metric.label, metric.value) for metric in app.metric]
    _visual_selectbox(app).set_value("line_queue_by_day").run(timeout=20)
    app.text_input[0].set_value("make trend line red").run(timeout=20)

    _click(app, "送出請求")
    report = app.session_state["report_spec"]
    assert report.pages["main"].visuals["line_queue_by_day"].visualization.extra["line_color"] is None
    assert [(metric.label, metric.value) for metric in app.metric] == original_metrics

    _click(app, "Apply Proposal")
    report = app.session_state["report_spec"]
    assert report.pages["main"].visuals["line_queue_by_day"].visualization.extra["line_color"] == "#D62728"
    assert [(metric.label, metric.value) for metric in app.metric] == original_metrics

    _click(app, "復原")
    report = app.session_state["report_spec"]
    assert report.pages["main"].visuals["line_queue_by_day"].visualization.extra["line_color"] is None
    assert not app.exception


def test_analysis_prompt_waits_for_apply_and_then_undo_restores_controls_and_numbers():
    app = _new_app()
    _visual_selectbox(app).set_value("line_queue_by_day").run(timeout=20)
    app.text_input[0].set_value("Only show Logic-B").run(timeout=20)

    _click(app, "送出請求")
    assert [(metric.label, metric.value) for metric in app.metric] == [
        ("Processed Moves", "6.0 moves"),
        ("Average Queue Time", "2.7 hr"),
    ]

    _click(app, "Apply Proposal")
    assert app.multiselect[1].value == ["Logic-B"]
    assert [(metric.label, metric.value) for metric in app.metric] == [
        ("Processed Moves", "2.0 moves"),
        ("Average Queue Time", "4.0 hr"),
    ]

    _click(app, "復原")
    assert app.multiselect[1].value == ["Logic-A", "Logic-B"]
    assert [(metric.label, metric.value) for metric in app.metric] == [
        ("Processed Moves", "6.0 moves"),
        ("Average Queue Time", "2.7 hr"),
    ]
    assert not app.exception


def test_manual_slicer_change_is_part_of_report_history():
    app = _new_app()

    app.multiselect[1].set_value(["Logic-B"]).run(timeout=20)
    assert [(metric.label, metric.value) for metric in app.metric] == [
        ("Processed Moves", "2.0 moves"),
        ("Average Queue Time", "4.0 hr"),
    ]

    _click(app, "復原")
    assert app.multiselect[1].value == ["Logic-A", "Logic-B"]
    assert [(metric.label, metric.value) for metric in app.metric] == [
        ("Processed Moves", "6.0 moves"),
        ("Average Queue Time", "2.7 hr"),
    ]
    assert not app.exception


def test_unsupported_assistant_request_clears_stale_pending_proposal():
    app = _new_app()
    _visual_selectbox(app).set_value("line_queue_by_day").run(timeout=20)
    app.text_input[0].set_value("make trend line red").run(timeout=20)

    _click(app, "送出請求")
    assert app.session_state["pending_patch"] is not None

    app.text_input[0].set_value("write SQL to join raw queue moves to wafer yield detail rows").run(timeout=20)
    _click(app, "送出請求")

    assert app.session_state["pending_patch"] is None
    assert not app.exception
