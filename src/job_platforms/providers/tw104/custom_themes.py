"""104 CUSTOM non-TEXT theme request serializer, source-mapped but not live verified.

Source: production Vuex 4228.postData() and theme constants 5255.
Styles: CLASSIC=1, BANNER=2, TEXT=3, IMAGE=4, MAGAZINE=5.
TEXT CRUD is separately implemented/live-verified by custom_text_contract.

This module converts validated private user inputs into native JSON and
never sends writes on its own. Media/preview upload APIs are separate.
"""
from __future__ import annotations

import base64
import binascii
import re
from urllib.parse import urlsplit

from job_platforms.core.errors import UnsupportedWrite
from .custom_text_contract import (
    _slot, _safe_text, _safe_html,
    custom_text_create_body, NO_MEDIA,
)

THEMES = {
    1: "CLASSIC",2:"BANNER",3:"TEXT",
    4:"IMAGE",5:"MAGAZINE",
}
MEDIA_TYPES = {0,1,2,3}
MAX_ITEMS = 6
MAX_BINARY = 5*1024*1024


def _url(value: str, max_len: int = 200) -> str:
    if not isinstance(value,str) or len(value)>max_len:
        raise UnsupportedWrite("104 CUSTOM URL invalid")
    if not value:
        return ""
    parts=urlsplit(value)
    if (
        parts.scheme.lower() not in ("https","http")
        or not parts.netloc
        or parts.username
        or parts.password
    ):
        raise UnsupportedWrite("104 CUSTOM URL must be http(s)")
    return value


def _media(value: dict) -> dict:
    if not isinstance(value,dict) or type(value.get("type")) is not int:
        raise UnsupportedWrite("104 CUSTOM media type must be explicit integer")
    kind=value["type"]
    if kind not in MEDIA_TYPES:
        raise UnsupportedWrite("104 CUSTOM media type unsupported")
    ext=value.get("ext","")
    if not isinstance(ext,str) or len(ext)>16 or not re.fullmatch(r"[A-Za-z0-9]*",ext):
        raise UnsupportedWrite("104 CUSTOM media extension invalid")
    if kind==0:
        if set(value)!={"type"} and value!={"type":0,"ext":""}:
            raise UnsupportedWrite("104 CUSTOM NONE cannot hide any media metadata")
        return dict(NO_MEDIA)
    if kind==1:
        if set(value)!={"type","data_uri","ext"}:
            raise UnsupportedWrite("104 CUSTOM image requires data URI and extension")
        uri=value["data_uri"]
        if not isinstance(uri,str) or len(uri)>4*MAX_BINARY//3+256:
            raise UnsupportedWrite("104 CUSTOM image is too large")
        header,sep,payload=uri.partition(",")
        if not sep or header not in (
            "data:image/png;base64","data:image/jpeg;base64"
        ):
            raise UnsupportedWrite("104 CUSTOM image must use PNG/JPEG data URI")
        if ext.lower() not in (
            ("png",) if header.endswith("png;base64") else ("jpg","jpeg")
        ):
            raise UnsupportedWrite("104 CUSTOM image extension and MIME mismatch")
        try:
            raw=base64.b64decode(payload,validate=True)
        except (binascii.Error,ValueError):
            raise UnsupportedWrite("104 CUSTOM invalid image base64") from None
        if not 8<=len(raw)<=MAX_BINARY:
            raise UnsupportedWrite("104 CUSTOM image size out of bounds")
        if header.endswith("png;base64"):
            valid=raw.startswith(b"\x89PNG\r\n\x1a\n")
        else:
            valid=raw.startswith(b"\xff\xd8\xff") and raw.endswith(b"\xff\xd9")
        if not valid:
            raise UnsupportedWrite("104 CUSTOM invalid image signature")
        return {"type":1,"content":payload,"ext":ext}
    if kind==2:
        if set(value)!={"type","fileId","ext"}:
            raise UnsupportedWrite("104 CUSTOM VIDEO requires existing fileId")
        file_id=value["fileId"]
        if (
            not isinstance(file_id,str) or not file_id
            or len(file_id)>1024 or any(ord(c)<32 for c in file_id)
        ):
            raise UnsupportedWrite("104 CUSTOM VIDEO fileId invalid")
        return {"type":2,"content":file_id,"ext":ext}
    if set(value)!={"type","url","ext"}:
        raise UnsupportedWrite("104 CUSTOM LINK requires URL")
    return {"type":3,"content":_url(value["url"]),"ext":ext}


def _duration(value: dict, ongoing: bool) -> dict:
    expected={"startYear","startMonth","endYear","endMonth"}
    if not isinstance(value,dict) or set(value)!=expected:
        raise UnsupportedWrite("104 CUSTOM duration fields invalid")
    normalized={}
    for name in ("startYear","endYear"):
        year=value[name]
        if not isinstance(year,str) or (
            year and (not year.isascii() or not year.isdigit()
                      or not 1900<=int(year)<=2100)
        ):
            raise UnsupportedWrite("104 CUSTOM invalid year")
        normalized[name]=year
    for name in ("startMonth","endMonth"):
        month=value[name]
        if type(month) is not int or not 0<=month<=12:
            raise UnsupportedWrite("104 CUSTOM month must be 0..12 integer")
        normalized[name]=month if month else ""
    if ongoing:
        normalized["endYear"]=""
        normalized["endMonth"]=""
    return normalized


def custom_theme_create_body(
    *,slot: int, name: str, theme: int,
    contents: list[dict], theme_options: dict,
) -> dict:
    """Source-level create payload for non-TEXT theme, **offline only**."""
    _slot(slot)
    title=_safe_text(name,"name",30,required=True)
    if type(theme) is not int or theme not in THEMES:
        raise UnsupportedWrite("104 CUSTOM unknown theme")
    options=(theme_options.get("optionsCustomTheme")
             if isinstance(theme_options,dict) else None)
    if not isinstance(options,list) or not any(
        type(x.get("value")) is int and x["value"]==theme
        for x in options if isinstance(x,dict)
    ):
        raise UnsupportedWrite("104 CUSTOM theme not in current options")
    if (
        not isinstance(contents,list)
        or not 1<=len(contents)<=MAX_ITEMS
    ):
        raise UnsupportedWrite("104 CUSTOM content count invalid")
    if theme==3:
        if len(contents)!=1 or set(contents[0])!={"introduction_html"}:
            raise UnsupportedWrite("104 CUSTOM TEXT only accepts one text content")
        return custom_text_create_body(
            slot=slot,name=title,
            introduction_html=contents[0]["introduction_html"],
            theme_options=theme_options,
        )
    if theme==4:
        files=[]
        for entry in contents:
            if not isinstance(entry,dict) or set(entry)!={"media"}:
                raise UnsupportedWrite("104 CUSTOM IMAGE expects only media objects")
            media=_media(entry["media"])
            if media["type"]!=1:
                raise UnsupportedWrite("104 CUSTOM IMAGE theme only accepts images")
            files.append(media)
        blocks=[{"file":files}]
    else:
        blocks=[]
        for entry in contents:
            if not isinstance(entry,dict) or set(entry)!={
                "duration","isInProgress","introduction_html","url","media"
            }:
                raise UnsupportedWrite("104 CUSTOM content fields invalid")
            in_progress=entry["isInProgress"]
            if type(in_progress) is not bool:
                raise UnsupportedWrite("104 CUSTOM progress must be boolean")
            blocks.append({
                "duration":_duration(entry["duration"],in_progress),
                "isInProgress":int(in_progress),
                "introduction":_safe_html(entry["introduction_html"]),
                "url":_url(entry["url"]),
                "file":[_media(entry["media"])],
            })
    return {"blockValueList":{"custom":{
        "custom":{"name":title,"sort":slot,"content":blocks},
        "themeChoose":{"selectedTheme":theme},
    }}}
