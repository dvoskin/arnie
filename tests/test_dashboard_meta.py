"""The user dashboard page carries a favicon and a personalized tab title, but NO Open
Graph / Twitter preview image — shared dashboard links render as a plain link + favicon,
no preview card."""
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


def test_dashboard_head_has_favicon():
    html = _dashboard_html("tok123")
    assert 'rel="icon"' in html
    # served by the app itself via a relative path (follows whatever host serves it)
    assert 'href="/favicon.png"' in html


def test_dashboard_social_title_present_no_image():
    html = _dashboard_html("tok123", name="Danny")
    # a generic text title for the preview...
    assert 'property="og:title"' in html
    assert 'content="Dashboard ⏐ ArnieOS"' in html
    assert 'name="twitter:title"' in html
    # ...but NO preview image
    assert "og:image" not in html and "twitter:image" not in html


def test_social_title_is_generic_no_name_leak():
    # The explicit generic og:title must NOT carry the per-user name (it would otherwise
    # leak into cacheable, forwardable link previews).
    html = _dashboard_html("tok123", name="Danny")
    head = html[:html.find("</head>")]
    title_block = head[head.find("og:title"):]
    assert "Danny" not in title_block
