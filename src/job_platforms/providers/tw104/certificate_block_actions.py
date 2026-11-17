"""104 empty CERTIFICATE section initialization and narrow text-only clearing.

Frontend 779c CREATE delegates to UPDATE, which uses PUT with
certificates[] and others text. The whole-block CLEAR uses a distinct
DELETE with string-valued certificates="" and others="".

These actions affect the resume's certificate block only. They DO NOT
create, delete, connect or disconnect account-level certifications.
Clearing is deliberately supported only when no certificate IDs are
linked, preventing accidental loss of associations.
Initial PUT succeeded in a private real 104 test on 2026-11-17;
the first live read-back showed certifications[], not certificates[].
Clear and round-trip restoration must be evaluated separately.
"""
from __future__ import annotations

from job_platforms.core.errors import UnsupportedWrite


def _form(document: dict) -> dict:
    try:
        form = document["certificate"]["formData"]
    except (TypeError, KeyError) as exc:
        raise UnsupportedWrite("104 CERTIFICATE formData missing") from exc
    if not isinstance(form, dict):
        raise UnsupportedWrite("104 CERTIFICATE formData invalid")
    return form


def _certificates(form: dict) -> dict:
    if not isinstance(form, dict) or not form:
        raise UnsupportedWrite("104 CERTIFICATE populated form required")
    block = form.get("certificate")
    if (
        not isinstance(block, dict)
        or "others" not in block
        or not isinstance(block["others"], str)
        or not ({"certificates", "certifications"} & set(block))
        or set(block) - {"others", "certificates", "certifications"}
    ):
        raise UnsupportedWrite("104 CERTIFICATE native structure changed")
    # 2026-11-17 *live* GET after a successful initial PUT supplied
    # only {certifications:[], others:"..."} -- no certificates key.
    # The editor's initial view model adds certificates:[] internally.
    for key in ("certificates", "certifications"):
        if key in block and (
            not isinstance(block[key], list)
            or any(not isinstance(x, dict) for x in block[key])
        ):
            raise UnsupportedWrite("104 CERTIFICATE unknown certification link")
    return block


def certificate_block_body(
    document: dict, action: str, *, others: str | None = None,
) -> dict:
    """Safe first-create or no-linked-certificate text-only clear."""
    form = _form(document)
    if action == "initialize":
        if form:
            raise UnsupportedWrite("104 CERTIFICATE already initialized")
        if not isinstance(others, str) or not others.strip() or len(others) > 200:
            raise UnsupportedWrite("104 CERTIFICATE initial text must be 1-200 chars")
        # Frontend 779c.CREATE is an alias to UPDATE (native PUT).
        return {"blockValueList": {"certificate": {
            "certificates": [], "others": others,
        }}}
    if action == "clear":
        if others is not None:
            raise UnsupportedWrite("104 CERTIFICATE clear takes no text")
        block = _certificates(form)
        if block.get("certificates") or block.get("certifications"):
            raise UnsupportedWrite(
                "104 CERTIFICATE with linked items cannot be safely cleared"
            )
        if not block["others"]:
            raise UnsupportedWrite("104 CERTIFICATE text already empty")
        # Distinct 779c.CLEAR DELETE shape: strings, not lists.
        return {"blockValueList": {"certificate": {
            "certificates": "", "others": "",
        }}}
    raise UnsupportedWrite("104 CERTIFICATE action must be initialize or clear")


def verify_certificate_block(
    before: dict, after: dict, action: str, *, body: dict,
) -> bool:
    old_form, new_form = _form(before), _form(after)
    if action == "initialize":
        if old_form or not new_form:
            return False
        try:
            block = _certificates(new_form)
        except UnsupportedWrite:
            return False
        return (
            not block.get("certificates")
            and not block.get("certifications")
            and block["others"] == body["blockValueList"]["certificate"]["others"]
        )
    if action == "clear":
        if not old_form:
            return False
        if not new_form:
            return True
        try:
            block = _certificates(new_form)
        except UnsupportedWrite:
            return False
        return (
            not block.get("certificates")
            and not block.get("certifications")
            and block["others"] == ""
        )
    return False
