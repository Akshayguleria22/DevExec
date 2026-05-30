import argparse
import json
import sys

from app.tools.registry import execute_tool


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool", required=True)
    parser.add_argument("--input", required=True)
    args = parser.parse_args()

    try:
        payload = json.loads(args.input)
    except json.JSONDecodeError:
        payload = {"raw": args.input}

    result = execute_tool(args.tool, payload)
    json.dump(result, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
