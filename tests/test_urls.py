"""Dashboard URL base resolution — DASHBOARD_BASE_URL wins, else the app host, else local."""
import importlib


def _fresh():
    import core.urls as u
    return importlib.reload(u)


def test_dashboard_base_prefers_explicit_env(monkeypatch):
    monkeypatch.setenv("DASHBOARD_BASE_URL", "https://app.tryarnie.com")
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://arnie.onrender.com")
    u = _fresh()
    assert u.dashboard_base_url() == "https://app.tryarnie.com"
    assert u.dashboard_url("abc") == "https://app.tryarnie.com/dashboard/abc"


def test_falls_back_to_render_host_when_no_dashboard_base(monkeypatch):
    monkeypatch.delenv("DASHBOARD_BASE_URL", raising=False)
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://arnie.onrender.com")
    u = _fresh()
    # Shipping the code is a no-op until DASHBOARD_BASE_URL is set — still the app host.
    assert u.dashboard_url("xyz") == "https://arnie.onrender.com/dashboard/xyz"


def test_local_default_when_nothing_set(monkeypatch):
    monkeypatch.delenv("DASHBOARD_BASE_URL", raising=False)
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    u = _fresh()
    assert u.dashboard_url("t") == "http://localhost:10000/dashboard/t"


def test_trailing_slash_trimmed(monkeypatch):
    monkeypatch.setenv("DASHBOARD_BASE_URL", "https://app.tryarnie.com/")
    u = _fresh()
    assert u.dashboard_url("t") == "https://app.tryarnie.com/dashboard/t"
