"""The user dashboard page must carry a favicon + Open Graph tags so shared dashboard
links render a branded preview (in iMessage/Telegram/social) and a tab icon."""
from api.templates import _dashboard_html, _dashboard_title


def test_dashboard_title_is_personalized():
    assert _dashboard_title("Danny") == "ArnieOS ⏐ Danny's Dashboard"
    html = _dashboard_html("tok", name="Danny")
    assert "<title>ArnieOS ⏐ Danny's Dashboard</title>" in html


def test_dashboard_title_falls_back_without_name():
    assert _dashboard_title("") == "ArnieOS ⏐ Your Dashboard"
    assert _dashboard_title(None) == "ArnieOS ⏐ Your Dashboard"


def test_dashboard_title_escapes_user_name():
    out = _dashboard_title("<b>x")
    assert "<b>" not in out and "&lt;b&gt;" in out


def test_personalized_name_not_in_social_preview():
    # The name personalizes the browser tab title only — it must NOT leak into the OG
    # preview (which is generic + cacheable + seen by others).
    html = _dashboard_html("tok", name="Danny")
    og_block = html[html.find("og:type"):html.find("</head>")]
    assert "Danny" not in og_block


def test_dashboard_head_has_favicon():
    html = _dashboard_html("tok123")
    assert 'rel="icon"' in html
    # served by the app itself via a relative path (follows whatever host serves it)
    assert 'href="/favicon.png"' in html


def test_dashboard_head_has_open_graph_image():
    html = _dashboard_html("tok123")
    assert 'property="og:image"' in html
    assert "tryarnie.com/og-image.png" in html
    assert 'property="og:title"' in html
    assert 'property="og:description"' in html
    # twitter card too, so X/iMessage render the large image
    assert 'name="twitter:card"' in html
    assert "summary_large_image" in html


def test_dashboard_preview_leaks_no_personal_data():
    # The token is the only per-user input; it must NOT appear in the shareable preview
    # meta (titles/descriptions), which can be cached and seen by others.
    html = _dashboard_html("SECRET_TOKEN_123")
    og_block = html[html.find("og:type"):html.find("</head>")]
    assert "SECRET_TOKEN_123" not in og_block
