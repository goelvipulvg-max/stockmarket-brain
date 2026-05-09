import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.questdb_client import execute


def main():
    schema_path = os.path.join(os.path.dirname(__file__), "schema_v1.sql")
    with open(schema_path) as f:
        content = f.read()

    raw_blocks = content.split(";")
    statements = []
    for block in raw_blocks:
        lines = [l for l in block.strip().splitlines() if not l.strip().startswith("--")]
        cleaned = "\n".join(lines).strip()
        if cleaned:
            statements.append(cleaned)

    all_pass = True
    for i, stmt in enumerate(statements):
        preview = stmt.replace("\n", " ")[:80]
        try:
            execute(stmt)
            print(f"[PASS] stmt {i + 1}: {preview}...")
        except Exception as e:
            print(f"[FAIL] stmt {i + 1}: {e}")
            print(f"       SQL: {stmt[:300]}")
            all_pass = False

    if all_pass:
        print(f"\nAll {len(statements)} statements applied successfully.")
    else:
        print("\nOne or more statements failed — check output above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
