"""104 BIO first creation and whole-block clear, distinct from verified PUT.

Public frontend module 8d88 uses:
  POST   blockValueList.bio.bio={chi,eng}  (editor HTML content)
  DELETE blockValueList.bio={chi:"",eng:""}
Existing BIO edit is a separate PUT and was previously live verified.
These two additional actions are source-mapped/synthetic-tested ONLY.
"""
from __future__ import annotations

from copy import deepcopy

from job_platforms.core.errors import UnsupportedWrite

BIO_FIELDS = frozenset({"chi", "eng"})


def _form(document: dict) -> dict:
    try:
        form = document["bio"]["formData"]
    except (KeyError, TypeError) as exc:
        raise UnsupportedWrite("104 BIO block missing") from exc
    if not isinstance(form, dict):
        raise UnsupportedWrite("104 BIO native formData invalid")
    return form


def _content(value: object, *, nonempty: bool) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != BIO_FIELDS:
        raise UnsupportedWrite("104 BIO content must have chi and eng only")
    if not all(isinstance(v, str) for v in value.values()):
        raise UnsupportedWrite("104 BIO content must be HTML strings")
    if nonempty and not any(v.strip() for v in value.values()):
        raise UnsupportedWrite("104 BIO creation requires nonempty text")
    return deepcopy(value)


def bio_action_body(
    document: dict, action: str, *,
    changes: dict | None = None,
) -> dict:
    if action not in ("create", "clear"):
        raise UnsupportedWrite("104 BIO supports create/clear native actions")
    form = _form(document)
    if action == "create":
        if form:
            raise UnsupportedWrite("104 BIO already exists; use PATCH for edits")
        values = _content(changes, nonempty=True)
        return {"blockValueList": {"bio": {"bio": values}}}
    if changes is not None:
        raise UnsupportedWrite("104 BIO clear has no payload fields")
    old = form.get("bio")
    original = _content(old, nonempty=False)
    if not any(value for value in original.values()):
        raise UnsupportedWrite("104 BIO already empty")
    return {"blockValueList": {"bio": {"chi": "", "eng": ""}}}


def verify_bio_action(
    before: dict, after: dict, action: str, *,
    body: dict,
) -> bool:
    old_form = _form(before)
    new_form = _form(after)
    if action == "create":
        if old_form:
            return False
        try:
            new_content = _content(new_form.get("bio"), nonempty=True)
        except UnsupportedWrite:
            return False
        return new_content == body["blockValueList"]["bio"]["bio"]
    if action == "clear":
        if not old_form or "bio" not in old_form:
            return False
        if not new_form:
            return True
        try:
            data = _content(new_form.get("bio"), nonempty=False)
        except UnsupportedWrite:
            return False
        return data == {"chi": "", "eng": ""}
    return False
