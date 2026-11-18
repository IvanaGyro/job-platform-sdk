"""Fresh Patchright browser login for a personal 104 account.

Private credentials and proxy information are supplied at runtime.
A new browser profile is used for each login attempt; a working browser
and proxy remain fixed throughout account, password and MFA operations.
"""
from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, quote

from patchright.async_api import async_playwright

from job_platforms.core.errors import AuthenticationRequired
from .transport import BrowserTransport


@dataclass(frozen=True)
class PreloginDiagnostic:
    """Secret-free diagnostic for one proxy's *pre-account* login checks.

    `cloudflare` describes response evidence, not who caused a 403.
    It must never contain a URL, host, cookie, credential or response body.
    """
    proxy_index: int
    stage: str
    reason: str
    http_status: int | None = None
    cloudflare: str = "unconfirmed"
    network_error: str | None = None

    def summary(self) -> str:
        status = (f" status={self.http_status}" if self.http_status is not None else "")
        net = (f" net={self.network_error}" if self.network_error is not None else "")
        return (
            f"proxy#{self.proxy_index} stage={self.stage} "
            f"reason={self.reason}{status}{net} cf={self.cloudflare}"
        )


class _PreloginFailure(Exception):
    def __init__(
        self, reason: str, status: int | None = None,
        cloudflare: str = "unconfirmed",
    ):
        self.reason = reason
        self.status = status
        self.cloudflare = cloudflare
        super().__init__(reason)


def _browser_network_error(exc: Exception) -> str | None:
    """Extract only Chromium's fixed-format error code, never its raw trace.

    Chromium exception messages may contain unredacted proxy URLs, tokens,
    or full request paths. Only an uppercase machine error token is safe.
    """
    matched = re.search(r"\bnet::(ERR_[A-Z0-9_]{2,60})\b", str(exc))
    return matched.group(1) if matched else None


def _cloudflare_signal(headers: dict[str, str] | None) -> str:
    """Distinguish an explicit CF challenge from CF edge headers.

    A cf-ray on a 403 proves Cloudflare was in the response path, not
    that Cloudflare (rather than 104) decided to return 403.
    """
    headers = {str(k).lower(): str(v).lower() for k, v in (headers or {}).items()}
    if headers.get("cf-mitigated") == "challenge":
        return "challenge"
    if "cloudflare" in headers.get("server", "") or headers.get("cf-ray"):
        return "edge_headers"
    return "unconfirmed"


def _reject_prelogin_http_response(response):
    """Fail on an explicitly observed navigation HTTP error."""
    if response is None:
        raise _PreloginFailure("navigation_no_response")
    cf = _cloudflare_signal(response.headers)
    if cf == "challenge":
        raise _PreloginFailure("cloudflare_challenge", response.status, cf)
    if response.status >= 400:
        raise _PreloginFailure("http_error", response.status, cf)


@dataclass
class AuthConfig:
    credentials_file: str
    proxy_file: str
    proxy_priority: tuple[int, ...] = (4, 2, 5, 1, 3, 6, 7, 8, 9, 10)
    storage_state_file: str | None = None
    headless: bool = False

    @classmethod
    def from_env(cls) -> "AuthConfig":
        credentials = os.getenv("JOB_PLATFORM_104_CREDENTIALS_FILE")
        proxies = os.getenv("JOB_PLATFORM_104_PROXY_FILE")
        if not credentials or not proxies:
            raise ValueError("104 credential and proxy paths must be set")
        priority = os.getenv("JOB_PLATFORM_104_PROXY_PRIORITY")
        if priority is not None:
            parts = priority.split(",")
            if (not parts or any(
                not part.isascii() or not part.isdecimal() or part.startswith("0")
                for part in parts
            )):
                raise ValueError("104 proxy priority must be comma-separated positive indices")
            indices = tuple(int(part) for part in parts)
            if len(indices) != len(set(indices)) or any(not 1 <= i <= 100 for i in indices):
                raise ValueError("104 proxy priority indices must be unique and in range")
        else:
            indices = cls.__dataclass_fields__["proxy_priority"].default
        return cls(
            credentials_file=credentials,
            proxy_file=proxies,
            proxy_priority=indices,
            storage_state_file=os.getenv("JOB_PLATFORM_104_STATE_FILE"),
        )


def _credentials(path: str) -> dict[str, str]:
    raw = Path(path).read_text(encoding="utf-8-sig")
    result = dict(line.split("=", 1) for line in raw.splitlines()
                  if "=" in line and not line.lstrip().startswith("#"))
    required = ("A", "P", "ISSUE_DATE", "ISSUE_LOCATION", "ISSUE_METHOD")
    if not all(result.get(key) for key in required):
        raise ValueError("104 credential file is missing required fields")
    return result


async def _visible(*locators):
    for locator in locators:
        if await locator.count() and await locator.first.is_visible():
            return locator.first
    return None


def _issue_date(raw: str) -> tuple[int, int, int]:
    values = [int(item) for item in re.findall(r"\d+", raw)]
    if len(values) != 3:
        raise ValueError("Unexpected ISSUE_DATE format")
    year, month, day = values
    if year < 1912:
        year += 1911
    if not 1900 <= year <= 2100 or not 1 <= month <= 12 or not 1 <= day <= 31:
        raise ValueError("ISSUE_DATE outside expected ranges")
    return year, month, day


async def _select(page, qa: str, values: list[str], labels: list[str]):
    select = page.locator(f'select[data-qa-id="{qa}"]')
    if await select.count() != 1:
        raise AuthenticationRequired("104 identity form changed")
    options = await select.locator("option").evaluate_all(
        "es => es.map(e => ({value:e.value,label:e.textContent.trim()}))"
    )
    available_values = {item["value"] for item in options}
    available_labels = {item["label"] for item in options}
    for value in values:
        if str(value) in available_values:
            await select.select_option(value=str(value))
            return
    for label in labels:
        if label in available_labels:
            await select.select_option(label=label)
            return
    raise AuthenticationRequired("104 identity option unavailable")


def _region(location: str) -> tuple[str, str]:
    label = location.strip().replace("臺", "台")
    codes = {
        "台北市": "63000", "新北市": "65000", "桃園市": "68000",
        "台中市": "66000", "台南市": "67000", "高雄市": "64000",
        "基隆市": "10017", "新竹市": "10018", "嘉義市": "10020",
        "宜蘭縣": "10002", "新竹縣": "10004", "苗栗縣": "10005",
        "彰化縣": "10007", "南投縣": "10008", "雲林縣": "10009",
        "嘉義縣": "10010", "屏東縣": "10013", "台東縣": "10014",
        "花蓮縣": "10015", "澎湖縣": "10016", "金門縣": "09020",
        "連江縣": "09007",
    }
    return codes.get(label, label), label


async def _verify_identity(page, creds: dict[str, str]):
    alternate = await _visible(page.get_by_text("其他驗證方式", exact=False))
    if alternate:
        await alternate.click(timeout=12000)
        await page.wait_for_timeout(950)
    link = await _visible(page.locator('a[data-qa-id="id_for"]'))
    if link is None:
        raise AuthenticationRequired("104 identity verification route unavailable")
    await link.click(timeout=12000)
    await page.wait_for_url("**/mfa/identity*", timeout=20000)
    identity = await _visible(
        page.locator('input[data-qa-id="enter_id_number"]'),
        page.locator('[data-qa-id="enter_id_number"] input'),
    )
    if identity is None:
        raise AuthenticationRequired("104 identity input unavailable")
    await identity.fill(creds["A"])
    year, month, day = _issue_date(creds["ISSUE_DATE"])
    await _select(page, "field_year", [str(year)], [f"{year-1911}年"])
    await page.wait_for_timeout(280)
    await _select(page, "field_month", [str(month), f"{month:02d}"],
                  [f"{month}月", f"{month:02d}月"])
    await page.wait_for_timeout(280)
    await _select(page, "field_day", [str(day), f"{day:02d}"],
                  [f"{day}日", f"{day:02d}日"])
    code, label = _region(creds["ISSUE_LOCATION"])
    await _select(page, "place_of_issue_select", [code],
                  [label, label.replace("台", "臺")])
    method = creds["ISSUE_METHOD"].strip()
    methods = {"初發": "1", "初領": "1", "補發": "2", "補領": "2", "換發": "3"}
    await _select(page, "replacement_type_select",
                  [methods.get(method, method)], [method])
    submit = await _visible(page.locator('[data-qa-id="verify_otp"]'))
    if submit is None:
        raise AuthenticationRequired("104 identity submit control unavailable")
    async with page.expect_response(
        lambda response: (
            urlsplit(response.url).path == "/v1/api/mfa/verify/idcard"
            and response.request.method == "POST"
        ),
        timeout=25000,
    ) as waiter:
        await submit.click(timeout=15000, no_wait_after=True)
    response = await waiter.value
    try:
        body = await response.json()
    except Exception:
        body = None
    if response.status != 200 or not isinstance(body, dict) or not isinstance(
        body.get("redirect_uri"), str
    ):
        raise AuthenticationRequired("104 identity verification not confirmed")
    # The official frontend displays an optional contact-update dialog.
    # Continue normal login without changing the account's email or phone.
    later = page.get_by_role("button", name="暫時不要", exact=True)
    await later.wait_for(state="visible", timeout=12000)
    await later.click(timeout=15000, no_wait_after=True)
    await page.wait_for_timeout(3700)


class FreshBrowserSession:
    """Context manager holding a single browser+proxy for the full operation."""

    def __init__(self, config: AuthConfig):
        self.config = config
        self.page = None
        self.proxy_index = None
        self._pw = None
        self._context = None
        self._profile = None
        self._proxy_url = None
        self._http_transports = []
        self.prelogin_diagnostics: list[PreloginDiagnostic] = []

    async def __aenter__(self):
        self._pw = await async_playwright().start()
        try:
            await self.open()
            return self
        except Exception:
            await self.__aexit__(None, None, None)
            raise

    async def __aexit__(self, *_):
        for transport in self._http_transports:
            await transport.aclose()
        self._http_transports.clear()
        self._proxy_url = None
        if self._context is not None:
            await self._context.close()
            self._context = None
        if self._profile is not None:
            self._profile.cleanup()
            self._profile = None
        if self._pw is not None:
            await self._pw.stop()
            self._pw = None

    async def open(self):
        creds = _credentials(self.config.credentials_file)
        proxy_lines = Path(self.config.proxy_file).read_text().splitlines()
        self.prelogin_diagnostics.clear()
        for index in self.config.proxy_priority:
            if not 1 <= index <= len(proxy_lines):
                self.prelogin_diagnostics.append(
                    PreloginDiagnostic(index, "proxy_config", "invalid_index")
                )
                continue
            parts = proxy_lines[index - 1].split(":", 3)
            if len(parts) != 4 or any(not x for x in parts):
                self.prelogin_diagnostics.append(
                    PreloginDiagnostic(index, "proxy_config", "invalid_format")
                )
                continue
            host, port, username, password = parts
            profile = tempfile.TemporaryDirectory(prefix="job-platform-104-")
            browser = None
            stage = "chromium_launch"
            # Capture HTTP 403 evidence even when navigation throws.
            observed_errors: list[tuple[str, int, str]] = []
            try:
                browser = await self._pw.chromium.launch_persistent_context(
                    user_data_dir=profile.name,
                    headless=self.config.headless,
                    proxy={
                        "server": f"http://{host}:{port}",
                        "username": username, "password": password,
                    },
                    locale="zh-TW",
                    viewport={"width": 1366, "height": 900},
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                page = browser.pages[0] if browser.pages else await browser.new_page()

                def observe_response(response):
                    # Never record request URLs, response bodies or headers.
                    # Keep only the numeric HTTP status and CF signal on
                    # the two known 104 authentication domains.
                    if (
                        urlsplit(response.url).hostname in (
                            "pda.104.com.tw", "signin.104.com.tw"
                        )
                        and response.status in (403, 429, 503)
                    ):
                        observed_errors.append((
                            stage, response.status,
                            _cloudflare_signal(response.headers),
                        ))

                page.on("response", observe_response)

                stage = "pda_entry_navigation"
                response = await page.goto(
                    "https://pda.104.com.tw/work/peruseRecord/",
                    wait_until="domcontentloaded", timeout=24000,
                )
                _reject_prelogin_http_response(response)
                await page.wait_for_timeout(1800)
                stage = "pda_profile_navigation"
                if await page.locator("input#identity:visible").count() != 1:
                    response = await page.goto(
                        "https://pda.104.com.tw/profile",
                        wait_until="domcontentloaded", timeout=24000,
                    )
                    _reject_prelogin_http_response(response)
                    await page.wait_for_timeout(3500)
                stage = "signin_navigation"
                if await page.locator("input#identity:visible").count() != 1:
                    response = await page.goto(
                        "https://signin.104.com.tw/",
                        wait_until="domcontentloaded", timeout=24000,
                    )
                    _reject_prelogin_http_response(response)
                    await page.wait_for_timeout(2400)
                stage = "signin_hostname"
                if urlsplit(page.url).hostname != "signin.104.com.tw":
                    raise _PreloginFailure("unexpected_login_host")
                stage = "signin_form"
                if await page.locator("input#identity:visible").count() != 1:
                    raise _PreloginFailure("missing_identity_input")
                stage = "login_init"
                status = await page.evaluate(
                    """async () => {
                        const response = await fetch('/v1/api/login/init', {
                            credentials:'include',
                            headers:{Accept:'application/json, text/plain, */*'}
                        });
                        return {
                            status: response.status,
                            cloudflare: response.headers.get('cf-mitigated') === 'challenge'
                                ? 'challenge'
                                : (response.headers.get('cf-ray') ||
                                   (response.headers.get('server') || '').toLowerCase()
                                    .includes('cloudflare'))
                                ? 'edge_headers' : 'unconfirmed'
                        };
                    }"""
                )
                if (
                    not isinstance(status, dict)
                    or status.get("status") != 200
                    or status.get("cloudflare") == "challenge"
                ):
                    code = status.get("status") if isinstance(status, dict) else None
                    cf = status.get("cloudflare", "unconfirmed") if isinstance(status, dict) else "unconfirmed"
                    if code is not None and (not isinstance(code, int) or isinstance(code, bool)):
                        code = None
                    # The listener may also have seen a CF-specific header
                    # that fetch() could not expose to JS.
                    if code is not None and cf == "unconfirmed":
                        cf = next(
                            (signal for phase, c, signal in reversed(observed_errors)
                             if phase == stage and c == code and signal != "unconfirmed"),
                            cf,
                        )
                    raise _PreloginFailure("login_init_http_error", code, cf)
            except Exception as exc:
                if isinstance(exc, _PreloginFailure):
                    reason, code, cf = exc.reason, exc.status, exc.cloudflare
                else:
                    # Never include raw exception messages: Playwright
                    # errors can contain proxy URLs and credential material.
                    reason, code, cf = type(exc).__name__, None, "unconfirmed"
                network_error = (
                    None if isinstance(exc, _PreloginFailure)
                    else _browser_network_error(exc)
                )
                if code is None:
                    # Prefer direct observed response evidence to a generic
                    # Playwright exception during the SAME stage.
                    observed = next(
                        ((c, signal) for phase, c, signal in reversed(observed_errors)
                         if phase == stage), None,
                    )
                    if observed is not None:
                        code, cf = observed
                self.prelogin_diagnostics.append(
                    PreloginDiagnostic(
                        index, stage, reason, code, cf, network_error
                    )
                )
                if browser is not None:
                    await browser.close()
                profile.cleanup()
                continue
            self._context = browser
            self._profile = profile
            self.page = page
            self.proxy_index = index
            self._proxy_url = (
                f"http://{quote(username, safe='')}:{quote(password, safe='')}"
                f"@{host}:{port}"
            )
            break
        else:
            safe_details = "; ".join(
                item.summary() for item in self.prelogin_diagnostics
            )
            raise AuthenticationRequired(
                "Could not establish a fresh 104 login session"
                + (f": {safe_details}" if safe_details else "")
            )

        account = await _visible(self.page.locator("input#identity:visible"))
        next_button = await _visible(
            self.page.locator('[data-qa-id="nextstep"]:visible')
        )
        if account is None or next_button is None:
            raise AuthenticationRequired("104 account step changed")
        await account.fill(creds["A"])
        await next_button.click(timeout=15000)
        # The account-validation request is asynchronous. A fixed 2.1-second
        # sleep occasionally classified a valid, still-loading page as a
        # changed login form. Wait for the actual password UI instead.
        try:
            await self.page.locator('input[type="password"]:visible').first.wait_for(
                state="visible", timeout=20000
            )
        except Exception as exc:
            raise AuthenticationRequired(
                "104 password step unavailable after account validation"
            ) from None
        password = await _visible(self.page.locator('input[type="password"]:visible'))
        submit = await _visible(
            self.page.get_by_role("button", name=re.compile("登入|login|sign in", re.I)),
            self.page.locator('button[type="submit"]:visible'),
        )
        if password is None or submit is None:
            raise AuthenticationRequired("104 password step changed")
        await password.fill(creds["P"])
        await submit.click(timeout=15000, no_wait_after=True)
        await self.page.wait_for_timeout(3400)
        if urlsplit(self.page.url).path.startswith("/mfa"):
            await _verify_identity(self.page, creds)
        if urlsplit(self.page.url).hostname != "pda.104.com.tw":
            await self.page.goto(
                "https://pda.104.com.tw/profile",
                wait_until="domcontentloaded", timeout=25000,
            )
        await self.page.wait_for_timeout(2500)
        if not await BrowserTransport(self.page).ensure_authenticated():
            raise AuthenticationRequired("104 authenticated resume access not verified")

        if self.config.storage_state_file:
            state = Path(self.config.storage_state_file)
            state.parent.mkdir(parents=True, exist_ok=True)
            await self._context.storage_state(path=str(state))
            state.chmod(0o600)

    async def http_transport(
        self, *, allow_writes: bool = False, close_browser: bool = False,
    ):
        """Move 104 cookies into curl_cffi on the original login proxy.

        By default the browser stays available for comparison and fallback.
        Optional close_browser releases browser resources once cookies have
        been transferred; subsequent browser-only operations are unavailable.
        All HTTP sessions close with FreshBrowserSession.
        """
        if self._context is None or self._proxy_url is None or self.page is None:
            raise AuthenticationRequired("104 login required before HTTP handoff")
        from .http_transport import CurlCffiTransport
        state = await self._context.storage_state()
        user_agent = await self.page.evaluate("navigator.userAgent")
        transport = CurlCffiTransport.from_storage_state(
            state, proxy_url=self._proxy_url, user_agent=user_agent,
            allow_writes=allow_writes,
        )
        self._http_transports.append(transport)
        if close_browser:
            # The chosen HTTP session keeps its own cookies/proxy. Free
            # Chromium only after the handoff was constructed successfully.
            await self._context.close()
            self._context = None
            self.page = None
            if self._profile is not None:
                self._profile.cleanup()
                self._profile = None
            if self._pw is not None:
                await self._pw.stop()
                self._pw = None
        return transport

    async def resume_client(
        self, *, transport: str = "browser", allow_http_writes: bool = False,
    ):
        """Create a resume client with interchangeable browser / HTTP backend."""
        from .client import Resume104Client
        if transport == "browser":
            return Resume104Client(self.page)
        if transport in ("curl_cffi", "curl_cffi_detached"):
            detached = transport == "curl_cffi_detached"
            http = await self.http_transport(
                allow_writes=allow_http_writes,
                close_browser=detached,
            )
            return Resume104Client(
                None if detached else self.page, transport=http,
            )
        raise ValueError(
            "104 transport must be browser, curl_cffi or curl_cffi_detached"
        )
