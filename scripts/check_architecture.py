from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "voicepilot"
PRODUCTION_MODULE_LIMIT = 500

STRICT_LIMITS = {
    "settings_qt.py": 500,
    "settings_pages.py": 500,
    "settings_models.py": 500,
    "hud_qt.py": 500,
    "app_lifecycle.py": 500,
    "rewrite.py": 500,
    "models.py": 500,
    "settings_home.py": 500,
    "settings_rewrite_pages.py": 500,
}

# Cohesive modules intentionally above the general target. Limits prevent
# unnoticed growth and each reason is reviewed in docs/ARCHITECTURE_EXCEPTIONS.md.
DOCUMENTED_EXCEPTIONS = {
    "__main__.py": 525,
    "ai_runtime.py": 650,
    "app_context.py": 620,
    "app_pipeline.py": 610,
    "audio.py": 800,
    "config.py": 600,
    "history.py": 600,
    "hotkeys.py": 525,
    "lifecycle_capture.py": 525,
    "llama_server.py": 575,
    "onboarding_pages.py": 1075,
    "onboarding_qt.py": 900,
    "onboarding_shortcuts.py": 675,
    "onboarding_tests.py": 1150,
    "paste.py": 580,
    "polish_prompts.py": 550,
    "polish_validation.py": 825,
    "settings_dictation_page.py": 700,
    "settings_rewrite_embedded.py": 650,
    "settings_speech_models_page.py": 700,
    "settings_style.py": 1200,
    "settings_update_prompt.py": 575,
    "transcribe.py": 725,
}


def _module_name(path: Path) -> str:
    return path.stem


def _module_imports(path: Path, known: set[str]) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    imports: set[str] = set()
    # Only static module-level imports participate. Function-local imports are
    # deliberate lazy boundaries and do not create import-time cycles.
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
            target = node.module.split(".", 1)[0]
            if target in known:
                imports.add(target)
    return imports


def find_cycles() -> list[tuple[str, ...]]:
    paths = {path.stem: path for path in PACKAGE.glob("*.py") if path.name != "__init__.py"}
    graph = {name: _module_imports(path, set(paths)) for name, path in paths.items()}
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []
    cycles: set[tuple[str, ...]] = set()

    def visit(name: str) -> None:
        if name in visiting:
            start = stack.index(name)
            cycle = stack[start:] + [name]
            rotations = [tuple(cycle[index:-1] + cycle[:index] + [cycle[index]]) for index in range(len(cycle) - 1)]
            cycles.add(min(rotations))
            return
        if name in visited:
            return
        visiting.add(name)
        stack.append(name)
        for target in sorted(graph[name]):
            visit(target)
        stack.pop()
        visiting.remove(name)
        visited.add(name)

    for module in sorted(graph):
        visit(module)
    return sorted(cycles)


def size_failures() -> list[str]:
    failures: list[str] = []
    for path in PACKAGE.glob("*.py"):
        filename = path.name
        limit = STRICT_LIMITS.get(
            filename,
            DOCUMENTED_EXCEPTIONS.get(filename, PRODUCTION_MODULE_LIMIT),
        )
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines > limit:
            failures.append(f"{filename}: {lines} lines exceeds {limit}")
    for path in (ROOT / "tests").glob("test_*.py"):
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines > 800:
            failures.append(f"{path.name}: {lines} test lines exceeds 800")
    return failures


def main() -> int:
    failures = size_failures()
    failures.extend("import cycle: " + " -> ".join(cycle) for cycle in find_cycles())
    if failures:
        print("Architecture gate failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Architecture gate passed: no static cycles; file-size budgets satisfied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
