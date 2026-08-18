"""Monitor Paychain offers with a visible Playwright browser.

Log in manually on the first run.  The default is dry-run: qualifying offers
are logged but are never accepted.  Use --auto-accept only after testing the
selectors in the account you are authorized to operate.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from hashlib import sha256
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from playwright.async_api import BrowserContext, Locator, Page, TimeoutError as PlaywrightTimeoutError, async_playwright


ROOT = Path(__file__).parent
STATE_FILE = ROOT / "storage_state.json"
PROCESSED_FILE = ROOT / "processed_offers.json"
LOG_DIR = ROOT / "logs"
activity_log = logging.getLogger("activity")


@dataclass(frozen=True)
class Settings:
    offers_url: str
    refresh_seconds: float
    minimum_amount_uah: Decimal
    offer_selector: str
    offer_id_attribute: str
    offer_key_selector: str
    amount_selector: str
    currency_selector: str
    status_selector: str
    action_menu_button_selector: str
    accept_button_selector: str
    active_statuses: tuple[str, ...]


@dataclass(frozen=True)
class Offer:
    offer_id: str
    amount: Decimal
    currency: str
    status: str
    element: Locator


def load_settings(config_path: Path) -> Settings:
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    required = (
        "offers_url", "refresh_seconds", "minimum_amount_uah", "offer_selector",
        "amount_selector", "currency_selector",
    )
    missing = [key for key in required if not raw.get(key)]
    if missing:
        raise ValueError(f"В config.json відсутні поля: {', '.join(missing)}")
    return Settings(
        offers_url=str(raw["offers_url"]),
        refresh_seconds=float(raw["refresh_seconds"]),
        minimum_amount_uah=Decimal(str(raw["minimum_amount_uah"])),
        offer_selector=str(raw["offer_selector"]),
        offer_id_attribute=str(raw.get("offer_id_attribute", "")),
        offer_key_selector=str(raw.get("offer_key_selector", "")),
        amount_selector=str(raw["amount_selector"]),
        currency_selector=str(raw["currency_selector"]),
        status_selector=str(raw.get("status_selector", "")),
        action_menu_button_selector=str(raw.get("action_menu_button_selector", "")),
        accept_button_selector=str(raw.get("accept_button_selector", "")),
        active_statuses=tuple(str(x).casefold() for x in raw.get("active_statuses", ["active"])),
    )


def parse_amount(raw: str) -> Decimal:
    """Parse strings such as '5 001,50 грн' without using floating point."""
    cleaned = raw.replace("\u00a0", " ").replace(" ", "")
    cleaned = re.sub(r"[^0-9,.-]", "", cleaned).replace(",", ".")
    if cleaned.count(".") > 1:
        raise ValueError(f"Не вдалося розібрати суму: {raw!r}")
    try:
        return Decimal(cleaned)
    except InvalidOperation as error:
        raise ValueError(f"Не вдалося розібрати суму: {raw!r}") from error


def load_processed() -> set[str]:
    if not PROCESSED_FILE.exists():
        return set()
    try:
        data = json.loads(PROCESSED_FILE.read_text(encoding="utf-8"))
        return set(map(str, data))
    except (OSError, json.JSONDecodeError):
        logging.warning("Не вдалося прочитати processed_offers.json; починаю з порожнього журналу.")
        return set()


def save_processed(processed: set[str]) -> None:
    # Keep the file compact while protecting against accidental endless growth.
    PROCESSED_FILE.write_text(json.dumps(sorted(processed)[-5000:], ensure_ascii=False, indent=2), encoding="utf-8")


async def text_in(offer: Locator, selector: str) -> str:
    target = offer.locator(selector).first
    return (await target.inner_text()).strip()


def parse_currency(raw: str) -> str:
    match = re.search(r"\b([A-Z]{3,5})\b", raw.upper())
    if not match:
        raise ValueError(f"Не вдалося визначити валюту: {raw!r}")
    return match.group(1)


async def scan_offers(page: Page, settings: Settings) -> list[Offer]:
    cards = page.locator(settings.offer_selector)
    count = await cards.count()
    offers: list[Offer] = []
    for index in range(count):
        card = cards.nth(index)
        offer_id = await card.get_attribute(settings.offer_id_attribute) if settings.offer_id_attribute else None
        if not offer_id and settings.offer_key_selector:
            # The page fragment does not expose offer ID.  Hash a local stable identifier;
            # its source value is never logged or saved in plain text.
            key = await text_in(card, settings.offer_key_selector)
            offer_id = sha256(key.encode("utf-8")).hexdigest()
        if not offer_id:
            key = await card.inner_text()
            offer_id = sha256(key.encode("utf-8")).hexdigest()
        try:
            offer = Offer(
                offer_id=offer_id,
                amount=parse_amount(await text_in(card, settings.amount_selector)),
                currency=parse_currency(await text_in(card, settings.currency_selector)),
                status=(
                    (await text_in(card, settings.status_selector)).casefold()
                    if settings.status_selector
                    # In the table view an offer with this row-scoped direct action is actionable.
                    else ("active" if await card.locator(settings.accept_button_selector).count() else "")
                ),
                element=card,
            )
            offers.append(offer)
        except (PlaywrightTimeoutError, ValueError) as error:
            logging.warning("Оффер %s пропущено: %s", offer_id, error)
    return offers


async def accept_offer(page: Page, offer: Offer, settings: Settings) -> bool:
    if not settings.accept_button_selector:
        logging.error("Не задано безпечний селектор кнопки Accept у межах картки. Автоприйняття вимкнено.")
        return False
    try:
        if settings.action_menu_button_selector:
            await offer.element.locator(settings.action_menu_button_selector).first.click(timeout=5_000)
        # The confirmation control is scoped to this row.  Verify success from
        # the API response instead of assuming the entire table row disappears.
        button = offer.element.locator(settings.accept_button_selector).first
        async with page.expect_response(
            lambda response: response.request.method == "POST" and response.url.rstrip("/").endswith("/accept"),
            timeout=8_000,
        ) as response_info:
            await button.click(timeout=5_000)
        response = await response_info.value
        if not 200 <= response.status < 300:
            logging.error("Прийняття оффера %s повернуло HTTP %s.", offer.offer_id, response.status)
            activity_log.info("ВІДХИЛЕНО API | оффер %s | %s %s | HTTP %s", offer.offer_id[:8], offer.amount, offer.currency, response.status)
            return False
        logging.info("Оффер %s прийнято.", offer.offer_id)
        activity_log.info("ПРИЙНЯТО | оффер %s | %s %s", offer.offer_id[:8], offer.amount, offer.currency)
        return True
    except PlaywrightTimeoutError:
        logging.error("Після натискання результат для оффера %s не підтверджено.", offer.offer_id)
        activity_log.info("НЕ ПІДТВЕРДЖЕНО | оффер %s | %s %s", offer.offer_id[:8], offer.amount, offer.currency)
        return False


async def run(settings: Settings, auto_accept: bool, start_signal: Path | None = None) -> None:
    processed = load_processed()
    seen_in_dry_run: set[str] = set()
    reported: set[str] = set()
    last_empty_report = 0.0
    async with async_playwright() as playwright:
        context: BrowserContext = await playwright.chromium.launch_persistent_context(
            str(ROOT / ".browser-profile"), headless=False
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(settings.offers_url, wait_until="domcontentloaded")
        logging.info("Увійдіть у свій обліковий запис у відкритому браузері. Оновлення вимкнено, доки ви не підтвердите готовність.")
        if start_signal:
            logging.info("Очікую натискання кнопки «Почати моніторинг» у вікні керування.")
            while not start_signal.exists():
                await asyncio.sleep(0.2)
            start_signal.unlink(missing_ok=True)
        else:
            await asyncio.to_thread(input, "\nПісля входу й відкриття сторінки офферів натисніть Enter тут, щоб почати моніторинг: ")
        logging.info("Моніторинг запущено.")
        activity_log.info("СТАРТ | поріг: %s UAH | авто-підтвердження: %s", settings.minimum_amount_uah, "так" if auto_accept else "ні")

        while True:
            started = asyncio.get_running_loop().time()
            try:
                if page.url != settings.offers_url:
                    await page.goto(settings.offers_url, wait_until="domcontentloaded")
                else:
                    await page.reload(wait_until="domcontentloaded")

                # The page is an Angular app; its cards often render after DOMContentLoaded.
                await page.wait_for_timeout(800)
                current_offers = await scan_offers(page, settings)
                if not current_offers:
                    now = asyncio.get_running_loop().time()
                    if now - last_empty_report >= 30:
                        activity_log.info("СКАНУВАННЯ | карток офферів не знайдено на сторінці.")
                        last_empty_report = now

                for offer in current_offers:
                    if offer.offer_id in processed:
                        continue
                    reasons: list[str] = []
                    if offer.currency != "UAH":
                        reasons.append(f"валюта {offer.currency}")
                    if offer.status not in settings.active_statuses:
                        reasons.append(f"статус {offer.status}")
                    if offer.amount < settings.minimum_amount_uah:
                        reasons.append(f"сума {offer.amount} < порога {settings.minimum_amount_uah}")
                    qualifies = (
                        offer.currency == "UAH"
                        and offer.status in settings.active_statuses
                        and offer.amount >= settings.minimum_amount_uah
                    )
                    if not qualifies:
                        if offer.offer_id not in reported:
                            logging.info("Оффер %s: пропущено (%s).", offer.offer_id[:8], "; ".join(reasons))
                            activity_log.info("ПРОПУЩЕНО | оффер %s | %s %s | %s", offer.offer_id[:8], offer.amount, offer.currency, "; ".join(reasons))
                            reported.add(offer.offer_id)
                        continue
                    logging.warning("Новий оффер: %s — %s %s (%s)", offer.offer_id, offer.amount, offer.currency, offer.status)
                    if auto_accept:
                        if await accept_offer(page, offer, settings):
                            processed.add(offer.offer_id)
                            save_processed(processed)
                    else:
                        if offer.offer_id not in seen_in_dry_run:
                            logging.warning("DRY-RUN: оффер не прийнято. Запустіть з --auto-accept лише після перевірки.")
                            activity_log.info("ПІДХОДИТЬ, АЛЕ НЕ ПРИЙНЯТО | оффер %s | %s %s | тестовий режим", offer.offer_id[:8], offer.amount, offer.currency)
                            seen_in_dry_run.add(offer.offer_id)
            except PlaywrightTimeoutError:
                logging.warning("Сторінка не встигла завантажитися; повторю через 2 секунди.")
            except Exception:
                logging.exception("Помилка циклу; продовжую моніторинг.")

            elapsed = asyncio.get_running_loop().time() - started
            await asyncio.sleep(max(0, settings.refresh_seconds - elapsed))


def configure_logging() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_DIR / "bot.log", encoding="utf-8")],
    )
    activity_log.setLevel(logging.INFO)
    activity_log.propagate = False
    activity_handler = logging.FileHandler(LOG_DIR / "activity.log", encoding="utf-8")
    activity_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    activity_log.addHandler(activity_handler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Paychain offer monitor")
    parser.add_argument("--config", type=Path, default=ROOT / "config.json")
    parser.add_argument("--auto-accept", action="store_true", help="Приймати оффери після успішного dry-run тесту")
    parser.add_argument("--minimum-amount", type=Decimal, help="Перевизначити мінімальну суму UAH із config.json")
    parser.add_argument("--start-signal", type=Path, help="Файл-сигнал запуску для вікна керування")
    args = parser.parse_args()
    configure_logging()
    try:
        settings = load_settings(args.config)
        if args.minimum_amount is not None:
            settings = replace(settings, minimum_amount_uah=args.minimum_amount)
        if settings.minimum_amount_uah < 0:
            raise ValueError("minimum_amount не може бути від’ємним.")
        if settings.refresh_seconds < 1:
            raise ValueError("refresh_seconds не може бути меншим за 1 секунду.")
        asyncio.run(run(settings, args.auto_accept, args.start_signal))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        logging.error("Конфігурація: %s", error)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
