# gitgen: Git 변경으로 커밋 메시지·PR 초안 만들기

Git 프로젝트 루트에서 실행하면 `git status`와 `git diff`로 변경 내용을 모으고, Google Gemini API로 **커밋 메시지** 또는 **Pull Request 제목·본문 초안**을 만들어 터미널에 출력하는 CLI 도구입니다.

- 결과는 **초안**입니다. 사람이 검토한 뒤 직접 복사해 적용합니다.
- 도구는 `git push`나 GitHub PR 생성을 하지 않습니다. 텍스트를 출력하는 데까지만 합니다.
- 한 번 실행할 때 API는 **1회만** 호출합니다. 자동 재시도는 하지 않습니다.

```text
python3 main.py commit | pr   (Git 프로젝트 루트에서)
  1) git status / git diff 수집 ── 변경이 없으면 "변경 사항이 없습니다" 출력 후 종료
  2) 안전 모드: diff 속 API 키·비밀번호·이메일 등을 가림
  3) 프롬프트 구성: 시스템 지시(역할·규칙·형식·금지) + 사용자 메시지(변경 이유·파일·diff)
  4) Gemini API 호출 1회 ── 키 없음·인증·네트워크 실패는 원인을 출력하고 종료
  5) 형식 검사(후처리): 제목 길이·PR 섹션 확인, 겉모양 자동 보정, 문제는 경고
  6) 변경 요약 → 커밋 메시지(또는 PR 제목/본문) → 형식 검사 결과를 구분선으로 출력
```

## 1. 설치·실행 환경

| 항목 | 내용 |
|---|---|
| Python | 3.10 이상 (개발·확인 환경: macOS, Python 3.14) |
| Git | `git` 명령이 설치되어 있어야 합니다 |
| 외부 패키지 | **없음**. 파이썬 표준 라이브러리만 사용하므로 `pip install`이 필요 없습니다 |
| AI API | Google Gemini API 키 ([Google AI Studio](https://aistudio.google.com/)에서 발급, 무료 등급으로 동작 확인) |

```bash
git clone <이 저장소 주소>
cd <저장소 폴더>
python3 main.py --help
```

> **macOS에서 python.org 설치판 Python을 쓰는 경우:** 처음 실행할 때 `SSL 인증서 확인 실패`가 나오면, Python과 함께 설치된 인증서 설치 스크립트를 한 번 실행합니다.
> ```bash
> "/Applications/Python 3.14/Install Certificates.command"   # 버전 숫자는 설치한 Python에 맞게
> ```
> 인증서 검증을 끄는 우회 방법은 보안상 쓰지 않습니다.

## 2. API 키 설정 (환경변수 `GEMINI_API_KEY`)

키는 **환경변수로만** 읽습니다. 코드나 저장소 파일에 키를 적지 않습니다.

```bash
# 키가 화면과 셸 기록(history)에 남지 않게 입력 (zsh)
read -s "GEMINI_API_KEY?키를 붙여넣고 Enter: " && export GEMINI_API_KEY && echo

# 확인: 키 값이 아니라 "길이"만 출력합니다 (0이면 설정 안 됨)
echo ${#GEMINI_API_KEY}
```

- bash에서는 `read -s -p "키를 붙여넣고 Enter: " GEMINI_API_KEY && export GEMINI_API_KEY && echo`를 씁니다.
- 환경변수는 **그 터미널 창에서만** 유지됩니다. 새 터미널을 열면 다시 설정합니다.
- `.env` 파일에 키를 보관하더라도 `.gitignore`에 `.env`, `.env.*`가 들어 있어 저장소에 올라가지 않습니다.
- 키는 요청 주소(URL)가 아니라 HTTP 헤더(`x-goog-api-key`)로 보내므로 오류 메시지나 로그에 찍히지 않습니다.

## 3. 명령 사용법

**반드시 Git 프로젝트 루트**(`.git` 폴더가 있는 곳)에서 실행합니다. 다른 프로젝트에 쓸 때는 그 프로젝트 루트로 이동한 뒤 이 저장소의 `main.py` 경로를 지정합니다. 예: `python3 ~/tools/gitgen/main.py commit`

### commit: 커밋 메시지 생성

```bash
git add 파일들                      # 담은 변경(git diff --cached)이 있으면 그것만 사용
python3 main.py commit              # 담은 것이 없으면 작업 폴더 변경(git diff) 사용
python3 main.py commit --context "응답이 잘려서 max_tokens 기본값을 올림"   # 변경 이유를 직접 알려 줌
```

- 출력: 제목 1줄(`종류: 요약`, 종류는 feat/fix/refactor/docs/test/chore) + 빈 줄 + 본문 불릿 1~2개(`- 파일: 바꾼 내용`)
- 아직 `git add` 하지 않은 새 파일은 diff에 내용이 없어 이름만 전달됩니다. 정확한 메시지를 원하면 먼저 `git add` 하세요.

### pr: PR 제목·본문 초안 생성

```bash
git switch -c feature/작업이름       # 작업 브랜치에서 커밋한 뒤
python3 main.py pr                  # main에서 갈라진 뒤의 커밋 전체(git diff main...HEAD) 사용
python3 main.py pr --base develop   # 기준 브랜치가 main이 아닐 때
```

- 출력: PR 제목 1줄 + 본문 `## Why` / `## What` / `## How to Test` (각 불릿 1개 이상)
- 커밋하지 않은 변경은 포함되지 않습니다(안내 메시지가 나옵니다).

### 옵션 (commit·pr 공통)

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--model` | `gemini-3.5-flash` | 사용할 Gemini 모델 |
| `--temperature` | `0.3` | 0~2. 낮을수록 일관된 표현, 높을수록 다양한 표현 |
| `--max-tokens` | `4096` | 응답 최대 길이(토큰). 이 모델은 답하기 전 "생각"에도 토큰을 쓰므로 넉넉히 둡니다 |
| `--safe-mode` / `--no-safe-mode` | 켜짐 | diff 속 민감정보를 가린 뒤 전송 |
| `--dry-run` | 꺼짐 | AI를 호출하지 않고, 변경 요약과 AI로 보낼 프롬프트 전체만 출력 (API 호출 0회) |
| `--context "TEXT"` | 없음 | 변경 이유. diff로는 알 수 없는 "왜"를 알려 PR Why 등을 추측하지 않게 함 |
| `--base` (pr 전용) | `main` | PR 비교 기준 브랜치 |

```bash
python3 main.py commit --temperature 0 --max-tokens 2048
python3 main.py pr --model gemini-3.5-flash --dry-run
```

## 4. 출력 예시

아래는 이 저장소 5단계 작업(`feature/formatter` 브랜치)에서 실제로 실행한 결과입니다.

### commit

```text
$ git add main.py gitgen/formatter.py tests/
$ python3 main.py commit

[INFO] 현재 브랜치: feature/formatter
[INFO] Git status 수집 완료: 5개 파일 변경 감지
[INFO] Git diff 수집 완료: 479줄 (git diff --cached, 스테이징된 변경)
[INFO] 스테이징되지 않은 변경 1개는 제외했습니다 (이번 커밋에 포함되지 않음).
[INFO] 안전 모드: 마스킹할 민감정보를 찾지 못했습니다.
[INFO] AI API 요청 중... (모델: gemini-3.5-flash, temperature: 0.3, max_tokens: 4096)
[INFO] API 호출 횟수: 1회
[INFO] 토큰 사용: 입력 7731, 출력 87, 생각 628 (종료 이유: STOP)
[INFO] 형식 검사 완료: 보정 0건, 경고 0건
[DONE] 커밋 메시지 생성 완료

--- 변경 요약 ---
A  gitgen/formatter.py              +277 -0
M  main.py                          +19 -4
A  tests/samples/broken_commit.txt  +5 -0
A  tests/samples/broken_pr.txt      +9 -0
A  tests/test_formatter.py          +115 -0
5개 파일, +425 -4
----------------------------------------

--- Commit Message ---
feat: AI 결과 형식 검사 및 변경 요약 기능 추가

- gitgen/formatter.py: AI 결과 다듬기, 규칙 검사 및 diff 기반 변경 요약 기능 구현
- main.py: 결과 출력과 dry-run 실행 단계에 형식 검사 및 변경 요약 적용
- tests/test_formatter.py: 포매터 모듈의 규칙 검사 및 후처리 단위 테스트 추가
----------------------------------------

--- 형식 검사 ---
[OK]   제목 31자 (권장 50자 이내, 최대 72자)
[OK]   본문 불릿 3개, 변경 파일 언급 3개 (불릿 1~2개 또는 파일 1~3개 언급)
----------------------------------------
[INFO] 생성된 문구는 초안입니다. 검토한 뒤 적용하세요.
```

> **검토 사례:** 형식 검사는 통과했지만 두 번째 불릿은 사실과 달랐습니다(dry-run에는 형식 검사가 없고 변경 요약만 추가됨). 실제 커밋(`0828b02`)은 이 부분과 빠진 샘플 파일 설명을 고친 뒤 적용했습니다. 형식 검사는 **모양**만 확인하므로 **내용**은 사람이 확인해야 합니다.

### pr

```text
$ python3 main.py pr

[INFO] 현재 브랜치: feature/formatter
[INFO] 브랜치 변경 파일 수집 완료: 5개 (main...HEAD 기준)
[INFO] Git diff 수집 완료: 479줄 (git diff main...HEAD, 이 브랜치의 커밋)
[INFO] 커밋되지 않은 변경 2개는 PR 초안에 포함되지 않습니다 (커밋 후 다시 실행하세요).
[INFO] 안전 모드: 마스킹할 민감정보를 찾지 못했습니다.
[INFO] AI API 요청 중... (모델: gemini-3.5-flash, temperature: 0.3, max_tokens: 4096)
[INFO] API 호출 횟수: 1회
[INFO] 토큰 사용: 입력 7773, 출력 273, 생각 834 (종료 이유: STOP)
[INFO] 형식 검사 완료: 보정 0건, 경고 0건
[DONE] PR 초안 생성 완료

--- 변경 요약 ---
A  gitgen/formatter.py              +277 -0
M  main.py                          +19 -4
A  tests/samples/broken_commit.txt  +5 -0
A  tests/samples/broken_pr.txt      +9 -0
A  tests/test_formatter.py          +115 -0
5개 파일, +425 -4
----------------------------------------

--- PR Title ---
AI 결과 후처리를 위한 형식 검사기 및 변경 요약 기능 추가
----------------------------------------

--- PR Body ---
## Why
- AI가 생성한 커밋 메시지 및 PR 초안의 형식을 자동 보정하고, 검사 내역과 파일 변경 요약을 함께 제공하기 위해

## What
- `gitgen/formatter.py`: AI 결과물 다듬기(제목 머리말/마침표/코드블록 제거, 불릿 기호 통일, 섹션 구조 보정) 및 diff 기반 변경 요약 집계 모듈 추가
- `main.py`: CLI 실행 시 `formatter`를 연동하여 변경 요약을 출력하고 결과물 후처리 및 검사 내역을 표시하도록 수정
- `tests/test_formatter.py`, `tests/samples/`: 형식 검사 기능 및 샘플 입력을 검증하는 단위 테스트 추가

## How to Test
- `python3 -m unittest discover tests -v` 명령을 실행하여 포맷터 단위 테스트를 진행합니다.
- `python3 -m gitgen.formatter pr < tests/samples/broken_pr.txt` 명령으로 가짜 응답 보정 동작을 확인합니다.
- `python3 main.py --dry-run` 명령으로 변경 요약 출력 및 실행 흐름을 확인합니다.
----------------------------------------

--- 형식 검사 ---
[OK]   PR 제목 34자 (최대 80자)
[OK]   섹션 3개와 불릿 수: Why 1 · What 3 · How to Test 3 (각 1개 이상)
----------------------------------------
[INFO] 생성된 문구는 초안입니다. 검토한 뒤 적용하세요.
```

> **검토 사례:** How to Test의 세 번째 명령 `python3 main.py --dry-run`은 그대로 실행하면 오류가 납니다. 명령(`commit`/`pr`)이 빠졌기 때문이며, `python3 main.py commit --dry-run`으로 고쳐 써야 합니다.

실행 화면 캡처: [commit](docs/screenshots/commit-output.png) · [pr](docs/screenshots/pr-output.png)

## 5. 출력 형식 검사 (후처리)

AI는 형식 지시를 대부분 따르지만 항상 따르지는 않습니다. 그래서 결과를 출력하기 전에 도구가 직접 검사합니다. 규칙을 어긴 결과를 AI에게 다시 요청(재생성)하지 않고 **후처리**를 택했습니다. API 호출을 1회로 고정해 비용과 시간을 예측할 수 있고, 개발 중 실측 10여 회에서 길이·섹션 위반이 없어 문제는 주로 겉모양이었기 때문입니다.

| 대상 | 규칙 | 처리 |
|---|---|---|
| 커밋 제목 | 최대 72자, 권장 50자 이내 | 51~72자: `[WARN]`만 표시 / 73자 이상: 단어 경계에서 72자 이내로 줄이고 원래 제목과 함께 `[WARN]` |
| 커밋 본문 | (선택) 불릿 1~2개 또는 변경 파일 1~3개 언급 | 벗어나면 `[WARN]` |
| PR 제목 | 1줄, 최대 80자 | 81자 이상: 단어 경계에서 줄이고 `[WARN]` |
| PR 본문 | `## Why` / `## What` / `## How to Test`, 각 불릿 1개 이상 | 섹션이나 불릿이 없으면 `- (작성 필요: …)` 불릿을 넣고 `[WARN]` |
| 겉모양 | — | ``` 표시, `제목:`·`**…**` 머리말, 제목 끝 마침표, `*`·`•` 불릿, `**Why**`·`### what:` 섹션 모양을 자동으로 고치고 `[FIX]` |

- 글자 수는 파이썬 `len()` 기준입니다(한글 한 글자 = 1자).
- 실제 AI는 위반을 거의 하지 않으므로, 위반 상황은 가짜 결과로 시험합니다.

```bash
python3 -m unittest discover tests -v                          # 규칙 위반 13가지 시험 (API·키 불필요)
python3 -m gitgen.formatter pr < tests/samples/broken_pr.txt   # 위반 샘플을 다듬는 과정 보기
```

시연 화면: [format-validation](docs/screenshots/format-validation.png). 82자 제목은 79자로 줄어들고, 빠진 How to Test 섹션이 추가되며, 머리말·불릿·섹션 모양이 보정됩니다.

## 6. 민감정보 대응 (안전 모드)

diff에는 코드에 적힌 글자가 그대로 들어가므로, 실수로 적은 키나 개인정보가 AI 서버로 전송될 수 있습니다. 안전 모드(기본 켜짐)는 전송 직전에 아래 패턴을 찾아 가립니다. `--context`로 넣은 글에도 같은 규칙을 적용합니다.

| 대상 | 예 | 바뀌는 글자 |
|---|---|---|
| Google API 키 (`AIza…`, `AQ.…`) · OpenAI/Anthropic 키(`sk-…`) | `AQ.Ab8F…` | `[MASKED_API_KEY]` |
| GitHub 토큰 · AWS 액세스 키 · 개인 키 블록 | `ghp_…`, `AKIA…`, `-----BEGIN … PRIVATE KEY-----` | `[MASKED_TOKEN]` 등 |
| 비밀번호·토큰 대입 | `password = "…"`, `DB_PASSWORD=…` | `[MASKED_SECRET]` |
| 개인정보 | 이메일, 주민등록번호, 휴대폰 번호 | `[MASKED_EMAIL]` 등 |

- 가린 건수가 로그에 나옵니다. 예: `[INFO] 안전 모드: 민감정보 마스킹 (Google API 키 1건, 이메일 1건)`
- **한계:** 패턴 마스킹은 알려진 모양만 잡습니다. 새로운 키 형식은 놓칠 수 있고(실제로 Google의 새 `AQ.` 형식 키를 위해 규칙을 추가했습니다), 규칙을 넓히면 정상 코드도 가려질 수 있습니다.
- 그래서 함께 쓰는 권장 사용법은 다음과 같습니다.
  1. 민감한 변경이 있을 수 있으면 먼저 `--dry-run`으로 **실제로 보낼 내용**을 확인합니다.
  2. 키는 코드·저장소에 두지 않습니다(환경변수, `.gitignore`의 `.env`).
  3. `--no-safe-mode`는 가릴 것이 없다고 확인한 경우에만 씁니다.

## 7. 비용·요청 횟수

- **한 번 실행에 API 1회.** 실패해도 자동으로 다시 부르지 않습니다. 로그 `API 호출 횟수: 1회`로 확인할 수 있습니다.
- 매 실행의 토큰 사용량을 출력합니다. 예: `토큰 사용: 입력 7731, 출력 87, 생각 628`
- 변경이 없으면 API를 호출하지 않고 종료합니다. `--dry-run`도 호출 0회입니다.
- 입력 토큰은 diff 크기에 비례합니다. 큰 변경은 커밋을 나눠서 실행하는 것이 비용과 품질 모두에 유리합니다.
- `--max-tokens`는 **상한**이지 사용량이 아닙니다. 실제로는 필요한 만큼만 씁니다. 다만 이 모델은 "생각"에 쓰는 토큰이 실행마다 크게 달라(같은 변경에서 약 540~1090), 상한이 작으면 답이 잘립니다. **잘린 응답은 미완성 결과를 보여 주지 않고 실패로 처리**합니다.
- Gemini 무료 등급은 분당·일일 요청 한도가 있습니다. 넘으면 `HTTP 429` 안내가 나오며, 잠시 후 다시 실행하면 됩니다.

## 8. 오류 메시지와 해결

모든 오류는 `[ERROR]`로 원인을 출력하고 종료 코드 1로 끝납니다.

| 상황 | 메시지(요약) | 해결 |
|---|---|---|
| 변경 없음 | `변경 사항이 없습니다. AI를 호출하지 않고 종료합니다.` | 정상 종료(코드 0) |
| 저장소 밖에서 실행 | `현재 폴더는 Git 저장소가 아닙니다…` | `git init` 된 프로젝트 루트에서 실행 |
| 하위 폴더에서 실행 | `현재 폴더는 Git 저장소의 하위 폴더입니다…` | `.git`이 있는 루트로 이동 |
| main에서 `pr` 실행 | `현재 'main' 브랜치입니다. PR 초안은 작업 브랜치에서 실행하세요` | 작업 브랜치로 이동 |
| 키 미설정 | `GEMINI_API_KEY 환경변수가 설정되지 않았습니다.` | 2장의 키 설정 |
| 잘못된 키 | `API 호출 실패 (HTTP 400) 인증 실패: API 키가 올바르지 않습니다.` | 키를 다시 확인·재발급 |
| 인터넷 끊김 | `네트워크 연결 실패: Gemini 서버에 연결할 수 없습니다…` | 연결 확인 |
| macOS SSL 인증서 | `SSL 인증서 확인 실패: …Install Certificates.command를 실행하세요.` | 1장의 인증서 설치 |
| 모델 이름 오류 | `API 호출 실패 (HTTP 404) 모델을 찾을 수 없습니다.` | `--model` 확인 |
| 요청 한도 초과 | `API 호출 실패 (HTTP 429) 요청 한도 초과…` | 잠시 후 다시 실행 |
| 응답이 한도에서 잘림 | `응답 미완성: max_tokens 한도에 걸려 … (생각 N, 출력 M)` | `--max-tokens` 값을 늘림 |

오류 화면 캡처: [키 없음](docs/screenshots/error-no-api-key.png) · [인증 실패](docs/screenshots/error-api-auth.png) · [네트워크](docs/screenshots/error-api-network.png) · [SSL 인증서](docs/screenshots/troubleshooting-ssl-cert.png) · [저장소 아님](docs/screenshots/error-not-git-repo.png) · [하위 폴더](docs/screenshots/error-not-git-root.png) · [변경 없음](docs/screenshots/no-changes.png) · [max_tokens 잘림](docs/screenshots/max-tokens-compare.png)

## 9. 프로젝트 구조

```text
main.py                  실행 진입점: 명령·옵션 해석, 전체 순서 지휘
gitgen/
├─ git_collector.py      git status / git diff 수집, 실행 위치 확인
├─ safe_mode.py          민감정보 마스킹 (정규식 패턴)
├─ prompts.py            시스템 지시 + 사용자 메시지 구성
├─ ai_client.py          Gemini REST 호출(urllib), 오류 원인 분류, 응답 해석
└─ formatter.py          형식 검사·후처리, 변경 요약
tests/
├─ test_formatter.py     형식 검사 단위 테스트 (unittest)
└─ samples/              규칙을 어긴 가짜 AI 결과 (시연용)
docs/screenshots/        실행 화면 캡처
```

각 모듈은 서로를 모르게 나눴습니다. Git 수집은 AI를 모르고, AI 호출은 Git을 모르며, 형식 검사는 글만 다룹니다. 그래서 한쪽을 바꿔도 다른 쪽에 영향이 없고, 따로 시험할 수 있습니다.
