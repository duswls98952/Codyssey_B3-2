"""AI에게 보낼 프롬프트(지시문) 만들기.

3단계: AI 연결을 시험하기 위한 임시 기본형이다.
4단계에서 커밋/PR 양식, 길이 규칙, 섹션 구조를 담아 다듬는다.
"""

from __future__ import annotations

from gitgen.git_collector import GitChanges


def _changes_block(changes: GitChanges, diff: str) -> str:
    """프롬프트에 붙일 변경 맥락(브랜치, 파일 목록, diff)."""
    files = changes.files + [f"? {path} (새 파일, 내용 없음)" for path in changes.untracked]
    return (f"[현재 브랜치]\n{changes.branch}\n\n"
            f"[변경 파일]\n" + "\n".join(files) + "\n\n"
            f"[diff]\n{diff or '(diff 내용 없음)'}\n")


def build_commit_prompt(changes: GitChanges, diff: str) -> str:
    return ("다음 Git 변경 사항을 보고 커밋 메시지를 한국어로 작성해 주세요.\n\n"
            + _changes_block(changes, diff))


def build_pr_prompt(changes: GitChanges, diff: str) -> str:
    return ("다음 Git 변경 사항을 보고 Pull Request 제목과 본문 초안을 한국어로 작성해 주세요.\n\n"
            + _changes_block(changes, diff))
