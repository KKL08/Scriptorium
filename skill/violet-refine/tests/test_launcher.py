import subprocess
from pathlib import Path

LAUNCHER = Path(__file__).resolve().parents[1] / "scripts" / "violet-refine"


def test_launcher_works_through_symlink(tmp_path):
    # 常见安装方式是软链到 ~/.local/bin：脚本得解析到真实位置再向上找项目根
    link = tmp_path / "bin" / "violet-refine"
    link.parent.mkdir()
    link.symlink_to(LAUNCHER)
    result = subprocess.run([str(link), "--help"], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert "找不到项目根" not in result.stderr
