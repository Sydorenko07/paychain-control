from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import time
from hashlib import sha256
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path

from playwright.async_api import Locator, Page, TimeoutError as PlaywrightTimeoutError, async_playwright

ROOT = Path(__file__).parent
PROFILE_DIR = ROOT / ".browser-profile"
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
    cleaned = raw.replace("\u00a0", " ").replace(" ", "")
    cleaned = re.sub(r"[^0-9,.-]", "", cleaned).replace(",", ".")
    if cleaned.count(".") > 1:
        raise ValueError(f"Не вдалося розібрати суму: {raw!r}")
    try:
        return Decimal(cleaned)
    except InvalidOperation as error:
        raise ValueError(f"Не вдалося розібрати суму: {raw!r}") from error


def normalize_currency(raw: str) -> str:
    """Extract the currency code from cells such as ``UAH 1016.50``."""
    match = re.search(r"\b(UAH|USD|EUR|USDT)\b", raw.upper())
    return match.group(1) if match else raw.strip().upper()


def load_processed() -> set[str]:
    if not PROCESSED_FILE.exists():
        return set()
    try:
        data = json.loads(PROCESSED_FILE.read_text(encoding="utf-8"))
        return set(data)
    except (OSError, json.JSONDecodeError):
        return set()


def save_processed(processed: set[str]) -> None:
    PROCESSED_FILE.write_text(json.dumps(sorted(processed), indent=2), encoding="utf-8")


async def text_in(locator: Locator, selector: str) -> str:
    return await locator.locator(selector).first.inner_text()


async def verify_amount_twice(page: Page, offer: Offer, settings: Settings) -> Decimal | None:
    """Зчитує суму двічі з невеликою затримкою. Повертає суму, якщо вона не змінилася."""
    try:
        await page.wait_for_timeout(100)
        second_amount = parse_amount(await text_in(offer.element, settings.amount_selector))
    except (PlaywrightTimeoutError, ValueError):
        return None
    if second_amount != offer.amount:
        return None
    return second_amount


async def accept_offer_with_double_click(page: Page, offer: Offer, settings: Settings) -> bool:
    """
    Подвійний швидкий клік по кнопці всередині рядка офера.
    УВАГА: два кліки можуть створити два запити до API – використовуйте на свій ризик.
    """
    try:
        # Відкриваємо меню дій, якщо потрібно
        if settings.action_menu_button_selector:
            await offer.element.locator(settings.action_menu_button_selector).first.click(timeout=5_000)

        # Шукаємо кнопку тільки в межах цього офера
        accept_button = offer.element.locator(settings.accept_button_selector).first

        # Перший клік
        await accept_button.click(timeout=5_000)

        # Дуже коротка пауза (50 мс) – щоб кліки були майже одночасними
        await page.wait_for_timeout(50)

        # Другий клік (для надійності, але це може спричинити дублювання)
        await accept_button.click(timeout=5_000)

        # Невелика пауза, щоб API обробило запити
        await page.wait_for_timeout(500)

        # Перевіряємо, чи офер зник або змінив статус
        try:
            if settings.status_selector:
                new_status = await text_in(offer.element, settings.status_selector)
                if new_status.casefold() not in settings.active_statuses:
                    activity_log.info("Офер %s змінив статус на %s – прийнято.", offer.offer_id[:8], new_status)
                    return True
        except Exception:
            # Якщо елемент зник, теж вважаємо успіх
            if await offer.element.count() == 0:
                activity_log.info("Офер %s зник після кліків – прийнято.", offer.offer_id[:8])
                return True

        # Якщо офер залишився активним – можливо, кліки не спрацювали
        activity_log.warning("Офер %s залишився активним після подвійного кліку.", offer.offer_id[:8])
        return False

    except PlaywrightTimeoutError:
        logging.warning("Таймаут під час кліку на офер %s", offer.offer_id[:8])
        return False
    except Exception as e:
        logging.error("Помилка при прийнятті офера %s: %s", offer.offer_id[:8], e)
        return False


async def run(settings: Settings, auto_accept: bool, start_signal: Path | None, minimized: bool) -> None:
    processed = load_processed()
    reported = set()
    seen_in_dry_run = set()

    async with async_playwright() as p:
        # A persistent profile writes cookies/session data while the browser is
        # running. Stopping the monitor therefore does not log the user out;
        # the profile is cleared only by an explicit local reset action.
        launch_args = ["--start-minimized"] if minimized else []
        context = await p.chromium.launch_persistent_context(
            str(PROFILE_DIR), headless=False, args=launch_args
        )
        page = await context.new_page()
        await page.goto(settings.offers_url)

        if start_signal:
            while not start_signal.exists():
                await asyncio.sleep(0.5)

        while True:
            iteration_start = time.monotonic()

            try:
                if page.is_closed():
                    logging.warning("Сторінка закрита, перезапускаємо...")
                    break

                await page.reload(timeout=10_000)
                await page.wait_for_load_state("load")

                offer_elements = await page.locator(settings.offer_selector).all()
                activity_log.info("СКАНУВАННЯ | знайдено рядків: %d", len(offer_elements))
                current_offers = []

                for element in offer_elements:
                    try:
                        if settings.offer_id_attribute:
                            offer_id = await element.get_attribute(settings.offer_id_attribute)
                        else:
                            text = await element.inner_text()
                            offer_id = sha256(text.encode()).hexdigest()

                        amount_text = await text_in(element, settings.amount_selector)
                        amount = parse_amount(amount_text)
                        currency = normalize_currency(await text_in(element, settings.currency_selector))

                        if settings.status_selector:
                            status = (await text_in(element, settings.status_selector)).strip().casefold()
                        else:
                            status = "active"

                        current_offers.append(Offer(
                            offer_id=offer_id,
                            amount=amount,
                            currency=currency,
                            status=status,
                            element=element
                        ))
                    except Exception:
                        continue

                for offer in current_offers:
                    if offer.offer_id in processed:
                        continue

                    # ПОДВІЙНА ПЕРЕВІРКА СУМИ
                    verified_amount = await verify_amount_twice(page, offer, settings)
                    if verified_amount is None:
                        activity_log.info("ПРОПУЩЕНО | оффер %s | сума змінилася або не прочитана", offer.offer_id[:8])
                        continue

                    offer = replace(offer, amount=verified_amount)
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

                    logging.warning("НОВИЙ ОФФЕР: %s — %s %s (%s)", offer.offer_id[:8], offer.amount, offer.currency, offer.status)

                    if auto_accept:
                        # ПРИЙНЯТТЯ З ПОДВІЙНИМ КЛІКОМ
                        if await accept_offer_with_double_click(page, offer, settings):
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

            elapsed = time.monotonic() - iteration_start
            sleep_time = max(0, settings.refresh_seconds - elapsed)
            await asyncio.sleep(sleep_time)


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
    parser.add_argument("--refresh-seconds", type=float, help="Інтервал оновлення сторінки в секундах")
    parser.add_argument("--start-signal", type=Path, help="Файл-сигнал запуску для вікна керування")
    parser.add_argument("--minimized", action="store_true", help="Запустити браузер мінімізованим")
    args = parser.parse_args()
    configure_logging()
    try:
        settings = load_settings(args.config)
        if args.minimum_amount is not None:
            settings = replace(settings, minimum_amount_uah=args.minimum_amount)
        if args.refresh_seconds is not None:
            settings = replace(settings, refresh_seconds=args.refresh_seconds)
        if settings.minimum_amount_uah < 0:
            raise ValueError("minimum_amount не може бути від'ємним.")
        if settings.refresh_seconds < 1:
            raise ValueError("refresh_seconds не може бути меншим за 1 секунду.")
        asyncio.run(run(settings, args.auto_accept, args.start_signal, args.minimized))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        logging.error("Конфігурація: %s", error)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
