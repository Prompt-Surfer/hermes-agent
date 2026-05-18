"""Integration tests for WhatsAppAdapter's reply-to-bot detection.

These tests exercise the adapter-level helpers (``_message_is_reply_to_bot``,
``_message_mentions_bot``, ``_clean_bot_mention_text``) directly without
spinning up the Node bridge — bridge messages are passed in as plain dicts
matching the JSON shape that ``_poll_messages`` would normally produce.
"""

from gateway.platforms.whatsapp import WhatsAppAdapter


def _make_adapter() -> WhatsAppAdapter:
    """Construct a WhatsAppAdapter without running __init__ — none of the
    helper methods under test touch ``self.config`` or the bridge.
    """
    adapter = WhatsAppAdapter.__new__(WhatsAppAdapter)
    adapter._mention_patterns = []
    return adapter


# ---------------------------------------------------------------------------
# _message_is_reply_to_bot
# ---------------------------------------------------------------------------


def test_reply_quoted_as_lid_matches_bot_jid():
    """LID-form quote matches the bot's JID via the shared E.164 derivation."""
    adapter = _make_adapter()
    data = {
        "quotedParticipant": "67427329167522@lid",
        "botIds": [
            "34652029134@s.whatsapp.net",
            "67427329167522@lid",
        ],
    }
    assert adapter._message_is_reply_to_bot(data) is True


def test_reply_quoted_as_jid_matches_bot_jid():
    adapter = _make_adapter()
    data = {
        "quotedParticipant": "34652029134@s.whatsapp.net",
        "botIds": ["34652029134@s.whatsapp.net"],
    }
    assert adapter._message_is_reply_to_bot(data) is True


def test_reply_quoted_with_device_suffix_matches_bot():
    adapter = _make_adapter()
    data = {
        "quotedParticipant": "34652029134:9@s.whatsapp.net",
        "botIds": ["34652029134@s.whatsapp.net"],
    }
    assert adapter._message_is_reply_to_bot(data) is True


def test_reply_quoted_with_legacy_at_n_at_suffix_matches_bot():
    adapter = _make_adapter()
    data = {
        "quotedParticipant": "41868062658802@2@lid",
        "botIds": ["41868062658802@lid"],
    }
    assert adapter._message_is_reply_to_bot(data) is True


def test_reply_to_someone_else_does_not_match_bot():
    adapter = _make_adapter()
    data = {
        "quotedParticipant": "11111@s.whatsapp.net",
        "botIds": ["34652029134@s.whatsapp.net", "67427329167522@lid"],
    }
    assert adapter._message_is_reply_to_bot(data) is False


def test_no_quoted_participant_is_not_a_reply():
    adapter = _make_adapter()
    data = {"botIds": ["34652029134@s.whatsapp.net"]}
    assert adapter._message_is_reply_to_bot(data) is False


def test_no_bot_ids_is_not_a_reply_to_bot():
    adapter = _make_adapter()
    data = {"quotedParticipant": "34652029134@s.whatsapp.net", "botIds": []}
    assert adapter._message_is_reply_to_bot(data) is False


# ---------------------------------------------------------------------------
# _message_mentions_bot
# ---------------------------------------------------------------------------


def test_mention_via_mentioned_ids_lid_form():
    adapter = _make_adapter()
    data = {
        "mentionedIds": ["67427329167522@lid"],
        "botIds": [
            "34652029134@s.whatsapp.net",
            "67427329167522@lid",
        ],
        "body": "hey",
    }
    assert adapter._message_mentions_bot(data) is True


def test_mention_via_body_bare_number():
    adapter = _make_adapter()
    data = {
        "mentionedIds": [],
        "botIds": ["34652029134@s.whatsapp.net"],
        "body": "@34652029134 what do you think?",
    }
    assert adapter._message_mentions_bot(data) is True


def test_no_mention_no_match():
    adapter = _make_adapter()
    data = {
        "mentionedIds": ["99999@s.whatsapp.net"],
        "botIds": ["34652029134@s.whatsapp.net"],
        "body": "talking to someone else",
    }
    assert adapter._message_mentions_bot(data) is False


# ---------------------------------------------------------------------------
# _clean_bot_mention_text
# ---------------------------------------------------------------------------


def test_clean_bot_mention_text_strips_at_number_prefix():
    adapter = _make_adapter()
    data = {"botIds": ["34652029134@s.whatsapp.net"]}
    cleaned = adapter._clean_bot_mention_text(
        "@34652029134 what's up?", data,
    )
    assert cleaned == "what's up?"


def test_clean_bot_mention_text_returns_original_when_nothing_to_strip():
    adapter = _make_adapter()
    data = {"botIds": ["34652029134@s.whatsapp.net"]}
    cleaned = adapter._clean_bot_mention_text("just a normal message", data)
    assert cleaned == "just a normal message"
