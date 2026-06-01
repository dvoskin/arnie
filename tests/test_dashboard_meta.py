"""The user dashboard page must carry a favicon + Open Graph tags so shared dashboard
links render a branded preview (in iMessage/Telegram/social) and a tab icon."""
from api.templates import _dashboard_html


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
