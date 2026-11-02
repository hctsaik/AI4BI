"""Check an installed core wheel with a small independently calculated oracle."""
from __future__ import annotations

import argparse
import importlib.abc
import json
from pathlib import Path
import sys


class RejectStreamlit(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "streamlit" or fullname.startswith("streamlit."):
            raise ImportError("Streamlit is deliberately unavailable in this headless probe")
        return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-package-root", type=Path, required=True)
    parser.add_argument("--forbid-source", type=Path, action="append", default=[])
    args = parser.parse_args()
    forbidden = [root.resolve() for root in args.forbid_source]

    def audit(event, values):
        if event == "open" and isinstance(values[0], (str, bytes)):
            candidate = Path(values[0].decode() if isinstance(values[0], bytes) else values[0]).resolve()
            if any(candidate.is_relative_to(root) for root in forbidden):
                raise PermissionError("Probe attempted to read a source checkout")

    sys.addaudithook(audit)
    sys.meta_path.insert(0, RejectStreamlit())
    import ai4bi
    from ai4bi.analysis.executor import Executor
    from ai4bi.ai.nl2proposal import NL2ProposalService
    from ai4bi.blocks.contracts import (BlockType, ColumnSchema, DataBlockContract,
                                        DisaggregationMethod, InlineDataSource, MetricDefinition)
    from ai4bi.query_spec import BlockRef, DimensionRef, MetricRef, VisualQuerySpec

    package_path = Path(ai4bi.__file__).resolve()
    assert package_path.is_relative_to(args.expected_package_root.resolve()), package_path
    # Tool A: 90/100 + 1/10 => weighted yield 91/110, NOT mean(90%,10%)=50%.
    rows = [{"tool": "A", "good": 90, "tested": 100},
            {"tool": "A", "good": 1, "tested": 10},
            {"tool": "B", "good": 4, "tested": 5}]
    block = DataBlockContract(
        block_id="yield_fact", block_type=BlockType.fact,
        description="P00 hand-calculable yield oracle", grain="one measurement per tool and sample",
        columns=[ColumnSchema(name="tool", data_type="string"),
                 ColumnSchema(name="good", data_type="integer"),
                 ColumnSchema(name="tested", data_type="integer")],
        metrics=[MetricDefinition(name="yield_ratio", formula="SUM(good) / NULLIF(SUM(tested), 0)",
                                  disaggregation_method=DisaggregationMethod.none)],
        data_source=InlineDataSource(records=rows))
    executor = Executor(extra_contracts={block.block_id: block})
    spec = VisualQuerySpec("p00_yield", [BlockRef(block.block_id)],
                           metrics=[MetricRef(block.block_id, "yield_ratio", "ratio")],
                           dimensions=[DimensionRef(block.block_id, "tool", "tool")])
    frame, metadata = executor.run_with_metadata(spec)
    actual = frame.set_index("tool")["ratio"].to_dict()
    expected = {"A": 91 / 110, "B": 4 / 5}
    assert actual.keys() == expected.keys()
    assert all(abs(actual[key] - expected[key]) < 1e-12 for key in expected), actual
    assert metadata.blocks_used == ["yield_fact"], metadata
    assert "streamlit" not in sys.modules
    print(json.dumps({"package_path": str(package_path), "actual": actual, "expected": expected,
                      "streamlit_imported": False, "nl_service_imported": NL2ProposalService.__name__,
                      "source_read_blocked": [str(p) for p in forbidden],
                      "metadata_blocks": metadata.blocks_used}, indent=2))


if __name__ == "__main__":
    main()
