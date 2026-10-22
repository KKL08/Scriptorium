from violet_refine.diffing import unified_diff


def test_unified_diff_shows_changed_line():
    diff = unified_diff("第一行\n第二行\n", "第一行\n第二行改了\n")
    assert "-第二行" in diff
    assert "+第二行改了" in diff
    assert diff.startswith("--- original")


def test_unified_diff_empty_for_identical_text():
    assert unified_diff("一样\n", "一样\n") == ""
