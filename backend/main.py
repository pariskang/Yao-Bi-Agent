from __future__ import annotations

import argparse
import json

from backend.skills.pipeline import run_case_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="Run YaoBi-Skill rule pipeline")
    parser.add_argument("--text", required=True, help="De-identified lumbar Bi case text")
    parser.add_argument("--json", action="store_true", help="Print full JSON instead of Markdown report")
    parser.add_argument("--use-llm", action="store_true", help="Enable optional Tao runtime overlay; falls back to deterministic report if unavailable or unsafe")
    args = parser.parse_args()
    result = run_case_pipeline(args.text, use_llm=args.use_llm)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["markdown_report"])


if __name__ == "__main__":
    main()
