"""AI 결과의 형식 검사와 다듬기(후처리), 변경 요약 만들기.

5단계 결정(후처리): 규칙을 어긴 결과를 AI에게 다시 요청하지 않고(API 호출 1회 유지),
도구가 직접 고치거나, 고칠 수 없으면 고친 흔적과 함께 경고해 사람에게 넘긴다.
  [FIX]  겉모양 문제를 자동으로 고침 (``` 표시, "제목:" 머리말, 마침표, 불릿 기호, 섹션 제목 모양)
  [WARN] 내용 문제는 표시만 하거나 최소한으로 맞춤 (긴 제목 자르기, 빠진 섹션 자리 표시)
  [OK]   규칙을 지킴
이 모듈은 API를 모르고, 글(문자열)만 다룬다. 그래서 가짜 결과로 시험할 수 있다(tests/).
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field

from gitgen.git_collector import GitChanges

COMMIT_TITLE_MAX = 72
COMMIT_TITLE_RECOMMENDED = 50
PR_TITLE_MAX = 80
PR_SECTIONS = ("Why", "What", "How to Test")
PLACEHOLDER = "- (작성 필요: AI가 이 섹션에 내용을 쓰지 않았습니다)"

# "제목:", "**PR 제목:**", "Commit message:" 같은 머리말
_TITLE_LABEL = re.compile(
    r"^\**\s*(?:커밋\s*메시지|커밋\s*제목|PR\s*제목|제목|commit\s*message|title|subject)\s*\**\s*[:：]\s*\**\s*",
    re.I)
# "## Why", "**Why**", "### How to test:", "Why:" 같은 섹션 제목 → "## Why"로 통일
_SECTION_HEADING = re.compile(
    r"^\s*(?:#{1,6}\s*)?\**\s*(why|what|how\s+to\s+test)\s*\**\s*[:：]?\s*\**\s*$", re.I)
_OTHER_BULLET = re.compile(r"^(\s*)[*•]\s+")   # "* 항목", "• 항목" → "- 항목"


@dataclass
class Check:
    level: str     # OK / FIX / WARN
    message: str


@dataclass
class Formatted:
    title: str
    body: str
    checks: list[Check] = field(default_factory=list)

    @property
    def text(self) -> str:
        """커밋 메시지 전체: 제목, 빈 줄, 본문."""
        return f"{self.title}\n\n{self.body}" if self.body else self.title

    def count(self, level: str) -> int:
        return sum(1 for c in self.checks if c.level == level)


# ---------------------------------------------------------------- 공통 다듬기

def _clean(text: str, checks: list[Check]) -> list[str]:
    """코드 블록 표시·줄 끝 공백·불릿 기호를 정리하고 줄 목록을 돌려준다."""
    lines = [line.rstrip() for line in text.strip().splitlines()]

    fences = [line for line in lines if line.strip().startswith("```")]
    if fences:
        lines = [line for line in lines if not line.strip().startswith("```")]
        checks.append(Check("FIX", "코드 블록 표시(```) 제거"))

    bullets = sum(1 for line in lines if _OTHER_BULLET.match(line))
    if bullets:
        lines = [_OTHER_BULLET.sub(r"\1- ", line) for line in lines]
        checks.append(Check("FIX", f"불릿 기호(*, •) {bullets}개를 '-'로 통일"))
    return lines


def _split_title(lines: list[str], checks: list[Check]) -> tuple[str, list[str]]:
    """첫 번째 내용 줄 = 제목, 나머지 = 본문. 제목의 머리말·꾸밈 기호를 벗긴다."""
    while lines and not lines[0].strip():
        lines = lines[1:]
    if not lines:
        return "", []
    title, rest = lines[0].strip(), lines[1:]

    original = title
    title = re.sub(r"^#{1,6}\s+", "", title)              # "# 제목" (마크다운 제목 기호)
    title = _TITLE_LABEL.sub("", title)                   # "제목: …"
    if len(title) >= 2 and title[0] == title[-1] and title[0] in "\"'`":
        title = title[1:-1].strip()                       # "…" / `…` 로 감싼 경우
    if title.startswith("**") and title.endswith("**"):
        title = title[2:-2].strip()                       # **…** 굵게 표시
    if title != original:
        checks.append(Check("FIX", f"제목 머리말·꾸밈 기호 제거 (원래: {original})"))

    if rest and rest[0].strip():
        checks.append(Check("FIX", "제목과 본문 사이에 빈 줄 추가"))
    body = "\n".join(rest).strip()
    body = re.sub(r"\n{3,}", "\n\n", body)                # 연속 빈 줄은 하나로
    return title, body.splitlines() if body else []


def _shorten(title: str, limit: int) -> str:
    """limit자 이내로 자른다. 단어 중간에서 끊지 않고, 끝에 남은 연결어는 뗀다."""
    if len(title) <= limit:
        return title
    cut = title[:limit]
    if " " in cut:
        cut = cut[:cut.rfind(" ")]
    cut = cut.rstrip(" ,·:;-")
    for tail in (" 및", " 그리고", " 와", " 과", " and", " &"):
        if cut.endswith(tail):
            cut = cut[: -len(tail)].rstrip(" ,·:;-")
    return cut


def _check_title(title: str, limit: int, recommended: int | None,
                 label: str, checks: list[Check]) -> str:
    if not title:
        checks.append(Check("WARN", f"{label}이 없습니다. 직접 작성하세요."))
        return "(작성 필요: 제목)"
    if len(title) > limit:
        short = _shorten(title, limit)
        checks.append(Check("WARN", f"{label} {len(title)}자 → 최대 {limit}자 초과라 {len(short)}자로 줄임. "
                                    f"의미가 맞는지 확인하세요 (원래: {title})"))
        return short
    if recommended and len(title) > recommended:
        checks.append(Check("WARN", f"{label} {len(title)}자: 권장 {recommended}자 초과 "
                                    f"(최대 {limit}자 이내라 그대로 둠)"))
    else:
        rule = f"권장 {recommended}자 이내, 최대 {limit}자" if recommended else f"최대 {limit}자"
        checks.append(Check("OK", f"{label} {len(title)}자 ({rule})"))
    return title


# ---------------------------------------------------------------- 커밋

def format_commit(text: str, paths: list[str] | None = None) -> Formatted:
    """커밋 메시지: 제목 1줄(최대 72자, 권장 50자) + 선택 본문(불릿 1~2개 또는 파일 1~3개 언급)."""
    checks: list[Check] = []
    title, body_lines = _split_title(_clean(text, checks), checks)

    if title.endswith(".") and not title.endswith(".."):
        title = title[:-1].rstrip()
        checks.append(Check("FIX", "제목 끝 마침표 제거"))
    title = _check_title(title, COMMIT_TITLE_MAX, COMMIT_TITLE_RECOMMENDED, "제목", checks)

    body = "\n".join(body_lines)
    if not body:
        checks.append(Check("OK", "본문 없음 (제목만, 본문은 선택)"))
    else:
        bullets = sum(1 for line in body_lines if line.lstrip().startswith("- "))
        mentioned = [p for p in (paths or [])
                     if p in body or p.rsplit("/", 1)[-1] in body]
        detail = f"불릿 {bullets}개, 변경 파일 언급 {len(mentioned)}개"
        if 1 <= bullets <= 2 or 1 <= len(mentioned) <= 3:
            checks.append(Check("OK", f"본문 {detail} (불릿 1~2개 또는 파일 1~3개 언급)"))
        else:
            checks.append(Check("WARN", f"본문 {detail}: 불릿 1~2개 또는 파일 1~3개 언급 기준을 "
                                        "벗어났습니다. 본문을 줄이거나 다듬으세요."))
    return Formatted(title, body, checks)


# ---------------------------------------------------------------- PR

def format_pr(text: str) -> Formatted:
    """PR: 제목 1줄(최대 80자) + 본문(## Why / ## What / ## How to Test, 각 불릿 1개 이상)."""
    checks: list[Check] = []
    lines = _clean(text, checks)

    # 첫 줄이 곧바로 섹션 제목이면 AI가 PR 제목을 빼먹은 것
    first = next((line for line in lines if line.strip()), "")
    if _SECTION_HEADING.match(first):
        title, body_lines = "", lines
    else:
        title, body_lines = _split_title(lines, checks)
    title = _check_title(title, PR_TITLE_MAX, None, "PR 제목", checks)

    out: list[str] = []
    heading_at: dict[str, int] = {}
    bullets = {name: 0 for name in PR_SECTIONS}
    reshaped = 0
    current = None
    for line in body_lines:
        m = _SECTION_HEADING.match(line)
        if m:
            key = re.sub(r"\s+", " ", m.group(1).lower())
            current = {"why": "Why", "what": "What", "how to test": "How to Test"}[key]
            if line.strip() != f"## {current}":
                reshaped += 1
            out.append(f"## {current}")
            heading_at.setdefault(current, len(out) - 1)
            continue
        if line.startswith("#"):
            current = None                       # 그 밖의 섹션(## 참고 등)은 세지 않는다
        elif current and line.lstrip().startswith("- "):
            bullets[current] += 1
        out.append(line)
    if reshaped:
        checks.append(Check("FIX", f"섹션 제목 {reshaped}개를 '## 이름' 모양으로 통일"))

    # 불릿이 없는 섹션: 제목 바로 아래에 자리 표시 불릿 (뒤에서부터 넣어야 위치가 안 밀린다)
    empty = [name for name in PR_SECTIONS if name in heading_at and bullets[name] == 0]
    for name in sorted(empty, key=lambda n: heading_at[n], reverse=True):
        out.insert(heading_at[name] + 1, PLACEHOLDER)
    for name in empty:
        checks.append(Check("WARN", f"## {name} 섹션에 불릿이 없어 자리 표시 불릿을 넣었습니다. 직접 채우세요."))

    # 아예 없는 섹션: 끝에 섹션과 자리 표시 불릿 추가
    missing = [name for name in PR_SECTIONS if name not in heading_at]
    for name in missing:
        out += ["", f"## {name}", PLACEHOLDER]
        checks.append(Check("WARN", f"## {name} 섹션이 없어 추가했습니다. 직접 채우세요."))

    if not empty and not missing:
        counts = " · ".join(f"{name} {bullets[name]}" for name in PR_SECTIONS)
        checks.append(Check("OK", f"섹션 3개와 불릿 수: {counts} (각 1개 이상)"))

    body = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    return Formatted(title, body, checks)


# ---------------------------------------------------------------- 출력용

def render_checks(checks: list[Check]) -> str:
    return "\n".join(f"[{c.level}]{' ' * (5 - len(c.level))}{c.message}" for c in checks)


def changed_paths(changes: GitChanges) -> list[str]:
    """'M main.py', 'R100 old new' 같은 항목에서 파일 경로만 꺼낸다."""
    return [entry.split()[-1] for entry in changes.files] + list(changes.untracked)


def summarize_changes(changes: GitChanges) -> str:
    """변경 요약: 파일별 상태와 추가/삭제 줄 수. AI 없이 diff에서 직접 센다(정확, 토큰 0)."""
    added: dict[str, int] = {}
    removed: dict[str, int] = {}
    binary: set[str] = set()
    current = None
    for line in changes.diff.splitlines():
        if line.startswith("diff --git "):
            current = line.rsplit(" b/", 1)[-1]
            added.setdefault(current, 0)
            removed.setdefault(current, 0)
        elif current is None:
            continue
        elif line.startswith("Binary files"):
            binary.add(current)
        elif line.startswith("+") and not line.startswith("+++"):
            added[current] += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed[current] += 1

    rows = [(entry.split()[0][0], entry.split()[-1]) for entry in changes.files]
    rows += [("?", path) for path in changes.untracked]
    width = max((len(path) for _, path in rows), default=0)
    lines = []
    for status, path in rows:
        if status == "?":
            stat = "(새 파일, 아직 git add 전)"
        elif path in binary:
            stat = "(바이너리)"
        else:
            stat = f"+{added.get(path, 0)} -{removed.get(path, 0)}"
        lines.append(f"{status}  {path:<{width}}  {stat}")
    lines.append(f"{len(rows)}개 파일, +{sum(added.values())} -{sum(removed.values())}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 단독 시험

if __name__ == "__main__":
    # AI 없이 형식 검사만 시험: 직접 넣은 글을 검사한다.
    #   python3 -m gitgen.formatter pr < 시험할_글.txt
    kind = sys.argv[1] if len(sys.argv) > 1 else "commit"
    result = format_pr(sys.stdin.read()) if kind == "pr" else format_commit(sys.stdin.read())
    print(f"--- 다듬은 결과 ({kind}) ---")
    print(result.title if kind == "commit" and not result.body else
          f"{result.title}\n\n{result.body}")
    print("--- 형식 검사 ---")
    print(render_checks(result.checks))
