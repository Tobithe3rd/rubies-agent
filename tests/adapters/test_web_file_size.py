"""Tests for scripts/checks/check_web_file_size.py."""
import importlib.util
from pathlib import Path

import yaml

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "checks" / "check_web_file_size.py"
spec = importlib.util.spec_from_file_location("check_web_file_size", SCRIPT)
size_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(size_check)


def write_config(tmp_path, max_lines=250, python=None, web=None, exempt=None):
    path = tmp_path / "quality.yaml"
    path.write_text(yaml.safe_dump({
        "web_module": {
            "max_file_lines": max_lines,
            "include": {
                "python": python or [],
                "web": web or [],
            },
            "exempt": exempt or [],
        }
    }))
    return path


def test_count_lines_ignores_blank_comments_and_slashes(tmp_path):
    path = tmp_path / "sample.py"
    path.write_text(
        "import os\n"
        "\n"
        "# comment\n"
        "   # indented comment\n"
        "// slash comment\n"
        "x = 1\n"
        "  \n"
        "y = 2  # trailing comment counts\n"
    )
    assert size_check.count_lines(path) == 3


def test_count_lines_treats_block_and_jsx_comments_as_comments(tmp_path):
    path = tmp_path / "sample.tsx"
    path.write_text(
        "/* block comment\n"
        "   still a comment */\n"
        "const a = 1;\n"
        "{/* single line jsx comment */}\n"
        "{/* multi line jsx\n"
        "    comment */}\n"
        "const b = /* inline */ 2;\n"
    )
    assert size_check.count_lines(path) == 2


def test_count_lines_does_not_treat_css_hashes_as_comments(tmp_path):
    path = tmp_path / "sample.css"
    path.write_text("--accent: #b3123b;\n#main { color: red; }\n")
    assert size_check.count_lines(path) == 2


def test_collect_files_honours_include_and_exempt_globs(tmp_path):
    (tmp_path / "web" / "components" / "ui").mkdir(parents=True)
    (tmp_path / "web" / "node_modules").mkdir(parents=True)
    (tmp_path / "web" / "app").mkdir(parents=True)
    (tmp_path / "web" / "components" / "ui" / "big.tsx").write_text("x\n" * 10)
    (tmp_path / "web" / "node_modules" / "x.js").write_text("x\n")
    (tmp_path / "web" / "app" / "ok.tsx").write_text("x\n")
    (tmp_path / "web" / "next-env.d.ts").write_text("x\n")

    found = size_check.collect_files(
        tmp_path,
        ["web/**/*"],
        ["web/components/ui/**", "web/node_modules/**", "web/next-env.d.ts"],
    )
    assert [p.relative_to(tmp_path).as_posix() for p in found] == ["web/app/ok.tsx"]


def test_failing_output_names_the_offender(tmp_path, capsys):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "big.py").write_text("a = 1\nb = 2\nc = 3\n")
    config = write_config(tmp_path, max_lines=2, python=["src/**/*.py"])

    rc = size_check.main(["--scope", "python"], root=tmp_path, config_path=config)
    output = capsys.readouterr().out

    assert rc == 1
    assert "src/big.py: 3 > 2" in output
    assert "FAIL:" in output


def test_scope_flag_limits_the_checked_files(tmp_path, capsys):
    (tmp_path / "src").mkdir()
    (tmp_path / "web").mkdir()
    (tmp_path / "src" / "a.py").write_text("a = 1\n")
    (tmp_path / "web" / "a.tsx").write_text("x\n")
    config = write_config(tmp_path, python=["src/**/*.py"], web=["web/**/*"])

    rc = size_check.main(["--scope", "python"], root=tmp_path, config_path=config)
    python_output = capsys.readouterr().out
    assert rc == 0
    assert "src/a.py" in python_output
    assert "web/a.tsx" not in python_output

    rc = size_check.main(["--scope", "web"], root=tmp_path, config_path=config)
    web_output = capsys.readouterr().out
    assert rc == 0
    assert "web/a.tsx" in web_output
    assert "src/a.py" not in web_output

    rc = size_check.main(["--scope", "all"], root=tmp_path, config_path=config)
    all_output = capsys.readouterr().out
    assert rc == 0
    assert "web/a.tsx" in all_output
    assert "src/a.py" in all_output
