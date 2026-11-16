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
from urllib.parse import urlsplit

from patchright.async_api import async_playwright

from job_platforms.core.errors import AuthenticationRequired
from .transport import BrowserTransport


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

    async def __aenter__(self):
        self._pw = await async_playwright().start()
        try:
            await self.open()
            return self
        except Exception:
            await self.__aexit__(None, None, None)
            raise

    async def __aexit__(self, *_):
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
        for index in self.config.proxy_priority:
            if not 1 <= index <= len(proxy_lines):
                continue
            parts = proxy_lines[index - 1].split(":", 3)
            if len(parts) != 4:
                continue
            host, port, username, password = parts
            profile = tempfile.TemporaryDirectory(prefix="job-platform-104-")
            browser = None
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
                await page.goto(
                    "https://pda.104.com.tw/work/peruseRecord/",
                    wait_until="domcontentloaded", timeout=24000,
                )
                await page.wait_for_timeout(1800)
                if await page.locator("input#identity:visible").count() != 1:
                    await page.goto(
                        "https://pda.104.com.tw/profile",
                        wait_until="domcontentloaded", timeout=24000,
                    )
                    await page.wait_for_timeout(3500)
                if await page.locator("input#identity:visible").count() != 1:
                    await page.goto(
                        "https://signin.104.com.tw/",
                        wait_until="domcontentloaded", timeout=24000,
                    )
                    await page.wait_for_timeout(2400)
                if urlsplit(page.url).hostname != "signin.104.com.tw":
                    raise AuthenticationRequired("No 104 sign-in form")
                if await page.locator("input#identity:visible").count() != 1:
                    raise AuthenticationRequired("No account field")
                status = await page.evaluate(
                    """async () => {
                        const response = await fetch('/v1/api/login/init', {
                            credentials:'include',
                            headers:{Accept:'application/json, text/plain, */*'}
                        });
                        return response.status;
                    }"""
                )
                if status != 200:
                    raise AuthenticationRequired("104 login initialization failed")
            except Exception:
                if browser is not None:
                    await browser.close()
                profile.cleanup()
                continue
            self._context = browser
            self._profile = profile
            self.page = page
            self.proxy_index = index
            break
        else:
            raise AuthenticationRequired("Could not establish a fresh 104 login session")

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
