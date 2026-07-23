"""Fail if a medallion schema name is hardcoded as a schema literal.

Enforces docs/architecture.md's core rule: schema names are parameterized via
bundle resources, never a literal string in .sql/.py, with one documented
exception (the fixed, shared raw-zip volume). Flags a schema-qualified table
reference or a raw volume path segment that names one of the three medallion
schemas directly, since that's exactly the pattern that silently stops
matching a dev-mode-prefixed schema. Add `# noqa: schema-literal` (or
`-- noqa: schema-literal` in SQL) on a line to allow a documented exception,
same convention as the existing sqlfluff noqa comments in this repo.
"""

import re
import sys

PATTERN = re.compile(r"(?<![$\w])(bronze|silver|gold)[./]\w")
NOQA = "noqa: schema-literal"


def check(path: str) -> list[str]:
    violations = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            if NOQA in line:
                continue
            if PATTERN.search(line):
                violations.append(f"{path}:{lineno}: {line.strip()}")
    return violations


def main() -> int:
    all_violations = [v for path in sys.argv[1:] for v in check(path)]
    if all_violations:
        print("Hardcoded medallion schema literal found — see docs/architecture.md:")
        for v in all_violations:
            print(f"  {v}")
        print(f'If this is a documented exception, add "{NOQA}" on the line.')
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
