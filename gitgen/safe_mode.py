"""안전 모드: AI로 보내기 전에 diff 속 민감정보를 가린다.

요구사항의 방식 (A) "특정 패턴 마스킹"을 구현한다.
규칙은 위에서부터 차례로 적용한다. 구체적인 키 모양을 먼저 가리고,
그다음 "password = ..." 같은 일반 규칙과 개인정보를 가린다.
"""

from __future__ import annotations

import re

# 이미 가린 값([MASKED_...])을 다시 가리지 않기 위한 조건
_NOT_MASKED = r"(?!\[MASKED_)"

# (규칙 이름, 정규식, 바꿀 글자)
RULES: list[tuple[str, re.Pattern[str], str]] = [
    # Google 키는 두 형식이 있다: 기존 Standard key "AIza…", 새 Auth key "AQ.…"(AI Studio 신규 발급)
    ("Google API 키", re.compile(r"AIza[0-9A-Za-z_\-]{35}"), "[MASKED_API_KEY]"),
    ("Google API 키(AQ. 형식)", re.compile(r"\bAQ\.[0-9A-Za-z_\-.]{40,}"), "[MASKED_API_KEY]"),
    ("OpenAI/Anthropic 키", re.compile(r"sk-[A-Za-z0-9_\-]{20,}"), "[MASKED_API_KEY]"),
    ("GitHub 토큰", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"), "[MASKED_TOKEN]"),
    ("AWS 액세스 키", re.compile(r"AKIA[0-9A-Z]{16}"), "[MASKED_AWS_KEY]"),
    ("개인 키 파일 내용",
     re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
     "[MASKED_PRIVATE_KEY]"),
    # password = "...", "api_key": "..." 처럼 따옴표로 감싼 값 (4글자 이상)
    ("비밀번호·토큰 값",
     re.compile(r"(?i)(\w*(?:password|passwd|secret|token|api_?key)\w*[\"']?\s*[:=]\s*)"
                r"([\"'])" + _NOT_MASKED + r"([^\"'\n]{4,})\2"),
     r"\1\2[MASKED_SECRET]\2"),
    # .env 형식: DB_PASSWORD=값 (따옴표 없음). 이름이 키워드로 "끝나는" 경우만 본다.
    # (MAX_TOKENS = 1024 같은 일반 설정값을 비밀값으로 오인하지 않기 위해)
    ("비밀번호·토큰 값(.env 형식)",
     re.compile(r"(?m)^([+\- ]?\s*[A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|ACCESS_KEY)\s*=\s*)"
                + _NOT_MASKED + r"([^\s\"'#]{4,})\s*$"),
     r"\1[MASKED_SECRET]"),
    ("이메일", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[MASKED_EMAIL]"),
    ("주민등록번호", re.compile(r"\b\d{6}-[1-4]\d{6}\b"), "[MASKED_RRN]"),
    ("휴대폰 번호", re.compile(r"\b01[016789]-?\d{3,4}-?\d{4}\b"), "[MASKED_PHONE]"),
]


def mask_sensitive(text: str) -> tuple[str, dict[str, int]]:
    """민감정보를 가린 텍스트와 {규칙 이름: 가린 개수}를 돌려준다."""
    counts: dict[str, int] = {}
    for name, pattern, replacement in RULES:
        text, n = pattern.subn(replacement, text)
        if n:
            counts[name] = n
    return text, counts
