"""Optional host-owned writable paths; standalone defaults remain unchanged."""
from dataclasses import dataclass
import os
from pathlib import Path
import shutil


@dataclass(frozen=True)
class RuntimePaths:
    drafts: Path
    registry: Path
    project_data: Path


def runtime_paths(project: Path, *, data_root: str | None = None) -> RuntimePaths:
    project = Path(project).resolve()
    demo = project / "data" / "semiconductor_demo"
    value = os.environ.get("AI4BI_DATA_ROOT", "") if data_root is None else data_root
    if not value:
        return RuntimePaths(demo / "draft_reports", demo / "registry", project)
    root = Path(value)
    if not root.is_absolute():
        raise ValueError("AI4BI_DATA_ROOT must be an absolute directory")
    root = root.resolve()
    if root.is_relative_to(project):
        raise ValueError("AI4BI_DATA_ROOT must be outside the application source")
    root.mkdir(parents=True, exist_ok=True)
    registry = root / "registry"
    if not registry.exists():
        seed = demo / "registry"
        if seed.is_dir():
            # Copy only the shipped registry, never source drafts or reports.
            shutil.copytree(seed, registry)
        else:
            registry.mkdir()
    return RuntimePaths(root / "draft_reports", registry, root)
