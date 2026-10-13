import json

from typer.testing import CliRunner

from sponsorscope.cli import app

runner = CliRunner()


def test_check_db_on_fresh_db(tmp_path):
    result = runner.invoke(app, ["check-db", "--db", str(tmp_path / "x.db")])
    assert result.exit_code == 0 and "ok" in result.output


def test_export_on_empty_db_writes_empty_index(tmp_path):
    result = runner.invoke(app, ["export", "--db", str(tmp_path / "x.db"), "--site", str(tmp_path / "site")])
    assert result.exit_code == 0, result.output
    index = json.loads((tmp_path / "site" / "data" / "index.json").read_text())
    assert index["countries"] == {}


def test_seed_loads_boards(tmp_path):
    seeds = tmp_path / "s.yaml"
    seeds.write_text("- {ats: lever, slug: acme, name: Acme}\n")
    result = runner.invoke(app, ["seed", "--db", str(tmp_path / "x.db"), "--seeds", str(seeds)])
    assert result.exit_code == 0 and "1 boards" in result.output


def test_all_registers_wired():
    from sponsorscope import cli
    assert [r.name for r in cli._registers()] == ["gb", "nl", "dk", "fi", "us", "ca", "ie"]
