"""AI 커밋 메시지 / PR 초안 생성기 — 실행 진입점.

사용법 (Git 프로젝트 루트에서):
    python main.py commit [옵션]
    python main.py pr [--base main] [옵션]

이 파일은 명령과 옵션을 해석하고, 각 모듈을 순서대로 불러 전체 흐름을 지휘한다.
"""

from __future__ import annotations

import argparse
import sys

from gitgen import git_collector, safe_mode

DEFAULT_MODEL = "gemini-3.5-flash"
DEFAULT_TEMPERATURE = 0.3
DEFAULT_MAX_TOKENS = 1024


def info(message: str) -> None:
    print(f"[INFO] {message}")


def error(message: str) -> None:
    print(f"[ERROR] {message}", file=sys.stderr)


def print_section(title: str, body: str) -> None:
    """구분선으로 감싼 출력 블록."""
    print(f"\n--- {title} ---")
    print(body.rstrip())
    print("-" * 40)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="main.py",
        description="Git 변경 사항으로 커밋 메시지·PR 초안을 생성합니다.",
    )

    # commit / pr 공통 옵션
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--model", default=DEFAULT_MODEL,
                        help="사용할 Gemini 모델 (기본: %(default)s)")
    common.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE,
                        help="0에 가까울수록 일관적, 높을수록 다양한 표현, 범위 0~2 (기본: %(default)s)")
    common.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS,
                        help="응답 최대 길이(토큰) (기본: %(default)s)")
    common.add_argument("--safe-mode", action=argparse.BooleanOptionalAction, default=True,
                        help="diff 속 API 키·이메일 등을 가린 뒤 전송 (기본: 켜짐)")
    common.add_argument("--dry-run", action="store_true",
                        help="AI를 호출하지 않고, AI로 보낼 변경 내용만 출력")

    sub = parser.add_subparsers(dest="command", required=True, metavar="{commit,pr}")
    sub.add_parser("commit", parents=[common], help="커밋 메시지 생성")
    pr = sub.add_parser("pr", parents=[common], help="PR 제목/본문 초안 생성")
    pr.add_argument("--base", default="main",
                    help="PR 비교 기준 브랜치 (기본: %(default)s)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not 0 <= args.temperature <= 2:
        parser.error("--temperature는 0~2 사이 값이어야 합니다.")
    if args.max_tokens <= 0:
        parser.error("--max-tokens는 1 이상이어야 합니다.")

    # 1) Git 변경 사항 수집
    try:
        git_collector.ensure_repo_root()
        if args.command == "commit":
            changes = git_collector.collect_for_commit()
        else:
            changes = git_collector.collect_for_pr(args.base)
    except git_collector.GitError as e:
        error(str(e))
        return 1

    info(f"현재 브랜치: {changes.branch}")
    info(f"Git status 수집 완료: {len(changes.files) + len(changes.untracked)}개 파일 변경 감지")
    if changes.is_empty:
        info("변경 사항이 없습니다. AI를 호출하지 않고 종료합니다.")
        return 0
    info(f"Git diff 수집 완료: {len(changes.diff.splitlines())}줄 ({changes.source})")
    for note in changes.notes:
        info(note)

    # 2) 안전 모드
    diff = changes.diff
    if args.safe_mode:
        diff, counts = safe_mode.mask_sensitive(diff)
        if counts:
            detail = ", ".join(f"{name} {n}건" for name, n in counts.items())
            info(f"안전 모드: 민감정보 마스킹 ({detail})")
        else:
            info("안전 모드: 마스킹할 민감정보를 찾지 못했습니다.")
    else:
        info("안전 모드 꺼짐: diff 원문이 그대로 전송됩니다. 민감정보가 없는지 확인하세요.")

    # 3) --dry-run: AI 호출 없이 전송될 내용만 확인
    if args.dry_run:
        file_lines = changes.files + [f"? {path} (새 파일)" for path in changes.untracked]
        print_section("변경 파일", "\n".join(file_lines))
        print_section("AI로 보낼 diff", diff or "(diff 내용 없음)")
        info("--dry-run: AI를 호출하지 않았습니다 (API 호출 0회).")
        return 0

    info("AI 호출은 3단계에서 연결합니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
