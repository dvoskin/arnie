"""Safe-rollout allowlist for proactive check-ins — only listed users get messages
when PROACTIVE_ALLOWLIST is set; everyone when it's not."""
import pytest
import scheduler.proactive_scheduler as S


def test_no_allowlist_allows_everyone(monkeypatch):
    monkeypatch.delenv("PROACTIVE_ALLOWLIST", raising=False)
    assert S._allowlist_allows("im:+15551234567")
    assert S._allowlist_allows(42, "anything", None)


def test_allowlist_restricts_to_members(monkeypatch):
    monkeypatch.setenv("PROACTIVE_ALLOWLIST", "im:+15551234567, 42")
    # matches if ANY identifier is on the list (id / telegram_id / send_id)
    assert S._allowlist_allows("im:+15551234567")
    assert S._allowlist_allows(99, "telegram", 42)   # 42 (int) matches "42"
    assert S._allowlist_allows(42)
    # not listed → blocked
    assert not S._allowlist_allows("im:+19998887777")
    assert not S._allowlist_allows(7, "nope", None)


def test_allowlist_parsing_trims_and_ignores_blanks(monkeypatch):
    monkeypatch.setenv("PROACTIVE_ALLOWLIST", " a , ,b ,")
    assert S._proactive_allowlist() == {"a", "b"}


@pytest.mark.asyncio
async def test_send_backstop_gates_on_allowlist(monkeypatch):
    """_send() must drop non-allowlisted users even if the loop missed them."""
    monkeypatch.setenv("PROACTIVE_MESSAGING_ENABLED", "true")
    monkeypatch.setenv("PROACTIVE_ALLOWLIST", "im:+1111")
    import core.platform as P
    sent = []

    class _FakeAdapter:
        def __init__(self, *a, **k):
            pass
        async def send(self, resp):
            sent.append(resp)

    monkeypatch.setattr(P, "IMessageAdapter", _FakeAdapter)

    await S._send("im:+9999", "hi")          # not on the allowlist
    assert sent == [], "non-allowlisted send should be dropped"

    await S._send("im:+1111", "hi")          # on the allowlist
    assert len(sent) == 1, "allowlisted send should go through"
