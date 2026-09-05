"""Enforce repository quality limits from measured source and coverage data."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

from radon.complexity import cc_visit
from radon.metrics import h_visit

SOURCE = Path("custom_components/kinosail")
PYTHON_ROOTS = (SOURCE, Path("tests"), Path("scripts"))


def functions(source: str):
    """Yield Radon functions, including nested closures."""
    for block in cc_visit(source):
        if block.__class__.__name__ == "Function":
            yield block
            yield from block.closures


def dynamic_type_lines(tree: ast.AST) -> list[int]:
    """Find explicit Any and Unknown type names in production source."""
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "typing":
            lines.update(node.lineno for alias in node.names if alias.name in {"Any", "Unknown"})
        elif isinstance(node, ast.Name) and node.id in {"Any", "Unknown"}:
            lines.add(node.lineno)
        elif isinstance(node, ast.Attribute) and node.attr in {"Any", "Unknown"}:
            lines.add(node.lineno)
    return sorted(lines)


def main() -> int:
    coverage = json.loads(Path(sys.argv[1]).read_text())
    failures: list[str] = []
    totals = coverage["totals"]
    for name in ("percent_statements_covered", "percent_branches_covered"):
        if totals[name] != 100:
            failures.append(f"coverage {name}={totals[name]:.2f}, required=100")

    maxima = {"loc": (0.0, ""), "cyclomatic": (0.0, ""), "halstead": (0.0, ""), "crap": (0.0, "")}
    for root in PYTHON_ROOTS:
        for path in root.rglob("*.py"):
            source = path.read_text()
            loc = len(source.splitlines())
            if loc > maxima["loc"][0]:
                maxima["loc"] = (loc, str(path))
            if loc >= 300:
                failures.append(f"LOC {path}={loc}, required<300")
            if root != SOURCE:
                continue
            dynamic_lines = dynamic_type_lines(ast.parse(source))
            if dynamic_lines:
                failures.append(f"dynamic types {path}:{dynamic_lines}")
            halstead = h_visit(source)
            reports = [("module", halstead.total), *halstead.functions]
            for name, report in reports:
                if report.difficulty > maxima["halstead"][0]:
                    maxima["halstead"] = (report.difficulty, f"{path}:{name}")
                if report.difficulty >= 80:
                    failures.append(f"Halstead {path}:{name}={report.difficulty:.2f}, required<80")
            covered_functions = coverage["files"][str(path)]["functions"]
            for block in functions(source):
                name = block.fullname
                if name not in covered_functions:
                    name = next(
                        (key for key, value in covered_functions.items() if value["start_line"] == block.lineno), name
                    )
                percent = covered_functions[name]["summary"]["percent_covered"]
                crap = block.complexity**2 * (1 - percent / 100) ** 3 + block.complexity
                if block.complexity > maxima["cyclomatic"][0]:
                    maxima["cyclomatic"] = (block.complexity, f"{path}:{name}")
                if crap > maxima["crap"][0]:
                    maxima["crap"] = (crap, f"{path}:{name}")
                if block.complexity >= 22:
                    failures.append(f"cyclomatic {path}:{name}={block.complexity}, required<22")
                if crap >= 25:
                    failures.append(f"CRAP {path}:{name}={crap:.2f}, required<25")

    for metric, (value, location) in maxima.items():
        print(f"{metric}: {value:g} ({location})")
    print("explicit Any/Unknown types: 0")
    if failures:
        print("Quality metric failures:\n" + "\n".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
