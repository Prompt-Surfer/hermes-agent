"""Tests for WhatsApp canonical identity matching (jid/lid/e164).

Mirrors the OpenClaw identity module — multiple identifier formats are
resolved to a comparable triple so that JID vs LID vs E.164 mismatches do
not break reply-to-bot and mention detection.
"""

import pytest

from gateway.platforms.whatsapp_identity import (
    get_comparable_identity_values,
    get_reply_context,
    get_self_identity,
    get_sender_identity,
    identities_overlap,
    resolve_comparable_identity,
)


# ---------------------------------------------------------------------------
# resolve_comparable_identity
# ---------------------------------------------------------------------------

class TestResolveComparableIdentity:
    def test_classic_jid_yields_jid_and_e164(self):
        result = resolve_comparable_identity({"jid": "34652029134@s.whatsapp.net"})
        assert result["jid"] == "34652029134@s.whatsapp.net"
        assert result["lid"] is None
        assert result["e164"] == "+34652029134"

    def test_lid_in_jid_field_is_reclassified_as_lid(self):
        # WhatsApp sometimes delivers a LID where a JID is expected.
        result = resolve_comparable_identity({"jid": "67427329167522@lid"})
        assert result["jid"] is None
        assert result["lid"] == "67427329167522@lid"
        # Cannot derive E.164 from an unresolved LID without the lookup table.
        assert result["e164"] is None

    def test_hosted_lid_is_classified_as_lid(self):
        result = resolve_comparable_identity({"jid": "999@hosted.lid"})
        assert result["jid"] is None
        assert result["lid"] == "999@hosted.lid"

    def test_explicit_lid_field_is_kept(self):
        result = resolve_comparable_identity(
            {"jid": "34652029134@s.whatsapp.net", "lid": "67427329167522@lid"},
        )
        assert result["jid"] == "34652029134@s.whatsapp.net"
        assert result["lid"] == "67427329167522@lid"
        assert result["e164"] == "+34652029134"

    def test_device_scoped_suffix_is_stripped(self):
        result = resolve_comparable_identity({"jid": "34652029134:5@s.whatsapp.net"})
        assert result["jid"] == "34652029134@s.whatsapp.net"
        assert result["e164"] == "+34652029134"

    def test_legacy_at_n_at_marker_is_stripped(self):
        # Older Baileys/Hermes data used the "@2@" form for multi-device.
        result = resolve_comparable_identity({"jid": "41868062658802@2@lid"})
        assert result["lid"] == "41868062658802@lid"
        assert result["jid"] is None

    def test_explicit_e164_is_normalised(self):
        result = resolve_comparable_identity({"e164": "+44 (20) 7946 0958"})
        assert result["e164"] == "+442079460958"

    def test_e164_without_plus_is_prefixed(self):
        result = resolve_comparable_identity({"e164": "442079460958"})
        assert result["e164"] == "+442079460958"

    def test_explicit_e164_takes_precedence_over_derived(self):
        # If the caller already knows the canonical E.164, we trust it.
        result = resolve_comparable_identity(
            {"jid": "34652029134@s.whatsapp.net", "e164": "+34999000111"},
        )
        assert result["e164"] == "+34999000111"

    def test_none_input_returns_empty_identity(self):
        result = resolve_comparable_identity(None)
        assert result == {"jid": None, "lid": None, "e164": None}

    def test_empty_dict_returns_empty_identity(self):
        result = resolve_comparable_identity({})
        assert result["jid"] is None
        assert result["lid"] is None
        assert result["e164"] is None

    def test_preserves_label_and_name_fields(self):
        result = resolve_comparable_identity(
            {"jid": "123@s.whatsapp.net", "name": "Alice", "label": "Mom"},
        )
        assert result["name"] == "Alice"
        assert result["label"] == "Mom"


# ---------------------------------------------------------------------------
# get_comparable_identity_values
# ---------------------------------------------------------------------------

class TestGetComparableIdentityValues:
    def test_returns_all_non_empty_values(self):
        values = get_comparable_identity_values(
            {"jid": "34652029134@s.whatsapp.net", "lid": "67427329167522@lid"},
        )
        # Order is not part of the contract; treat as a set.
        assert set(values) == {
            "34652029134@s.whatsapp.net",
            "67427329167522@lid",
            "+34652029134",
        }

    def test_filters_out_empties(self):
        values = get_comparable_identity_values({"jid": "999@lid"})
        # Only the LID survives — no JID and no derivable E.164.
        assert values == ["999@lid"]

    def test_none_input_returns_empty_list(self):
        assert get_comparable_identity_values(None) == []

    def test_empty_dict_returns_empty_list(self):
        assert get_comparable_identity_values({}) == []


# ---------------------------------------------------------------------------
# identities_overlap
# ---------------------------------------------------------------------------

class TestIdentitiesOverlap:
    def test_same_jid_overlaps(self):
        left = {"jid": "34652029134@s.whatsapp.net"}
        right = {"jid": "34652029134@s.whatsapp.net"}
        assert identities_overlap(left, right) is True

    def test_same_lid_overlaps(self):
        left = {"jid": "67427329167522@lid"}
        right = {"lid": "67427329167522@lid"}
        assert identities_overlap(left, right) is True

    def test_jid_and_lid_cross_match_via_e164(self):
        # Bot exposes both jid + lid; reply quotes only the lid form.
        left = {
            "jid": "34652029134@s.whatsapp.net",
            "lid": "67427329167522@lid",
        }
        right = {"jid": "67427329167522@lid"}
        assert identities_overlap(left, right) is True

    def test_device_scoped_variant_still_overlaps(self):
        left = {"jid": "34652029134@s.whatsapp.net"}
        right = {"jid": "34652029134:7@s.whatsapp.net"}
        assert identities_overlap(left, right) is True

    def test_disjoint_identities_do_not_overlap(self):
        left = {"jid": "11111@s.whatsapp.net"}
        right = {"jid": "22222@s.whatsapp.net"}
        assert identities_overlap(left, right) is False

    def test_empty_left_yields_no_overlap(self):
        assert identities_overlap(None, {"jid": "11111@s.whatsapp.net"}) is False

    def test_empty_right_yields_no_overlap(self):
        assert identities_overlap({"jid": "11111@s.whatsapp.net"}, None) is False

    def test_both_empty_yields_no_overlap(self):
        assert identities_overlap({}, {}) is False


# ---------------------------------------------------------------------------
# get_sender_identity
# ---------------------------------------------------------------------------

class TestGetSenderIdentity:
    def test_reads_sender_id_classic_form(self):
        identity = get_sender_identity(
            {"senderId": "34652029134@s.whatsapp.net", "senderName": "Alice"},
        )
        assert identity["jid"] == "34652029134@s.whatsapp.net"
        assert identity["e164"] == "+34652029134"
        assert identity["name"] == "Alice"

    def test_reads_sender_id_lid_form(self):
        identity = get_sender_identity({"senderId": "67427329167522@lid"})
        assert identity["lid"] == "67427329167522@lid"
        assert identity["jid"] is None

    def test_explicit_sender_dict_wins_over_sender_id(self):
        identity = get_sender_identity(
            {
                "sender": {"jid": "111@s.whatsapp.net", "e164": "+34111111"},
                "senderId": "999@s.whatsapp.net",
            },
        )
        assert identity["jid"] == "111@s.whatsapp.net"
        assert identity["e164"] == "+34111111"

    def test_missing_sender_returns_empty(self):
        identity = get_sender_identity({})
        assert identity["jid"] is None
        assert identity["lid"] is None
        assert identity["e164"] is None


# ---------------------------------------------------------------------------
# get_self_identity
# ---------------------------------------------------------------------------

class TestGetSelfIdentity:
    def test_bot_ids_list_with_jid_and_lid_merges(self):
        identity = get_self_identity(
            {
                "botIds": [
                    "34652029134@s.whatsapp.net",
                    "67427329167522@lid",
                ],
            },
        )
        assert identity["jid"] == "34652029134@s.whatsapp.net"
        assert identity["lid"] == "67427329167522@lid"
        assert identity["e164"] == "+34652029134"

    def test_bot_ids_with_only_lid(self):
        identity = get_self_identity({"botIds": ["67427329167522@lid"]})
        assert identity["lid"] == "67427329167522@lid"
        assert identity["jid"] is None

    def test_explicit_self_dict_wins(self):
        identity = get_self_identity(
            {
                "self": {"jid": "111@s.whatsapp.net", "lid": "222@lid"},
                "botIds": ["999@s.whatsapp.net"],
            },
        )
        assert identity["jid"] == "111@s.whatsapp.net"
        assert identity["lid"] == "222@lid"

    def test_missing_self_returns_empty(self):
        identity = get_self_identity({})
        assert identity["jid"] is None
        assert identity["lid"] is None

    def test_bot_ids_handles_device_scoped_entries(self):
        identity = get_self_identity(
            {"botIds": ["34652029134:5@s.whatsapp.net", "67427329167522:3@lid"]},
        )
        assert identity["jid"] == "34652029134@s.whatsapp.net"
        assert identity["lid"] == "67427329167522@lid"


# ---------------------------------------------------------------------------
# get_reply_context
# ---------------------------------------------------------------------------

class TestGetReplyContext:
    def test_quoted_participant_yields_sender_identity(self):
        ctx = get_reply_context({"quotedParticipant": "34652029134@s.whatsapp.net"})
        assert ctx is not None
        assert ctx["sender"]["jid"] == "34652029134@s.whatsapp.net"
        assert ctx["sender"]["e164"] == "+34652029134"

    def test_quoted_participant_lid_form(self):
        ctx = get_reply_context({"quotedParticipant": "67427329167522@lid"})
        assert ctx is not None
        assert ctx["sender"]["lid"] == "67427329167522@lid"

    def test_no_quoted_participant_returns_none(self):
        assert get_reply_context({}) is None

    def test_empty_quoted_participant_returns_none(self):
        assert get_reply_context({"quotedParticipant": ""}) is None

    def test_explicit_reply_to_dict_is_used(self):
        ctx = get_reply_context(
            {
                "replyTo": {
                    "id": "abc",
                    "body": "hello",
                    "sender": {"jid": "34111@s.whatsapp.net"},
                },
            },
        )
        assert ctx is not None
        assert ctx["id"] == "abc"
        assert ctx["body"] == "hello"
        assert ctx["sender"]["jid"] == "34111@s.whatsapp.net"


# ---------------------------------------------------------------------------
# End-to-end reply-to-bot scenario
# ---------------------------------------------------------------------------

class TestReplyToBotScenario:
    """Cross-format scenarios that the old @2@-stripping logic missed."""

    def test_reply_quoted_as_lid_matches_bot_jid(self):
        # The user replied to a bot message; WhatsApp recorded the quoted
        # participant in LID form, but the bot's primary identifier is its
        # @s.whatsapp.net JID. Plain string comparison would miss this.
        msg = {
            "quotedParticipant": "67427329167522@lid",
            "botIds": [
                "34652029134@s.whatsapp.net",
                "67427329167522@lid",
            ],
        }
        reply_ctx = get_reply_context(msg)
        bot = get_self_identity(msg)
        assert reply_ctx is not None
        assert identities_overlap(reply_ctx["sender"], bot) is True

    def test_reply_quoted_as_jid_with_device_suffix_matches_bot(self):
        msg = {
            "quotedParticipant": "34652029134:9@s.whatsapp.net",
            "botIds": ["34652029134@s.whatsapp.net"],
        }
        reply_ctx = get_reply_context(msg)
        bot = get_self_identity(msg)
        assert identities_overlap(reply_ctx["sender"], bot) is True

    def test_reply_to_someone_else_does_not_match_bot(self):
        msg = {
            "quotedParticipant": "11111@s.whatsapp.net",
            "botIds": ["34652029134@s.whatsapp.net", "67427329167522@lid"],
        }
        reply_ctx = get_reply_context(msg)
        bot = get_self_identity(msg)
        assert identities_overlap(reply_ctx["sender"], bot) is False
