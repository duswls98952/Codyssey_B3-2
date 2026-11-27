"""Gemini API 호출 모듈 (REST).

1단계에서 curl로 보냈던 요청을 파이썬 표준 라이브러리(urllib)로 보낸다.
  요청 만들기 → 전송 → 상태 코드 확인 → 응답 JSON에서 글 꺼내기
실패하면 원인별 메시지를 담아 AIError를 던진다. 이 모듈은 Git을 전혀 모른다.
"""

from __future__ import annotations

import json
import os
import socket
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass

API_KEY_ENV = "GEMINI_API_KEY"
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
TIMEOUT_SECONDS = 60


class AIError(Exception):
    """API 호출 실패. 메시지에 사용자가 이해할 수 있는 원인을 담는다."""


@dataclass
class AIResult:
    text: str              # AI가 쓴 글
    finish_reason: str     # 멈춘 이유: STOP(다 씀), MAX_TOKENS(길이 한도) 등
    prompt_tokens: int     # 입력(프롬프트) 토큰 수
    output_tokens: int     # 출력(답변) 토큰 수
    thinking_tokens: int   # 답을 쓰기 전 "생각"에 쓴 토큰 수


def get_api_key() -> str:
    """환경변수에서 API 키를 읽는다. 코드에는 키를 절대 적지 않는다."""
    key = os.environ.get(API_KEY_ENV, "").strip()
    if not key:
        raise AIError(
            f"{API_KEY_ENV} 환경변수가 설정되지 않았습니다.\n"
            f'        예) read -s "{API_KEY_ENV}?키를 붙여넣고 Enter: " && export {API_KEY_ENV}'
        )
    return key


def build_request_body(prompt: str, temperature: float, max_tokens: int,
                       system: str | None = None) -> dict:
    """요청 본문(JSON). CLI 옵션이 generationConfig로 들어간다."""
    body: dict = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,      # --temperature
            "maxOutputTokens": max_tokens,   # --max-tokens
        },
    }
    if system:
        # 시스템 지시: 대화 내용과 따로, "어떻게 답할지"를 정하는 칸
        body["systemInstruction"] = {"parts": [{"text": system}]}
    return body


def generate(prompt: str, *, api_key: str, model: str,
             temperature: float, max_tokens: int, system: str | None = None) -> AIResult:
    """Gemini에 요청을 1회 보내고 결과를 돌려준다. 자동 재시도는 하지 않는다."""
    url = f"{BASE_URL}/{model}:generateContent"           # --model은 주소에 들어간다
    body = json.dumps(build_request_body(prompt, temperature, max_tokens, system)).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "x-goog-api-key": api_key,   # 키는 주소(URL)가 아니라 헤더로 보낸다 → 오류 메시지·로그에 안 찍힘
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        # 서버까지는 닿았지만, 서버가 실패 상태 코드(4xx/5xx)로 답한 경우
        raw = e.read().decode("utf-8", errors="replace")
        raise AIError(_explain_http_error(e.code, raw)) from None
    except urllib.error.URLError as e:
        # 서버에 닿지도 못한 경우 (인터넷 끊김, 주소 찾기 실패, 연결 시간 초과)
        if isinstance(e.reason, (socket.timeout, TimeoutError)):
            raise AIError(_timeout_message()) from None
        if isinstance(e.reason, ssl.SSLCertVerificationError):
            # 인터넷 문제가 아니라, 이 컴퓨터의 Python에 인증서 목록이 없어 서버 신원을 확인 못 한 경우
            raise AIError("SSL 인증서 확인 실패: Python이 Gemini 서버의 인증서를 검증하지 못했습니다. "
                          "macOS에서 python.org 설치판을 쓴다면 "
                          "'/Applications/Python 3.x/Install Certificates.command'를 실행하세요. "
                          f"(원인: {e.reason})") from None
        raise AIError("네트워크 연결 실패: Gemini 서버에 연결할 수 없습니다. "
                      f"인터넷 연결을 확인하세요. (원인: {e.reason})") from None
    except (socket.timeout, TimeoutError):
        # 연결은 됐지만 응답을 기다리다 시간 초과
        raise AIError(_timeout_message()) from None

    return _parse_response(raw)


def _timeout_message() -> str:
    return (f"시간 초과: {TIMEOUT_SECONDS}초 동안 Gemini 서버의 응답이 없습니다. "
            "잠시 후 다시 시도하세요.")


def _explain_http_error(code: int, raw: str) -> str:
    """상태 코드와 서버가 보낸 오류 본문으로 원인 메시지를 만든다."""
    detail = raw[:200] or "(본문 없음)"
    try:
        err = json.loads(raw).get("error", {})
        detail = f"{err.get('status', '')} {err.get('message', '')}".strip() or detail
    except (ValueError, AttributeError):
        pass  # 본문이 JSON이 아니면 앞부분을 그대로 보여 준다

    if code == 400 and "api key" in detail.lower():
        hint = "인증 실패: API 키가 올바르지 않습니다."
    else:
        hint = {
            400: "잘못된 요청입니다. 옵션 값(--temperature, --max-tokens 등)을 확인하세요.",
            401: "인증 실패: API 키가 올바르지 않거나 만료되었습니다.",
            403: "권한 없음: 이 키로는 해당 API·모델을 사용할 수 없습니다.",
            404: "모델을 찾을 수 없습니다. --model 이름을 확인하세요.",
            429: "요청 한도 초과: 무료 등급 한도를 넘었습니다. 잠시 후 다시 시도하세요.",
        }.get(code, "Gemini 서버 오류입니다. 잠시 후 다시 시도하세요."
              if code >= 500 else "요청이 실패했습니다.")
    return f"API 호출 실패 (HTTP {code}) {hint}\n        서버 메시지: {detail}"


def _parse_response(raw: str) -> AIResult:
    """성공 응답(JSON)에서 AI가 쓴 글과 토큰 사용량을 꺼낸다."""
    try:
        data = json.loads(raw)
    except ValueError:
        raise AIError(f"응답을 해석할 수 없습니다 (JSON이 아님): {raw[:200]}") from None

    usage = data.get("usageMetadata", {})
    thinking = usage.get("thoughtsTokenCount", 0)
    candidates = data.get("candidates") or []
    if not candidates:
        reason = data.get("promptFeedback", {}).get("blockReason")
        raise AIError("AI가 응답을 만들지 않았습니다"
                      + (f" (차단 사유: {reason})." if reason else "."))

    candidate = candidates[0]
    finish = candidate.get("finishReason", "UNKNOWN")
    parts = candidate.get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()

    if finish == "MAX_TOKENS":
        # 한도에서 멈췄다면 결과는 확실히 미완성이다. 일부라도 썼든 못 썼든
        # 잘린 글을 "완료"로 보여 주지 않고 실패로 처리한다(복사해 쓰는 사고 방지).
        output = usage.get("candidatesTokenCount", 0)
        state = "글을 쓰기 전에 멈췄습니다" if not text else "글을 쓰는 도중에 잘렸습니다"
        raise AIError(f"응답 미완성: max_tokens 한도에 걸려 {state} "
                      f"(생각 {thinking}, 출력 {output}). --max-tokens 값을 늘려 다시 실행하세요.")
    if not text:
        raise AIError(f"응답이 비어 있습니다 (finishReason: {finish}).")

    return AIResult(
        text=text,
        finish_reason=finish,
        prompt_tokens=usage.get("promptTokenCount", 0),
        output_tokens=usage.get("candidatesTokenCount", 0),
        thinking_tokens=thinking,
    )
