from pathlib import Path
import pytest
from ai4bi.ui.runtime_paths import runtime_paths


def test_standalone_defaults_and_managed_isolation(tmp_path):
    project = tmp_path / "app"
    seed = project / "data/semiconductor_demo/registry"
    seed.mkdir(parents=True)
    (seed / "block.json").write_text("seed", encoding="utf8")
    drafts = seed.parent / "draft_reports"
    drafts.mkdir()
    (drafts / "private.json").write_text("user", encoding="utf8")
    default = runtime_paths(project, data_root="")
    assert default.drafts == drafts
    assert default.project_data == project
    root = tmp_path / "managed"
    managed = runtime_paths(project, data_root=str(root))
    assert managed.drafts == root / "draft_reports"
    assert managed.project_data == root
    assert (managed.registry / "block.json").read_text() == "seed"
    assert not managed.drafts.exists()
    (managed.registry / "block.json").write_text("modified", encoding="utf8")
    runtime_paths(project, data_root=str(root))
    assert (managed.registry / "block.json").read_text() == "modified"
    assert (seed / "block.json").read_text() == "seed"


def test_invalid_managed_roots_are_rejected(tmp_path):
    project = tmp_path / "app"
    project.mkdir()
    for value in ("relative-data", str(project / "data")):
        with pytest.raises(ValueError):
            runtime_paths(project, data_root=value)
