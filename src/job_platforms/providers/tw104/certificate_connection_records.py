"""Browser-only 104 certificate-association writer via deployed Vuex actions.

The compiled official editor module 779c provides:
  form/certificate/setCertificationConnect(certIds)
  form/certificate/deleteCertificationConnect(certId)
  form/certificate/getCertificationList()

This deliberately dispatches the *official loaded frontend action* instead
of guessing an unverified HTTP endpoint. No global certificate record is
created, edited or deleted. Actual 104 site acceptance still needs a live
authorized CRUD/read-back/restore test.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from job_platforms.core.errors import UnsupportedWrite

from .certificate_connection_contract import (
    certificate_connect_plan, certificate_disconnect_plan,
)

# Official certificate editor UI importLimit=20 (module 779c component).
MAX_IMPORT = 20


def linked_certificate_items(document: dict) -> dict[int, tuple[int | str, dict]]:
    """Read grouped, resume-owned items, retaining stable existing metadata."""
    try:
        value = document["certificate"]["formData"]["certificate"]
        groups = value["certifications"]
    except (KeyError, TypeError):
        raise UnsupportedWrite("104 linked certificate native GET unavailable") from None
    if not isinstance(value, dict) or not isinstance(groups, list):
        raise UnsupportedWrite("104 linked certificate groups are missing")
    if not isinstance(value.get("others"), str):
        raise UnsupportedWrite("104 linked certificate text metadata missing")
    entries: dict[int, tuple[int | str, dict]] = {}
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("items"), list):
            raise UnsupportedWrite("104 linked certificate grouping changed")
        if not isinstance(group.get("category"), (int, str)):
            raise UnsupportedWrite("104 linked certificate group category missing")
        for item in group["items"]:
            if not isinstance(item, dict):
                raise UnsupportedWrite("104 linked certificate record must be an object")
            entry = item.get("id")
            if type(entry) is not int or entry <= 0:
                raise UnsupportedWrite("104 linked certificate record ID is invalid")
            if entry in entries:
                raise UnsupportedWrite("104 linked certificate IDs are ambiguous")
            entries[entry] = (group["category"], deepcopy(item))
    return entries


def linked_certificate_ids(document: dict) -> frozenset[int]:
    return frozenset(linked_certificate_items(document))


def verify_certificate_association(
    before: dict, after: dict, *,
    desired_ids: frozenset[int],
) -> bool:
    """No certificate text/layout/other section may be silently replaced."""
    prior_items = linked_certificate_items(before)
    next_items = linked_certificate_items(after)
    if frozenset(next_items) != desired_ids:
        return False
    # Existing account-owned certificates must retain their metadata, not
    # silently mutate when the resume-level relationship changes.
    if any(next_items.get(cert_id) != old for cert_id, old in prior_items.items()
           if cert_id in next_items):
        return False
    previous = deepcopy(before["certificate"])
    latest = deepcopy(after["certificate"])
    for obj in (previous, latest):
        del obj["formData"]["certificate"]["certifications"]
    return previous == latest


# The executed JavaScript is constant text; no source-derived URL or string
# concatenation from caller input. Only exact whitelisted action IDs.
_BROWSER_CERT_DISPATCH = """async ({vno, action, ids, recordId}) => {
  if (location.hostname !== 'pda.104.com.tw')
    throw Error('Official My104 editor origin required');
  const store = window.$nuxt?.$store;
  if (!store || String(store.state?.vno) !== String(vno))
    throw Error('Loaded editor resume does not match requested vno');
  const actions = {
    connect: 'form/certificate/setCertificationConnect',
    disconnect: 'form/certificate/deleteCertificationConnect'
  };
  const type = Object.prototype.hasOwnProperty.call(actions, action)
    ? actions[action] : null;
  if (!type || !Object.prototype.hasOwnProperty.call(store._actions || {}, type))
    throw Error('Official certificate association action not installed');
  if (action === 'connect') {
    const certResult = await store.dispatch('form/certificate/getCertificationList');
    const records = certResult?.data?.data;
    if (!Array.isArray(records) || !records.every(x =>
        x && Number.isSafeInteger(x.id) && x.id > 0))
      throw Error('Account certificate option list shape changed');
    const ownedIds = new Set(records.map(x => x.id));
    if (!ids.every(x => ownedIds.has(x)))
      throw Error('Selected certificate ID is not in account-owned list');
  }
  await store.dispatch(type, action === 'connect' ? ids : recordId);
  return {submitted: true};
}"""


async def dispatch_certification_action(page: Any, *, resume_id: str,
                                        action: str, ids: list[int],
                                        record_id: int | None) -> None:
    """Submit one authenticated official Vuex action, never a guessed URL."""
    if not callable(getattr(page, "evaluate", None)):
        raise UnsupportedWrite("104 certificate connections require browser page")
    try:
        confirmation = await page.evaluate(_BROWSER_CERT_DISPATCH, {
            "vno": resume_id,
            "action": action,
            "ids": ids,
            "recordId": record_id,
        })
    except Exception:
        # The website might already have processed the operation. Do NOT
        # retry it, and never echo browser error text containing private data.
        from job_platforms.core.errors import VerificationError
        raise VerificationError(
            "104 certificate association outcome unknown; independent GET required"
        ) from None
    if confirmation != {"submitted": True}:
        from job_platforms.core.errors import VerificationError
        raise VerificationError(
            "104 certificate action returned unrecognized acknowledgement"
        )


def validate_certificate_action(before: dict, *, action: str,
                                ids: Any = None, record_id: Any = None
                                ) -> frozenset[int]:
    existing = linked_certificate_ids(before)
    if action == "connect":
        if record_id is not None:
            raise UnsupportedWrite("104 certificate connect accepts no record ID")
        certificate_connect_plan(ids)
        if len(ids) > MAX_IMPORT:
            raise UnsupportedWrite("104 certificate import exceeds editor limit 20")
        desired = frozenset(ids)
        if desired == existing:
            raise UnsupportedWrite("104 certificate selection unchanged")
        return desired
    if action == "disconnect":
        if ids is not None:
            raise UnsupportedWrite("104 certificate disconnect accepts no selection list")
        certificate_disconnect_plan(record_id)
        if record_id not in existing:
            raise UnsupportedWrite("104 certificate is not linked to this resume")
        return existing - {record_id}
    raise UnsupportedWrite("104 certificate association action unsupported")
