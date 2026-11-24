"""Git 변경 사항 수집 모듈.

`git status`, `git diff` 실행 결과(터미널에 찍히는 글자)를 파이썬 데이터로 바꾼다.
이 모듈은 AI를 전혀 모른다. "무엇이 바뀌었나"만 책임진다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field


class GitError(Exception):
    """git 실행 실패, 또는 실행 위치가 잘못된 경우."""


@dataclass
class GitChanges:
    branch: str                 # 현재 브랜치 이름
    files: list[str]            # 변경 파일 목록 (예: "M main.py")
    untracked: list[str]        # 새로 만들었지만 아직 git add 하지 않은 파일
    diff: str                   # 변경 내용 텍스트 (git diff 출력)
    source: str                 # diff를 어떤 명령으로 읽었는지 (로그용)
    notes: list[str] = field(default_factory=list)  # 사용자에게 알릴 참고사항

    @property
    def is_empty(self) -> bool:
        return not self.files and not self.untracked


def run_git(*args: str) -> str:
    """git 명령을 실행하고, 화면에 찍힐 출력(stdout)을 문자열로 돌려준다."""
    # core.quotePath=false: 한글 파일명이 "\355\225\234" 같은 이스케이프로 깨지지 않게 한다.
    cmd = ["git", "-c", "core.quotePath=false", *args]
    result = subprocess.run(cmd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode != 0:
        reason = (result.stderr.strip().splitlines() or ["원인 불명"])[0]
        raise GitError(f"`git {' '.join(args)}` 실행 실패: {reason}")
    return result.stdout


def ensure_repo_root() -> None:
    """현재 폴더가 Git 프로젝트 루트(.git이 있는 곳)인지 확인한다."""
    if shutil.which("git") is None:
        raise GitError("git 명령을 찾을 수 없습니다. Git이 설치되어 있는지 확인하세요.")
    if os.path.exists(".git"):
        return
    try:
        run_git("status", "--porcelain")
    except GitError:
        raise GitError("현재 폴더는 Git 저장소가 아닙니다. "
                       "git init 된 프로젝트 루트에서 실행하세요.") from None
    raise GitError("현재 폴더는 Git 저장소의 하위 폴더입니다. "
                   ".git 폴더가 있는 프로젝트 루트로 이동해 실행하세요.")


def _parse_branch(header: str) -> str:
    """'## main...origin/main [ahead 1]' 같은 첫 줄에서 브랜치 이름만 뽑는다."""
    text = header[3:]
    if text.startswith("No commits yet on "):
        return text[len("No commits yet on "):]
    return text.split("...")[0].split(" ")[0]


def read_status() -> tuple[str, list[tuple[str, str]]]:
    """git status 결과를 (브랜치, [(상태코드 2글자, 경로), ...])로 바꾼다.

    상태코드 2글자: 왼쪽 = 스테이징(바구니) 상태, 오른쪽 = 작업 폴더 상태.
    예) "M " 스테이징된 수정, " M" 스테이징 전 수정, "A " 새로 추가, "??" 추적 안 되는 새 파일
    """
    out = run_git("status", "--porcelain=v1", "--branch", "--untracked-files=all")
    lines = out.splitlines()
    branch = "(알 수 없음)"
    if lines and lines[0].startswith("## "):
        branch = _parse_branch(lines[0])
        lines = lines[1:]
    entries = [(line[:2], line[3:]) for line in lines if line]
    return branch, entries


def collect_for_commit() -> GitChanges:
    """커밋 메시지용: 스테이징된 변경이 있으면 그것을, 없으면 작업 폴더 변경을 읽는다."""
    branch, entries = read_status()
    staged = [f"{code[0]} {path}" for code, path in entries if code[0] not in " ?"]
    unstaged = [f"{code[1]} {path}" for code, path in entries if code[1] not in " ?"]
    untracked = [path for code, path in entries if code == "??"]

    if staged:
        changes = GitChanges(branch, staged, [], run_git("diff", "--cached"),
                             "git diff --cached, 스테이징된 변경")
        skipped = len(unstaged) + len(untracked)
        if skipped:
            changes.notes.append(f"스테이징되지 않은 변경 {skipped}개는 제외했습니다 "
                                 "(이번 커밋에 포함되지 않음).")
        return changes

    changes = GitChanges(branch, unstaged, untracked, run_git("diff"),
                         "git diff, 스테이징 전 변경")
    if unstaged or untracked:
        changes.notes.append("아직 git add 하지 않은 변경입니다. 커밋 전에 git add 하세요.")
    if untracked:
        changes.notes.append(f"새 파일 {len(untracked)}개는 diff에 내용이 없어 파일 이름만 전달합니다.")
    return changes


def collect_for_pr(base: str) -> GitChanges:
    """PR 초안용: 기준 브랜치(base)에서 갈라진 뒤 현재 브랜치에 쌓인 커밋 전체를 읽는다."""
    branch, entries = read_status()
    if branch == base:
        raise GitError(f"현재 '{base}' 브랜치입니다. PR 초안은 작업 브랜치에서 실행하세요 "
                       "(예: git switch -c feature/작업이름).")
    try:
        names = run_git("diff", "--name-status", f"{base}...HEAD")
        diff = run_git("diff", f"{base}...HEAD")
    except GitError as e:
        raise GitError(f"기준 브랜치 '{base}'와 비교할 수 없습니다. "
                       f"--base 옵션으로 기준 브랜치를 지정하세요. ({e})") from None

    files = [" ".join(line.split("\t")) for line in names.splitlines() if line]
    changes = GitChanges(branch, files, [], diff, f"git diff {base}...HEAD, 이 브랜치의 커밋")
    if entries:
        changes.notes.append(f"커밋되지 않은 변경 {len(entries)}개는 PR 초안에 포함되지 않습니다 "
                             "(커밋 후 다시 실행하세요).")
    return changes
