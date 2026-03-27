"""Worker entrypoint module executed inside container for skill dispatch."""

import argparse
import json
import sys

from aegis.result import SkillResult

from aegis.skills.echo_skill import EchoSkill
from aegis.skills.llm_skill import LLMSkill


def run_skill(skill_name: str, action: str, params: dict) -> SkillResult:
    if skill_name == "echo":
        skill = EchoSkill()
    elif skill_name == "llm":
        skill = LLMSkill()
    else:
        return SkillResult.fail(f"Unknown skill '{skill_name}' in Container worker")

    return skill.execute(action, params)


def main():
    parser = argparse.ArgumentParser(description="Container skill worker")
    parser.add_argument("--skill", required=True)
    parser.add_argument("--action", required=True)
    parser.add_argument("--params", required=True)

    args = parser.parse_args()

    try:
        params = json.loads(args.params)
    except json.JSONDecodeError:
        print(json.dumps({"success": False, "error": "Invalid JSON params"}))
        sys.exit(2)

    result = run_skill(args.skill, args.action, params)
    output = {
        "success": result.success,
        "data": result.data,
        "error": result.error,
    }

    print(json.dumps(output, ensure_ascii=False))

    if result.success:
        sys.exit(0)
    sys.exit(1)


if __name__ == "__main__":
    main()
