"""AI 커밋 메시지 / PR 초안 생성기 — 실행 진입점.

사용법 (Git 프로젝트 루트에서):
    python main.py commit [옵션]
    python main.py pr [--base main] [옵션]

이 파일은 명령과 옵션을 해석하고, 각 모듈을 순서대로 불러 전체 흐름을 지휘한다.
"""

from __future__ import annotations

import argparse
import sys

from gitgen import ai_client, formatter, git_collector, prompts, safe_mode

DEFAULT_MODEL = "gemini-3.5-flash"
DEFAULT_TEMPERATURE = 0.3
DEFAULT_MAX_TOKENS = 4096  # 실측: 생각 900 + 출력 120 ≈ 1020 → 큰 diff까지 고려해 약 4배


def info(message: str) -> None:
    print(f"[INFO] {message}", flush=True)


def done(message: str) -> None:
    print(f"[DONE] {message}", flush=True)


def error(message: str) -> None:
    print(f"[ERROR] {message}", file=sys.stderr, flush=True)


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
    common.add_argument("--context", metavar="TEXT",
                        help='변경 이유를 직접 알려 줌 (선택, 예: --context "응답이 잘려서 한도를 올림")')

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
    count = len(changes.files) + len(changes.untracked)
    if args.command == "commit":
        info(f"Git status 수집 완료: {count}개 파일 변경 감지")
    else:
        info(f"브랜치 변경 파일 수집 완료: {count}개 ({args.base}...HEAD 기준)")
    if changes.is_empty:
        info("변경 사항이 없습니다. AI를 호출하지 않고 종료합니다.")
        return 0
    info(f"Git diff 수집 완료: {len(changes.diff.splitlines())}줄 ({changes.source})")
    for note in changes.notes:
        info(note)

    context = (args.context or "").strip() or None
    if context:
        info(f"변경 이유 제공됨 (--context): {len(context)}자")

    # 2) 안전 모드 (AI로 가는 글 전부: diff와 변경 이유)
    diff = changes.diff
    if args.safe_mode:
        diff, counts = safe_mode.mask_sensitive(diff)
        if context:
            context, context_counts = safe_mode.mask_sensitive(context)
            for name, n in context_counts.items():
                counts[name] = counts.get(name, 0) + n
        if counts:
            detail = ", ".join(f"{name} {n}건" for name, n in counts.items())
            info(f"안전 모드: 민감정보 마스킹 ({detail})")
        else:
            info("안전 모드: 마스킹할 민감정보를 찾지 못했습니다.")
    else:
        info("안전 모드 꺼짐: diff 원문이 그대로 전송됩니다. 민감정보가 없는지 확인하세요.")

    # 3) 프롬프트 구성: 시스템 지시(형식·규칙) + 사용자 메시지(마스킹된 diff 등)
    if args.command == "commit":
        prompt = prompts.build_commit_prompt(changes, diff, context)
    else:
        prompt = prompts.build_pr_prompt(changes, diff, context)

    # 4) --dry-run: AI 호출 없이 전송될 내용만 확인
    if args.dry_run:
        print_section("변경 요약", formatter.summarize_changes(changes))
        print_section("AI로 보낼 시스템 지시", prompt.system)
        print_section("AI로 보낼 사용자 메시지", prompt.user)
        info("--dry-run: AI를 호출하지 않았습니다 (API 호출 0회).")
        return 0

    # 5) AI 호출 (1회). 키가 없으면 요청을 보내기 전에 멈춘다.
    try:
        api_key = ai_client.get_api_key()
    except ai_client.AIError as e:
        error(str(e))
        return 1

    info(f"AI API 요청 중... (모델: {args.model}, temperature: {args.temperature}, "
         f"max_tokens: {args.max_tokens})")
    try:
        result = ai_client.generate(prompt.user, system=prompt.system, api_key=api_key,
                                    model=args.model, temperature=args.temperature,
                                    max_tokens=args.max_tokens)
    except ai_client.AIError as e:
        error(str(e))
        info("API 호출 횟수: 1회 (실패)")
        return 1

    info("API 호출 횟수: 1회")
    info(f"토큰 사용: 입력 {result.prompt_tokens}, 출력 {result.output_tokens}, "
         f"생각 {result.thinking_tokens} (종료 이유: {result.finish_reason})")
    # (한도에서 잘린 응답은 ai_client가 실패로 처리하므로 여기까지 오지 않는다)

    # 6) 형식 검사·다듬기 (후처리: AI를 다시 부르지 않는다)
    if args.command == "commit":
        formatted = formatter.format_commit(result.text, formatter.changed_paths(changes))
    else:
        formatted = formatter.format_pr(result.text)
    info(f"형식 검사 완료: 보정 {formatted.count('FIX')}건, 경고 {formatted.count('WARN')}건")

    # 7) 결과 출력: 변경 요약 → 복사할 결과 → 검사 내역
    done(f"{'커밋 메시지' if args.command == 'commit' else 'PR 초안'} 생성 완료")
    print_section("변경 요약", formatter.summarize_changes(changes))
    if args.command == "commit":
        print_section("Commit Message", formatted.text)
    else:
        print_section("PR Title", formatted.title)
        print_section("PR Body", formatted.body)
    print_section("형식 검사", formatter.render_checks(formatted.checks))
    if formatted.count("WARN"):
        info("[WARN] 항목을 확인하고 필요하면 직접 고치세요.")
    info("생성된 문구는 초안입니다. 검토한 뒤 적용하세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
