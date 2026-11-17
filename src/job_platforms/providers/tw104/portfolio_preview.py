"""104 PORTFOLIO preview/conversion *status* read-only adapter.

Official frontend 44aa.GET_THUMBNAIL -> api/convertStatus/get
BFF route: GET /api/resumes/files/convert-status?fileId=...&tag=...
The status endpoint is not a conversion request: it only inspects
an existing FILE attachment in a user-owned current resume.
"""
from __future__ import annotations
from typing import Any

from job_platforms.core.errors import UnsupportedWrite,VerificationError
from .portfolio_records import portfolio_records


def conversion_file_id(doc: dict, *, position: int) -> str:
    """Resolve selected resume-owned FILE attachment; do not expose ID."""
    if type(position) is not int or position<1:
        raise UnsupportedWrite("104 PORTFOLIO status needs an existing sort")
    records=portfolio_records(doc)
    row=next((x for x in records if x["sort"]==position),None)
    if row is None or str(row["attachType"]["value"])!="1":
        raise UnsupportedWrite("104 preview status is only for existing FILE items")
    file_id=row["attach"]["fileId"]
    if (
        not isinstance(file_id,str) or not file_id or len(file_id)>4096
        or any(ord(ch)<32 for ch in file_id)
    ):
        raise UnsupportedWrite("104 fileId missing or invalid")
    return file_id


def convert_status_summary(raw: Any) -> dict:
    """Strict response projection without signed preview URLs or fileIds."""
    if not isinstance(raw,dict) or not isinstance(raw.get("data"),dict):
        raise VerificationError("104 conversion status response structure changed")
    data=raw["data"]
    status=data.get("convertStatus")
    if not isinstance(status,str) or not status or len(status)>64:
        raise VerificationError("104 conversion status field missing")
    urls=data.get("urls",[])
    if not isinstance(urls,list) or len(urls)>500 or any(
        not isinstance(x,str) for x in urls
    ):
        raise VerificationError("104 conversion preview URL list invalid")
    return {
        "convert_status":status,
        "preview_url_count":len(urls),
        "preview_ready":status.lower()=="success" and bool(urls),
        "read_only":True,
        "preview_bytes_verified":False,
        "conversion_requested":False,
    }
