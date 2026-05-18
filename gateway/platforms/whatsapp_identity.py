"""Canonical identity matching for WhatsApp messages.

WhatsApp identifies users via several interchangeable formats:

* **JID** — classic `digits@s.whatsapp.net` (and `@hosted` variants).
* **LID** — `digits@lid` / `@hosted.lid`, opaque Linked-Identity-Device IDs.
* **E.164** — international phone number, e.g. `+34652029134`.

A single user can appear under any of those formats in a single delivery —
the reply quote may carry the LID while the bot remembers itself by JID.
Comparing raw strings misses these cases, so we resolve every identity to
the same `{jid, lid, e164}` triple and check whether the sets overlap.

This Python module mirrors `extensions/whatsapp/src/identity.ts` from
OpenClaw — same shape, same semantics, minus the LID→E.164 reverse-lookup
(which requires Baileys auth state we don't have access to in-process).
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

__all__ = [
    "resolve_comparable_identity",
    "get_comparable_identity_values",
    "identities_overlap",
    "get_sender_identity",
    "get_self_identity",
    "get_reply_context",
    "normalize_device_scoped_jid",
    "normalize_e164",
    "jid_to_e164",
]


_WHATSAPP_LID_RE = re.compile(r"@(lid|hosted\.lid)$", re.IGNORECASE)
_DEVICE_COLON_RE = re.compile(r":\d+")
_DEVICE_AT_RE = re.compile(r"@\d+@")
_JID_E164_RE = re.compile(r"^(\d+)@(s\.whatsapp\.net|hosted)$", re.IGNORECASE)


def normalize_device_scoped_jid(jid: Optional[str]) -> Optional[str]:
    """Strip device suffixes (`:5` and legacy `@2@`) from a JID-like string."""
    if not jid:
        return None
    cleaned = _DEVICE_COLON_RE.sub("", str(jid))
    cleaned = _DEVICE_AT_RE.sub("@", cleaned)
    cleaned = cleaned.strip()
    return cleaned or None


def _is_lid(jid: Optional[str]) -> bool:
    return bool(jid and _WHATSAPP_LID_RE.search(jid))


def normalize_e164(value: Optional[str]) -> Optional[str]:
    """Strip formatting characters and ensure a leading `+`."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    # Drop optional scheme prefix like "tel:" or "whatsapp:".
    text = re.sub(r"^[a-z][a-z0-9-]*:", "", text, flags=re.IGNORECASE)
    digits = re.sub(r"[^\d+]", "", text)
    if not digits or digits == "+":
        return None
    if digits.startswith("+"):
        return "+" + digits[1:]
    return "+" + digits


def jid_to_e164(jid: Optional[str]) -> Optional[str]:
    """Convert a classic `@s.whatsapp.net` / `@hosted` JID to E.164.

    LIDs cannot be reversed without the local Baileys mapping table, so they
    return ``None`` here — callers that need that lookup must supply an
    explicit ``e164`` on the identity dict.
    """
    if not jid:
        return None
    cleaned = normalize_device_scoped_jid(jid)
    if not cleaned:
        return None
    match = _JID_E164_RE.match(cleaned)
    if not match:
        return None
    return "+" + match.group(1)


def resolve_comparable_identity(
    identity: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Return an identity dict with canonical ``jid`` / ``lid`` / ``e164``.

    Non-identity keys on the input (``name``, ``label``, …) pass through
    unchanged so callers can keep using the result as a display record.
    """
    if not identity:
        return {"jid": None, "lid": None, "e164": None}

    raw_jid = normalize_device_scoped_jid(identity.get("jid"))
    raw_lid = normalize_device_scoped_jid(identity.get("lid"))

    # A "@lid"-shaped value in the jid slot is actually a LID — reclassify.
    lid = raw_lid or (raw_jid if _is_lid(raw_jid) else None)
    jid = raw_jid if raw_jid and not _is_lid(raw_jid) else None

    raw_e164 = identity.get("e164")
    if raw_e164 is not None and str(raw_e164).strip():
        e164 = normalize_e164(raw_e164)
    else:
        e164 = jid_to_e164(jid) if jid else None

    resolved: Dict[str, Any] = {**identity, "jid": jid, "lid": lid, "e164": e164}
    return resolved


def get_comparable_identity_values(
    identity: Optional[Dict[str, Any]],
) -> List[str]:
    """Return all non-empty canonical identifiers for an identity."""
    resolved = resolve_comparable_identity(identity)
    return [v for v in (resolved["e164"], resolved["jid"], resolved["lid"]) if v]


def identities_overlap(
    left: Optional[Dict[str, Any]],
    right: Optional[Dict[str, Any]],
) -> bool:
    """True when the two identities share any canonical identifier."""
    left_values = set(get_comparable_identity_values(left))
    if not left_values:
        return False
    return any(v in left_values for v in get_comparable_identity_values(right))


# ---------------------------------------------------------------------------
# Bridge-message helpers
# ---------------------------------------------------------------------------


def get_sender_identity(msg: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve the sender identity from a bridge message dict."""
    explicit = msg.get("sender")
    if explicit:
        return resolve_comparable_identity(explicit)
    return resolve_comparable_identity(
        {
            "jid": msg.get("senderJid") or msg.get("senderId"),
            "e164": msg.get("senderE164"),
            "name": msg.get("senderName"),
        },
    )


def _identity_from_jid_list(values: Iterable[str]) -> Dict[str, Any]:
    """Split a list of mixed JID/LID strings into a single identity dict."""
    jid: Optional[str] = None
    lid: Optional[str] = None
    for raw in values:
        cleaned = normalize_device_scoped_jid(raw)
        if not cleaned:
            continue
        if _is_lid(cleaned):
            if lid is None:
                lid = cleaned
        else:
            if jid is None:
                jid = cleaned
    return resolve_comparable_identity({"jid": jid, "lid": lid})


def get_self_identity(msg: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve the bot's own identity from a bridge message dict.

    Accepts either an explicit ``self`` dict, individual ``selfJid`` /
    ``selfLid`` / ``selfE164`` fields, or a ``botIds`` list of mixed
    JID / LID strings (as emitted by the Node bridge).
    """
    explicit = msg.get("self")
    if explicit:
        return resolve_comparable_identity(explicit)

    if any(k in msg for k in ("selfJid", "selfLid", "selfE164")):
        return resolve_comparable_identity(
            {
                "jid": msg.get("selfJid"),
                "lid": msg.get("selfLid"),
                "e164": msg.get("selfE164"),
            },
        )

    bot_ids = msg.get("botIds") or []
    if bot_ids:
        return _identity_from_jid_list(bot_ids)

    return resolve_comparable_identity(None)


def get_reply_context(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the quoted message context (with resolved sender) or None.

    Two input shapes are supported:

    * An explicit ``replyTo`` dict carrying ``id`` / ``body`` / ``sender``.
    * The flatter Baileys bridge form, where only ``quotedParticipant``
      (and optionally ``quotedMessageId`` / ``quotedBody``) is supplied.
    """
    reply_to = msg.get("replyTo")
    if reply_to:
        return {
            **reply_to,
            "sender": resolve_comparable_identity(reply_to.get("sender")),
        }

    quoted_participant = msg.get("quotedParticipant")
    if not quoted_participant:
        return None

    return {
        "id": msg.get("quotedMessageId"),
        "body": msg.get("quotedBody", ""),
        "sender": resolve_comparable_identity({"jid": quoted_participant}),
    }
