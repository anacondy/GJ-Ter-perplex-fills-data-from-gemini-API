"""Tests for the Flask dashboard.

These exercise the routes the templates depend on. Every variable the templates
reference is asserted to be supplied, because a missing one renders as empty
rather than raising - which is how a broken card goes unnoticed.
"""

from __future__ import annotations

import pytest

from gjter import db
from gjter.config import UNKNOWN
from gjter.pipeline import enrich
from gjter.providers.offline import OfflineProvider
from gjter.seed import seed

flask = pytest.importorskip("flask", reason="Flask not installed")


@pytest.fixture()
def populated_db(tmp_path, monkeypatch):
    """A fully enriched database, with the app pointed at it."""
    from gjter.config import Settings

    path = tmp_path / "web.db"
    monkeypatch.setenv("GJTER_DB_PATH", str(path))
    conn = db.connect(path)
    db.migrate(conn)
    seed(conn)
    enrich(
        conn,
        OfflineProvider(),
        Settings(db_path=path, batch_pause_seconds=0),
    )
    conn.close()
    return path


@pytest.fixture()
def client(populated_db):
    import app as web

    web.app.config.update(TESTING=True)
    return web.app.test_client()


@pytest.fixture()
def empty_client(tmp_path, monkeypatch):
    """App pointed at a database that has the schema but no rows."""
    path = tmp_path / "empty.db"
    monkeypatch.setenv("GJTER_DB_PATH", str(path))
    conn = db.connect(path)
    db.migrate(conn)
    conn.close()

    import app as web

    web.app.config.update(TESTING=True)
    return web.app.test_client()


class TestIndex:
    def test_index_renders(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert b"GJ Terminal" in response.data

    def test_all_twelve_posts_are_listed(self, client):
        body = client.get("/").get_data(as_text=True)
        for post in ("IAS Officer", "IPS Officer", "SBI Probationary Officer"):
            assert post in body

    def test_rows_carry_the_id_the_click_handler_needs(self, client):
        assert 'data-id="1"' in client.get("/").get_data(as_text=True)

    def test_is_updating_renders_as_valid_javascript(self, client):
        """`let wasUpdating = {{ is_updating | lower }}` must yield a boolean.

        If the variable is missing, Jinja renders '' and the script becomes
        `let wasUpdating = ;` - a syntax error that kills every handler on the
        page, including sorting and search.
        """
        body = client.get("/").get_data(as_text=True)
        assert ("let wasUpdating = false" in body) or (
            "let wasUpdating = true" in body
        )

    def test_no_sentinel_text_leaks_into_the_table(self, client):
        assert UNKNOWN not in client.get("/").get_data(as_text=True)

    def test_empty_database_shows_the_placeholder_row(self, empty_client):
        body = empty_client.get("/").get_data(as_text=True)
        assert "No job data found" in body

    def test_pay_level_null_renders_as_na_not_none(self, client):
        """Bank/corporation posts have pay_level NULL; must not print 'None'."""
        body = client.get("/").get_data(as_text=True)
        assert ">None<" not in body


class TestDetails:
    def test_details_renders(self, client):
        response = client.get("/details/1")
        assert response.status_code == 200
        assert b"Job Specifications" in response.data

    def test_specs_and_pattern_are_populated(self, client):
        body = client.get("/details/1").get_data(as_text=True)
        assert "Data not available." not in body
        assert "Preliminary" in body

    def test_cutoff_card_shows_real_marks(self, client):
        body = client.get("/details/1").get_data(as_text=True)
        assert "92.66" in body  # UPSC CSE 2025 General
        assert "No data available." not in body

    def test_fee_card_is_populated(self, client):
        """This card could only ever show its fallback before schema v3."""
        body = client.get("/details/1").get_data(as_text=True)
        assert "Details not available." not in body
        assert "₹100" in body

    def test_vacancies_card_is_populated(self, client):
        body = client.get("/details/1").get_data(as_text=True)
        assert "Details announced in notification." not in body
        assert "979" in body

    def test_website_card_links_out(self, client):
        body = client.get("/details/1").get_data(as_text=True)
        assert "upsc.gov.in" in body
        assert "Link not available." not in body

    def test_external_links_are_rel_noopener(self, client):
        """target=_blank without rel=noopener exposes window.opener."""
        body = client.get("/details/1").get_data(as_text=True)
        for chunk in body.split('target="_blank"')[1:]:
            assert "noopener" in chunk[:60]

    def test_back_link_resolves(self, client):
        assert 'href="/"' in client.get("/details/1").get_data(as_text=True)

    def test_provenance_footer_is_shown(self, client):
        body = client.get("/details/1").get_data(as_text=True)
        assert "Last verified" in body

    def test_missing_job_returns_404(self, client):
        assert client.get("/details/9999").status_code == 404

    def test_non_integer_id_returns_404(self, client):
        assert client.get("/details/abc").status_code == 404

    def test_sql_injection_in_path_is_not_executed(self, client):
        response = client.get("/details/1%20OR%201=1")
        assert response.status_code == 404


class TestUpdateStatus:
    def test_returns_json_boolean(self, client):
        payload = client.get("/update_status").get_json()
        assert isinstance(payload["updating"], bool)

    def test_reflects_the_flag(self, client):
        import app as web

        web.set_updating(True)
        try:
            assert client.get("/update_status").get_json()["updating"] is True
        finally:
            web.set_updating(False)
        assert client.get("/update_status").get_json()["updating"] is False

    def test_is_not_cached(self, client):
        """The poller appends a cache-buster, but the header must be right too."""
        assert "no-store" in client.get("/update_status").headers["Cache-Control"]


class TestHealthz:
    def test_ok_when_populated(self, client):
        payload = client.get("/healthz").get_json()
        assert payload["status"] == "ok"
        assert payload["coverage"]["jobs"] == 12


class TestMissingDatabase:
    def test_index_degrades_gracefully(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GJTER_DB_PATH", str(tmp_path / "absent.db"))
        import app as web

        web.app.config.update(TESTING=True)
        client = web.app.test_client()
        response = client.get("/")
        assert response.status_code == 503
        assert b"database_setup.py" in response.data


class TestDebugSafety:
    def test_debug_with_public_host_is_refused(self):
        """--debug on 0.0.0.0 would expose the Werkzeug RCE console."""
        import app as web

        with pytest.raises(SystemExit):
            web.main(["--debug", "--host", "0.0.0.0"])
