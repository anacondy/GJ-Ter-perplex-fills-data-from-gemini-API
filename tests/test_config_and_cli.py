"""Tests for configuration, secret handling and the CLI surface."""

from __future__ import annotations

import json

import pytest

from gjter.cli import main
from gjter.config import ConfigError, load_api_key
from gjter.providers import get_provider
from gjter.providers.base import ProviderError


class TestApiKey:
    def test_reads_gemini_env_var(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "real-key-123")
        assert load_api_key() == "real-key-123"

    def test_falls_back_to_google_env_var(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setenv("GOOGLE_API_KEY", "other-key")
        assert load_api_key() == "other-key"

    def test_explicit_argument_wins(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "env-key")
        assert load_api_key("explicit") == "explicit"

    @pytest.mark.parametrize("placeholder", ["KEY HERE", "YOUR_API_KEY", "", "  "])
    def test_committed_placeholders_are_rejected(self, monkeypatch, placeholder):
        """'KEY HERE' was the committed value; it must not count as a key."""
        monkeypatch.setenv("GEMINI_API_KEY", placeholder)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        with pytest.raises(ConfigError):
            load_api_key()

    def test_missing_key_raises_actionable_error(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
            load_api_key()

    def test_optional_mode_returns_none(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        assert load_api_key(required=False) is None


class TestNoSecretsInSource:
    def test_no_api_key_literal_in_repository(self):
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        pattern = re.compile(r"AIza[0-9A-Za-z_\-]{35}")
        offenders = []
        for path in root.rglob("*.py"):
            if ".git" in path.parts or "test_config" in path.name:
                continue
            if pattern.search(path.read_text(encoding="utf-8")):
                offenders.append(str(path))
        assert not offenders, f"hardcoded API key found in: {offenders}"

    def test_gitignore_covers_secrets_and_db(self):
        from pathlib import Path

        text = (Path(__file__).resolve().parent.parent / ".gitignore").read_text()
        assert ".env" in text
        assert "*.db" in text


class TestProviderRegistry:
    def test_offline_provider_needs_no_key(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        provider = get_provider("offline")
        assert provider.name == "curated-offline"
        assert provider.fetch_batch(["UPSC CSE"]).records

    def test_unknown_provider_raises(self):
        with pytest.raises(ProviderError, match="Unknown provider"):
            get_provider("perplexity")

    def test_offline_reports_unknown_exams_as_missing(self):
        response = get_provider("offline").fetch_batch(["Totally Fake Exam"])
        assert response.records == []
        assert response.meta["missing"] == ["Totally Fake Exam"]


class TestCli:
    def test_init_then_status(self, tmp_path, capsys):
        dbp = tmp_path / "cli.db"
        assert main(["--db", str(dbp), "init"]) == 0
        assert main(["--db", str(dbp), "status"]) == 0
        assert "Jobs: 12" in capsys.readouterr().out

    def test_init_twice_keeps_data(self, tmp_path, capsys):
        dbp = tmp_path / "twice.db"
        main(["--db", str(dbp), "init"])
        main(["--db", str(dbp), "scout", "--offline"])
        main(["--db", str(dbp), "init"])
        capsys.readouterr()
        main(["--db", str(dbp), "status", "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["coverage"]["job_specs"] > 0

    def test_offline_scout_and_verify(self, tmp_path, capsys):
        dbp = tmp_path / "scout.db"
        main(["--db", str(dbp), "init"])
        capsys.readouterr()
        assert main(["--db", str(dbp), "scout", "--offline"]) == 0
        assert main(["--db", str(dbp), "verify"]) == 0
        assert "All integrity checks passed" in capsys.readouterr().out

    def test_scout_without_key_exits_cleanly(self, tmp_path, monkeypatch, capsys):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        dbp = tmp_path / "nokey.db"
        main(["--db", str(dbp), "init"])
        capsys.readouterr()
        code = main(["--db", str(dbp), "scout"])
        assert code == 2
        assert "GEMINI_API_KEY" in capsys.readouterr().out

    def test_status_on_missing_db_is_graceful(self, tmp_path, capsys):
        code = main(["--db", str(tmp_path / "nope.db"), "status"])
        assert code == 1
        assert "not found" in capsys.readouterr().out.lower()

    def test_export_writes_json(self, tmp_path, capsys):
        dbp = tmp_path / "exp.db"
        out = tmp_path / "out.json"
        main(["--db", str(dbp), "init"])
        main(["--db", str(dbp), "scout", "--offline"])
        capsys.readouterr()
        assert main(["--db", str(dbp), "export", "-o", str(out)]) == 0
        payload = json.loads(out.read_text())
        assert len(payload) == 12
        assert payload[0]["specs"]["nationality"]

    def test_force_reset_clears(self, tmp_path, capsys):
        dbp = tmp_path / "reset.db"
        main(["--db", str(dbp), "init"])
        main(["--db", str(dbp), "scout", "--offline"])
        main(["--db", str(dbp), "init", "--force-reset", "--no-seed"])
        capsys.readouterr()
        main(["--db", str(dbp), "status", "--json"])
        assert json.loads(capsys.readouterr().out)["coverage"]["jobs"] == 0

    def test_no_command_prints_help(self, capsys):
        assert main([]) == 0
        assert "usage" in capsys.readouterr().out.lower()

    def test_dry_run_leaves_db_untouched(self, tmp_path, capsys):
        dbp = tmp_path / "dry.db"
        main(["--db", str(dbp), "init"])
        main(["--db", str(dbp), "scout", "--offline", "--dry-run"])
        capsys.readouterr()
        main(["--db", str(dbp), "status", "--json"])
        assert json.loads(capsys.readouterr().out)["coverage"]["job_specs"] == 0


class TestCuratedDataset:
    def test_every_record_carries_a_source(self):
        from gjter.providers.offline import OfflineProvider

        for record in OfflineProvider().records:
            assert record["source_url"].startswith("http"), record["exam_name"]
            assert record["official_website"].startswith("http"), record["exam_name"]

    def test_cutoffs_have_categories_and_scores(self):
        from gjter.providers.offline import OfflineProvider

        for record in OfflineProvider().records:
            for cutoff in record.get("cutoffs", []):
                assert cutoff["category"]
                assert cutoff["score"]

    def test_dataset_covers_every_seeded_exam(self):
        from gjter.providers.offline import OfflineProvider
        from gjter.seed import SEED_JOBS

        covered = {r["exam_name"] for r in OfflineProvider().records}
        needed = {job["exam_name"] for job in SEED_JOBS}
        assert needed <= covered, f"missing curated data for {needed - covered}"
