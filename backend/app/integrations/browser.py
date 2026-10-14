"""A web browser the agent drives: open sites, read them as numbered elements, click, type and choose.

It runs your installed Chrome or Edge (or Playwright's Chromium) without a window, in its own profile under the
data folder: never your everyday browser and its sign-ins. Like reading pages, it only reaches the public web,
and what a page says is passed on as data, not instructions. Clicking and typing wait for your Approve.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import threading
from typing import Any, Awaitable, Callable, Optional, TypeVar
from urllib.parse import urlparse

from app.integrations import web
from app.integrations.base import IntegrationTool, Kind

logger = logging.getLogger(__name__)

CHANNELS = ("chrome", "msedge", None)  # installed Chrome, then Edge, then Playwright's own Chromium
NAMES = {"chrome": "Google Chrome", "msedge": "Microsoft Edge", None: "Chromium"}
IDLE_SECONDS = 600  # close the browser after this long unused
TIMEOUT_MS = 15_000
MAX_ELEMENTS = 150
MAX_TEXT = 6000
MAX_IMAGES = 20
# Headless Chrome says "HeadlessChrome" in its user agent and some sites turn it away: report the plain Chrome
# one it really is, per browser (found on first launch).
_AGENTS: dict[Optional[str], Optional[str]] = {}
# Tests serve a fake web here: url -> (status, content type, body), or None to go out for real.
PAGES: Optional[Callable[[str], Optional[tuple[int, str, str]]]] = None

T = TypeVar("T")
_LOOP: Optional[asyncio.AbstractEventLoop] = None
_LOOP_LOCK = threading.Lock()


def _loop() -> asyncio.AbstractEventLoop:
    """The browser's own event loop, on its own thread. Playwright starts the browser as a program, which the
    server's loop can't do on Windows under ``uvicorn --reload`` (a selector loop raises NotImplementedError)."""
    global _LOOP
    with _LOOP_LOCK:
        if _LOOP is None or _LOOP.is_closed():
            _LOOP = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
            threading.Thread(target=_LOOP.run_forever, name="nexus-browser", daemon=True).start()
        return _LOOP


async def _on_browser_loop(work: Awaitable[T]) -> T:
    return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(work, _loop()))  # type: ignore[arg-type]

# Numbers every visible thing you can click, type in or choose, and returns them with the page's text.
SNAPSHOT_JS = """() => {
  const sel = 'a[href],button,input:not([type=hidden]),select,textarea,summary,[role=button],[role=link],[role=checkbox],'
    + '[role=radio],[role=tab],[role=menuitem],[role=option],[role=switch],[role=combobox],[role=textbox],[contenteditable=""],'
    + '[contenteditable=true],[onclick]';
  document.querySelectorAll('[data-nexus-ref]').forEach(e => e.removeAttribute('data-nexus-ref'));
  const inputRoles = {checkbox: 'checkbox', radio: 'radio', submit: 'button', button: 'button', search: 'searchbox'};
  const out = [];
  for (const el of document.querySelectorAll(sel)) {
    if (out.length >= LIMIT) break;
    const box = el.getBoundingClientRect(), style = getComputedStyle(el);
    if (!box.width || !box.height || style.visibility === 'hidden' || style.display === 'none' || el.disabled) continue;
    const ref = out.length + 1;
    el.setAttribute('data-nexus-ref', String(ref));
    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute('role') || ({a: 'link', select: 'select', textarea: 'textbox'}[tag])
      || (tag === 'input' ? (inputRoles[el.type] || 'textbox') : tag);
    const label = el.labels && el.labels[0] ? el.labels[0].innerText : '';
    const name = (el.getAttribute('aria-label') || label || el.innerText || el.getAttribute('placeholder')
      || el.getAttribute('title') || el.getAttribute('alt') || (el.type === 'password' ? '' : el.value) || '')
      .trim().replace(/\\s+/g, ' ').slice(0, 80);
    const item = {ref, role, name};
    if (tag === 'select') item.value = el.options[el.selectedIndex] ? el.options[el.selectedIndex].text : '';
    else if (['textbox', 'searchbox', 'combobox'].includes(role) && el.value && el.type !== 'password') item.value = String(el.value).slice(0, 80);
    if (role === 'checkbox' || role === 'radio') item.checked = !!el.checked;
    out.push(item);
  }
  const images = [];  // pictures worth showing: not icons, not inline data
  for (const img of document.querySelectorAll('img')) {
    if (images.length >= MAX_IMAGES) break;
    const box = img.getBoundingClientRect(), src = img.currentSrc || img.src;
    if (box.width < 80 || box.height < 80 || !/^https?:/.test(src)) continue;
    images.push({src, alt: (img.alt || img.title || '').trim().replace(/\\s+/g, ' ').slice(0, 80)});
  }
  return {elements: out, images, text: document.body ? document.body.innerText : ''};
}""".replace("LIMIT", str(MAX_ELEMENTS)).replace("MAX_IMAGES", str(MAX_IMAGES))


class Browser:
    """One browser per connected integration, started on first use and closed when idle or removed."""

    def __init__(self, integration_id: int) -> None:
        self.integration_id = integration_id
        self.lock = asyncio.Lock()  # one action at a time: chats share the one tab
        self._playwright: Any = None
        self._context: Any = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self.channel: Optional[str] = None
        self._timer: Optional[asyncio.TimerHandle] = None
        self._closing: Optional[asyncio.Future] = None
        self._allowed: dict[str, bool] = {}

    async def _guard(self, route: Any) -> None:
        """Every request the page makes: only to the public web (like reading pages), or the tests' fake web."""
        url = route.request.url
        if url.startswith(("data:", "blob:", "about:")):
            await route.continue_()
            return
        host = urlparse(url).hostname or ""
        if host not in self._allowed:
            try:
                await asyncio.to_thread(web._check_public, url)
                self._allowed[host] = True
            except ValueError:
                self._allowed[host] = False
        if not self._allowed[host]:
            await route.abort("blockedbyclient")
        elif PAGES and (fake := PAGES(url)):
            await route.fulfill(status=fake[0], content_type=fake[1], body=fake[2])
        else:
            await route.continue_()

    async def page(self) -> Any:
        if self._context is None:
            from playwright.async_api import async_playwright

            from app.core.database import get_db_path

            self._playwright = await async_playwright().start()
            profile = get_db_path().parent / "browser" / str(self.integration_id)
            errors = []

            async def launch(channel: Optional[str]) -> Any:
                return await self._playwright.chromium.launch_persistent_context(
                    str(profile), channel=channel, headless=True, accept_downloads=False, user_agent=_AGENTS.get(channel),
                    args=["--disable-blink-features=AutomationControlled"])

            for channel in CHANNELS:
                try:
                    self._context = await launch(channel)
                    if channel not in _AGENTS:
                        probe = self._context.pages[0] if self._context.pages else await self._context.new_page()
                        agent = await probe.evaluate("navigator.userAgent")
                        _AGENTS[channel] = agent.replace("HeadlessChrome", "Chrome") if "Headless" in agent else None
                        if _AGENTS[channel]:
                            await self._context.close()
                            self._context = await launch(channel)
                    self.channel = channel
                    break
                except Exception as exc:
                    errors.append(f"{NAMES[channel]}: {str(exc).splitlines()[0]}")
            if self._context is None:
                await self._playwright.stop()
                raise ValueError("No browser to drive: install Google Chrome or Microsoft Edge, or run "
                                 "'python -m playwright install chromium'. (" + "; ".join(errors) + ")")
            self._loop = asyncio.get_running_loop()
            OPEN.add(self)
            self._context.set_default_timeout(TIMEOUT_MS)
            await self._context.route("**/*", self._guard)
        if self._timer:
            self._timer.cancel()
        loop = self._loop
        self._timer = loop.call_later(IDLE_SECONDS, lambda: loop.create_task(self.close()))  # unused for a while: close
        return self._context.pages[0] if self._context.pages else await self._context.new_page()

    async def close(self) -> None:
        """Close the browser; a second call waits for a close already under way (Nexus can't exit mid-close)."""
        if self._closing is None:
            self._closing = asyncio.ensure_future(self._shut())
        try:
            await self._closing
        finally:
            self._closing = None

    async def _shut(self) -> None:
        if self._timer:
            self._timer.cancel()
        context, playwright, self._context, self._playwright = self._context, self._playwright, None, None
        try:
            if context is not None:
                await context.close()
        except Exception:  # already gone
            pass
        try:
            if playwright is not None:
                await playwright.stop()
        except Exception:
            pass
        OPEN.discard(self)

    def stop(self) -> None:  # the integration was removed
        if self._loop and self._context is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(lambda: self._loop.create_task(self.close()))


    async def snapshot(self, page: Any) -> dict[str, Any]:
        try:
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:  # pages that never go quiet (live feeds) are read as they are
            pass
        found = await page.evaluate(SNAPSHOT_JS)
        lines = []
        for e in found["elements"]:
            extra = f' value="{e["value"]}"' if "value" in e else ""
            extra += (" (checked)" if e.get("checked") else " (not checked)") if "checked" in e else ""
            lines.append(f'[{e["ref"]}] {e["role"]} "{e["name"]}"{extra}')
        text = found["text"].strip()
        title = await page.title()
        pictures = "".join(f'\n- "{i["alt"]}" {i["src"]}' for i in found["images"])
        body = (f'<page url="{page.url}" title="{title}">\nThings you can use (pass the number as ref):\n'
                + ("\n".join(lines) or "(none)")
                + (f"\n\nPictures (to show one, put it in your reply as a Markdown image: ![description](address)):{pictures}"
                   if pictures else "")
                + f"\n\nPage text:\n{text[:MAX_TEXT]}"
                + ("\n(… more text below)" if len(text) > MAX_TEXT else "") + f"\n</page>\n{web.DATA_NOTE}")
        return {"text": body, "data": {"url": page.url, "title": title, "elements": len(lines)}}

    async def element(self, page: Any, ref: Any) -> Any:
        target = page.locator(f'[data-nexus-ref="{int(ref)}"]')
        if await target.count() == 0:
            raise ValueError(f"Element [{ref}] isn't on the page any more: look at the page again for fresh numbers")
        return target.first


OPEN: set[Browser] = set()  # running browsers, closed when Nexus shuts down


async def close_all() -> None:
    if not OPEN:
        return

    async def close() -> None:
        await asyncio.gather(*(b.close() for b in list(OPEN)), return_exceptions=True)

    await _on_browser_loop(close())


class PageTool(IntegrationTool):
    """Its result is already the text the model reads (the page, wrapped as data) plus ``data``."""

    async def execute(self, parameters: dict[str, Any]) -> dict[str, Any]:
        return await self._run(parameters or {})


def _browser(config: dict[str, Any]) -> Browser:
    from app.integrations import integration_manager

    runner = integration_manager.runner(config.get("_integration_id"))
    if not isinstance(runner, Browser):
        raise ValueError("The browser isn't connected")
    return runner


def tools(slug: str, name: str, config: dict[str, Any]) -> list[IntegrationTool]:
    def action(run: Callable[[Browser, Any, dict[str, Any]], Any]) -> Callable[[dict[str, Any]], Any]:
        async def go(p: dict[str, Any]) -> Any:
            browser = _browser(config)

            async def work() -> Any:
                async with browser.lock:
                    page = await browser.page()
                    await run(browser, page, p)
                    return await browser.snapshot(page)

            return await _on_browser_loop(work())
        return go

    async def open_page(browser: Browser, page: Any, p: dict[str, Any]) -> None:
        url = str(p.get("url") or "").strip()
        if url and "://" not in url:
            url = f"https://{url}"
        await asyncio.to_thread(web._check_public, url)  # a readable refusal, before the browser's own
        await page.goto(url)

    async def look(browser: Browser, page: Any, p: dict[str, Any]) -> None:
        pass

    async def go_back(browser: Browser, page: Any, p: dict[str, Any]) -> None:
        await page.go_back()

    async def click(browser: Browser, page: Any, p: dict[str, Any]) -> None:
        await (await browser.element(page, p.get("ref"))).click()

    async def type_text(browser: Browser, page: Any, p: dict[str, Any]) -> None:
        target = await browser.element(page, p.get("ref"))
        await target.fill(str(p.get("text") or ""))
        if p.get("submit"):
            await target.press("Enter")

    async def select_option(browser: Browser, page: Any, p: dict[str, Any]) -> None:
        await (await browser.element(page, p.get("ref"))).select_option(label=str(p.get("option") or ""))

    async def press_key(browser: Browser, page: Any, p: dict[str, Any]) -> None:
        await page.keyboard.press(str(p.get("key") or "Enter"))

    async def screenshot(p: dict[str, Any]) -> Any:
        from app.files import _store

        browser = _browser(config)

        async def work() -> tuple[str, bytes]:
            async with browser.lock:
                page = await browser.page()
                return page.url, await page.screenshot(full_page=bool(p.get("full_page")))

        url, image = await _on_browser_loop(work())
        made = _store(f"screenshot-{(urlparse(url).hostname or 'page').replace('.', '-')}.png", image)
        return {"text": f"Took a screenshot of {url}; the user can see it in the chat.", "data": {"file": made}}

    target = {"ref": {"type": "integer", "description": "The element's number from the page"},
              "element": {"type": "string", "description": "What it is, in a few words (shown when asking the user), e.g. 'Search button'"}}

    def tool(tool_name: str, description: str, properties: dict[str, Any], required: list[str], run: Any,
             changes: bool, title: str) -> IntegrationTool:
        return PageTool(slug, name, tool_name, description, {"properties": properties, "required": required},
                        run, read_only=not changes, title=title)

    opener = tool("open_page", "Open a website in the browser to use it like a person would (search a site, click through, fill "
             "forms, check a booking or an order, find pictures). Returns the page as numbered elements, its pictures and "
             "its text. If a site turns automated visits away (a captcha, 'unusual traffic'), try another site that has "
             "the same thing instead of giving up.",
             {"url": {"type": "string"}}, ["url"], action(open_page), False, "Open page")
    opener.link_args = ("url",)  # an address the model built (not one seen in the chat) needs your OK
    return [
        opener,
        tool("look", "Look at the browser's current page again: fresh element numbers and text.", {}, [], action(look), False,
             "Look at page"),
        tool("go_back", "Go back to the previous page in the browser.", {}, [], action(go_back), False, "Go back"),
        tool("screenshot", "Take a screenshot of the browser's current page to show the user.",
             {"full_page": {"type": "boolean", "description": "The whole page instead of what fits the window"}}, [],
             screenshot, False, "Screenshot"),
        tool("click", "Click a link, button, checkbox or tab on the browser's page, by its number.", target,
             ["ref", "element"], action(click), True, "Click"),
        tool("type_text", "Type into a text box on the browser's page (replacing what's there); submit presses Enter.",
             {**target, "text": {"type": "string"}, "submit": {"type": "boolean"}}, ["ref", "element", "text"],
             action(type_text), True, "Type"),
        tool("select_option", "Choose an option in a dropdown on the browser's page, by the option's visible text.",
             {**target, "option": {"type": "string"}}, ["ref", "element", "option"], action(select_option), True, "Choose"),
        tool("press_key", "Press a key in the browser, e.g. Enter, Escape, Tab, PageDown.",
             {"key": {"type": "string"}}, ["key"], action(press_key), True, "Press key"),
    ]


async def check(config: dict[str, Any]) -> str:
    async def probe() -> str:
        browser = Browser(0)
        try:
            page = await browser.page()
            await page.set_content("<p>ok</p>")
            return f"Using {NAMES[browser.channel]}, without a window, in its own profile"
        finally:
            await browser.close()

    return await _on_browser_loop(probe())


def start(integration_id: int, config: dict[str, Any]) -> Browser:
    return Browser(integration_id)  # opens on first use


KIND = Kind("browser", "Web browser", "Let the agent use websites for you: open them, click, type and fill in forms. "
            "Clicks and typing wait for your OK.", "MousePointerClick", [], check, tools, start=start)
