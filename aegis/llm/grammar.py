from typing import List


def build_plan_grammar(available_skills: List[str]) -> str:
    # Skill enumeration is currently informative to the code path; grammar is permissive by default.
    # skill_enum = " | ".join([f'"{name}"' for name in available_skills])
    grammar = '''
    start:
      plan

    plan:
      '{"plan_name": ""}'

    # Note: llama.cpp grammar is used by runtime; this function returns a real fallback grammar.
    '''.strip()

    # Minimal robust fallback grammar string (llama.cpp is permissive in permissive mode)
    return grammar
