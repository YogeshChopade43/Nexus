"""Machine-level settings: the OS keychain, trusted networks and serving the built frontend."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.core import config

LOCAL = ("127.0.0.1", 50000)


def test_secret_key_in_keychain(tmp_path, monkeypatch):
    vault: dict[str, str] = {}
    monkeypatch.setattr(config, "_keychain", lambda action, value="": vault.update(key=value) if action == "set" else vault.get("key"))
    (tmp_path / ".nexus_secret_key").write_text("from-file")
    environ = {"NEXUS_KEYCHAIN": "true"}
    config.ensure_secret_key(str(tmp_path / "nexus.db"), environ)
    assert environ["NEXUS_SECRET_KEY"] == "from-file" and vault["key"] == "from-file"
    assert not (tmp_path / ".nexus_secret_key").exists()  # moved, not copied
    environ = {"NEXUS_KEYCHAIN": "true"}
    config.ensure_secret_key(str(tmp_path / "nexus.db"), environ)
    assert environ["NEXUS_SECRET_KEY"] == "from-file"


def test_trusted_networks_count_as_this_machine(monkeypatch):
    from app.api.middleware import is_local

    class Req:
        def __init__(self, host):
            self.client = type("C", (), {"host": host})()

    assert is_local(Req("127.0.0.1")) and not is_local(Req("172.18.0.1"))
    monkeypatch.setenv("NEXUS_TRUSTED_NETWORKS", "172.16.0.0/12, 10.1.2.3")
    assert is_local(Req("172.18.0.1")) and is_local(Req("10.1.2.3")) and not is_local(Req("8.8.8.8"))
    assert not is_local(Req("testclient"))


def test_serves_built_frontend(tmp_path, monkeypatch):
    from app.main import create_app

    (tmp_path / "index.html").write_text("<html>nexus</html>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path.parent / "secret.txt").write_text("nope")
    monkeypatch.setenv("NEXUS_STATIC_DIR", str(tmp_path))
    web = TestClient(create_app(), client=LOCAL)
    assert web.get("/").text == "<html>nexus</html>"
    assert web.get("/workflows").text == "<html>nexus</html>"  # client-side route
    assert web.get("/assets/app.js").text == "console.log(1)"
    assert "nope" not in web.get("/..%2Fsecret.txt").text
    missing = web.get("/api/does-not-exist")
    assert missing.status_code in (401, 404) and "<html>" not in missing.text  # never the app's page for an API path
    assert web.get("/health").json()["status"] == "ok"
