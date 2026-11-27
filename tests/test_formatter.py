"""형식 검사(후처리) 시험: 일부러 규칙을 어긴 가짜 AI 결과를 넣어 본다.

실행 (레포 루트에서):  python3 -m unittest discover tests -v
API를 부르지 않으므로 키·인터넷 없이 실행된다.
"""

import unittest

from gitgen import formatter
from gitgen.git_collector import GitChanges


def levels(result):
    return [c.level for c in result.checks]


class CommitFormatTest(unittest.TestCase):
    def test_clean_commit_passes(self):
        """규칙을 지킨 커밋 메시지는 고치지 않고 OK만 남긴다"""
        text = "feat: 형식 검사 추가\n\n- gitgen/formatter.py: 제목 길이 검사"
        r = formatter.format_commit(text, ["gitgen/formatter.py"])
        self.assertEqual(r.text, text)
        self.assertEqual(levels(r), ["OK", "OK"])

    def test_fence_label_period_removed(self):
        """``` 표시, '제목:' 머리말, 끝 마침표를 자동으로 고친다 (FIX)"""
        text = "```\n제목: feat: 형식 검사 추가.\n- formatter.py: 추가\n```"
        r = formatter.format_commit(text, ["gitgen/formatter.py"])
        self.assertEqual(r.title, "feat: 형식 검사 추가")
        self.assertEqual(r.text, "feat: 형식 검사 추가\n\n- formatter.py: 추가")
        self.assertGreaterEqual(levels(r).count("FIX"), 4)  # ```, 머리말, 빈 줄, 마침표

    def test_title_over_recommended_warns_only(self):
        """제목 51~72자: 권장 초과 경고만 하고 그대로 둔다"""
        title = "feat: " + "가" * 50              # 56자
        r = formatter.format_commit(title)
        self.assertEqual(r.title, title)
        self.assertIn("WARN", levels(r))

    def test_title_boundary_50_and_72(self):
        """경계값: 정확히 50자는 OK, 정확히 72자는 자르지 않는다"""
        r50 = formatter.format_commit("feat: " + "가" * 44)   # 50자
        self.assertEqual(r50.checks[0].level, "OK")
        t72 = "feat: " + "가" * 66                          # 72자
        self.assertEqual(formatter.format_commit(t72).title, t72)

    def test_title_over_max_is_shortened(self):
        """제목 73자 이상: 단어 경계에서 72자 이내로 줄이고 경고한다"""
        title = "feat: " + " ".join(["프롬프트를"] * 20)
        r = formatter.format_commit(title)
        self.assertLessEqual(len(r.title), 72)
        self.assertFalse(r.title.endswith(" "))
        self.assertTrue(any(c.level == "WARN" and "원래" in c.message for c in r.checks))

    def test_star_bullets_normalized(self):
        """'* 항목', '• 항목' 불릿을 '- 항목'으로 통일한다"""
        r = formatter.format_commit("fix: 버그 수정\n\n* main.py: 수정\n• a.py: 수정")
        self.assertEqual(r.body, "- main.py: 수정\n- a.py: 수정")


class PRFormatTest(unittest.TestCase):
    GOOD = ("PR 제목\n\n## Why\n- 이유\n\n## What\n- 변경\n\n## How to Test\n- 확인")

    def test_clean_pr_passes(self):
        """세 섹션과 불릿이 모두 있으면 OK"""
        r = formatter.format_pr(self.GOOD)
        self.assertEqual(r.title, "PR 제목")
        self.assertNotIn("WARN", levels(r))

    def test_heading_styles_normalized(self):
        """'**Why**', '### what:', 'How to test' → '## Why' 등으로 통일"""
        text = "제목\n\n**Why**\n- a\n\n### what:\n- b\n\nHow to test\n- c"
        r = formatter.format_pr(text)
        for name in ("## Why", "## What", "## How to Test"):
            self.assertIn(name, r.body)
        self.assertIn("FIX", levels(r))
        self.assertNotIn("WARN", levels(r))

    def test_missing_section_added(self):
        """How to Test 섹션이 없으면 자리 표시 불릿과 함께 추가하고 경고"""
        r = formatter.format_pr("제목\n\n## Why\n- a\n\n## What\n- b")
        self.assertIn("## How to Test\n" + formatter.PLACEHOLDER, r.body)
        self.assertIn("WARN", levels(r))

    def test_section_without_bullet(self):
        """불릿 없는 섹션에는 제목 바로 아래 자리 표시 불릿을 넣는다"""
        r = formatter.format_pr("제목\n\n## Why\n그냥 문장\n\n## What\n- b\n\n## How to Test\n- c")
        self.assertIn("## Why\n" + formatter.PLACEHOLDER, r.body)

    def test_missing_title(self):
        """제목 없이 섹션부터 시작하면 제목이 없다고 경고"""
        r = formatter.format_pr("## Why\n- a\n\n## What\n- b\n\n## How to Test\n- c")
        self.assertTrue(r.title.startswith("(작성 필요"))
        self.assertIn("## Why", r.body)

    def test_pr_title_over_80(self):
        """PR 제목 81자 이상은 80자 이내로 줄인다"""
        r = formatter.format_pr(" ".join(["기능을"] * 30) + "\n\n" + self.GOOD.split("\n\n", 1)[1])
        self.assertLessEqual(len(r.title), 80)


class SummaryTest(unittest.TestCase):
    def test_counts_added_removed(self):
        """변경 요약: diff에서 파일별 +/- 줄 수를 센다"""
        diff = ("diff --git a/main.py b/main.py\n--- a/main.py\n+++ b/main.py\n"
                "@@ -1,2 +1,2 @@\n-old\n+new\n+more\n context\n")
        changes = GitChanges("b", ["M main.py"], ["new.txt"], diff, "src")
        text = formatter.summarize_changes(changes)
        self.assertIn("M  main.py  +2 -1", text)
        self.assertIn("?  new.txt", text)
        self.assertIn("2개 파일, +2 -1", text)


if __name__ == "__main__":
    unittest.main()
