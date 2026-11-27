"""AI에게 보낼 프롬프트(지시문) 만들기.

프롬프트는 두 부분으로 나눈다.
  시스템 지시(system) : 매번 같은 "일하는 방식" — ① 역할 ② 규칙 ③ 출력 형식 ④ 금지
  사용자 메시지(user) : 매번 바뀌는 "재료"   — ⑤ 맥락(변경 이유·브랜치·파일) ⑥ diff(안전 모드 적용본)
3단계 임시 프롬프트는 형식을 정하지 않아 AI가 설명·여러 후보·마크다운을 섞어 냈다.
여기서는 "정확히 이 형식만" 쓰도록 지시해 결과를 그대로 검토·복사할 수 있게 한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from gitgen.git_collector import GitChanges


@dataclass
class Prompt:
    system: str   # 시스템 지시: 역할·규칙·형식·금지
    user: str     # 사용자 메시지: 이번 변경의 맥락과 diff


# 커밋·PR 공통 금지 사항 (④)
_COMMON_RULES = """\
[금지]
- diff와 변경 이유에 없는 내용을 지어내지 않습니다. 확실하지 않은 기능·효과·수치는 쓰지 않습니다.
- 변경 이유가 주어지지 않았고 diff로도 알 수 없으면, 이유를 추측하지 말고 무엇을 바꿨는지만 씁니다.
- "변경 이유가 제공되지 않았으므로" 같은 작성 과정에 대한 설명을 결과에 쓰지 않습니다. 결과에는 변경 내용만 씁니다.
- [MASKED_...] 로 가려진 값은 민감정보를 숨긴 것입니다. 원래 값을 추측하거나 언급하지 않습니다.
- 인사말, 설명, 여러 개의 후보, 마크다운 코드 블록(```)을 출력하지 않습니다. 정해진 형식의 결과 하나만 출력합니다.

[diff 읽는 법]
- '+'로 시작하는 줄은 추가된 줄, '-'로 시작하는 줄은 삭제된 줄, 공백으로 시작하는 줄은 바뀌지 않은 주변 맥락입니다.
- "(새 파일, 내용 없음)"으로 표시된 파일은 이름만 알 수 있습니다. 내용을 추측하지 않습니다."""


COMMIT_SYSTEM = f"""\
당신은 Git 커밋 메시지를 작성하는 도우미입니다. 주어진 변경 사항만 근거로 커밋 메시지 하나를 한국어로 작성합니다.

[규칙]
- 제목은 한 줄입니다. "종류: 요약" 모양으로 씁니다.
  종류는 feat(기능 추가), fix(버그 수정), refactor(구조 개선), docs(문서), test(테스트), chore(설정·기타) 중 하나입니다.
- 제목은 50자 이내를 목표로 하고, 절대 72자를 넘기지 않습니다. 끝에 마침표를 찍지 않습니다.
- 제목 다음에 빈 줄 하나, 그다음 본문을 씁니다.
- 본문은 1~2개의 불릿입니다. 각 불릿은 "- 파일 또는 모듈: 바꾼 내용" 모양이며, 핵심 변경을 다룬 파일·모듈 이름을 적습니다.

[출력 형식] 아래 형식 그대로, 다른 글 없이 출력합니다.
종류: 제목

- 파일 또는 모듈: 바꾼 내용
- 파일 또는 모듈: 바꾼 내용

{_COMMON_RULES}"""


PR_SYSTEM = f"""\
당신은 GitHub Pull Request 제목과 본문 초안을 작성하는 도우미입니다. 주어진 브랜치 변경 사항만 근거로 한국어로 작성합니다.

[규칙]
- 첫 줄은 PR 제목 한 줄입니다. 80자를 넘기지 않으며 "제목:" 같은 머리말을 붙이지 않습니다.
- 제목 다음에 빈 줄 하나, 그다음 본문을 씁니다.
- 본문은 ## Why, ## What, ## How to Test 세 섹션을 이 순서로 모두 포함합니다.
- 각 섹션에는 "- "로 시작하는 불릿이 1개 이상 있어야 합니다.
  Why: 왜 이 변경이 필요한지. 변경 이유가 주어지면 그것을 근거로 씁니다.
       주어지지 않으면 diff로 확인되는 목적(이 변경으로 무엇이 가능해지거나 해결되는지)만 씁니다.
  What: 무엇을 바꿨는지. 파일·모듈 이름을 함께 적습니다.
  How to Test: 리뷰어가 직접 확인할 수 있는 명령이나 절차. 실제로 테스트를 실행했다고 주장하지 않습니다.

[출력 형식] 아래 형식 그대로, 다른 글 없이 출력합니다.
PR 제목

## Why
- 이유

## What
- 변경 내용

## How to Test
- 확인 방법

{_COMMON_RULES}"""


def _changes_block(changes: GitChanges, diff: str, context: str | None) -> str:
    """⑤ 맥락 + ⑥ diff. 매 실행마다 달라지는 재료 부분."""
    files = changes.files + [f"? {path} (새 파일, 내용 없음)" for path in changes.untracked]
    reason = context or "(제공되지 않음)"
    return (f"[변경 이유 (작성자 제공)]\n{reason}\n\n"
            f"[현재 브랜치]\n{changes.branch}\n\n"
            f"[변경 파일]\n" + "\n".join(files) + "\n\n"
            f"[diff]\n{diff or '(diff 내용 없음)'}\n")


def build_commit_prompt(changes: GitChanges, diff: str, context: str | None = None) -> Prompt:
    user = ("아래 변경 사항으로 커밋 메시지를 작성해 주세요.\n\n"
            + _changes_block(changes, diff, context))
    return Prompt(system=COMMIT_SYSTEM, user=user)


def build_pr_prompt(changes: GitChanges, diff: str, context: str | None = None) -> Prompt:
    user = ("아래 브랜치 변경 사항으로 Pull Request 제목과 본문을 작성해 주세요.\n\n"
            + _changes_block(changes, diff, context))
    return Prompt(system=PR_SYSTEM, user=user)
