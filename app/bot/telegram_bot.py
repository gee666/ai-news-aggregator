import asyncio
import logging
from typing import Any

from app.bot import commands
from app.bot.formatting import format_digest, format_sources, format_status, format_summary, split_telegram_html
from app.config import get_settings
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    return commands.is_configured()


async def send_digest_to_owner() -> bool:
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_owner_chat_id:
        return False
    try:
        from aiogram import Bot
        from aiogram.enums import ParseMode
    except ImportError:
        logger.warning("aiogram is not installed; cannot send digest")
        return False

    bot = Bot(settings.telegram_bot_token)
    try:
        for chunk in split_telegram_html(format_digest(await commands.digest())):
            await bot.send_message(
                settings.telegram_owner_chat_id,
                chunk,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
    finally:
        await bot.session.close()
    return True


async def _answer(message: Any, text: str) -> None:
    for chunk in split_telegram_html(text):
        await message.answer(chunk, parse_mode="HTML", disable_web_page_preview=True)


async def run_polling() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    if not settings.telegram_bot_token:
        logger.warning("TELEGRAM_BOT_TOKEN is not set; bot is idle")
        await asyncio.Event().wait()
        return
    try:
        from aiogram import Bot, Dispatcher, F
        from aiogram.filters import Command, CommandObject
        from aiogram.types import Message
    except ImportError as exc:
        raise SystemExit("Install aiogram or project 'bot' extra to run the Telegram bot") from exc

    bot = Bot(settings.telegram_bot_token)
    dispatcher = Dispatcher()

    async def owner_only(message: Message) -> bool:
        if commands.is_owner(message.chat.id):
            return True
        logger.warning("ignored non-owner chat_id=%s", message.chat.id)
        await message.answer("Unauthorized")
        return False

    @dispatcher.message(Command("start"))
    async def start(message: Message) -> None:
        if not await owner_only(message):
            return
        await _answer(
            message,
            "News Bot AI ready. Commands: /latest /digest /search <query> /submit <url or text> /sources /status",
        )

    @dispatcher.message(Command("latest"))
    async def latest(message: Message) -> None:
        if not await owner_only(message):
            return
        rows = await commands.latest()
        await _answer(message, "\n\n".join(format_summary(row) for row in rows) or "No summaries yet.")

    @dispatcher.message(Command("digest"))
    async def digest(message: Message) -> None:
        if not await owner_only(message):
            return
        await _answer(message, format_digest(await commands.digest()))

    @dispatcher.message(Command("search"))
    async def search(message: Message, command: CommandObject) -> None:
        if not await owner_only(message):
            return
        query = (command.args or "").strip()
        if not query:
            await _answer(message, "Usage: /search query")
            return
        results = await commands.search(query)
        summaries = results["summaries"]
        if summaries:
            await _answer(message, "\n\n".join(format_summary(row) for row in summaries))
        else:
            await _answer(message, "No matches.")

    @dispatcher.message(Command("submit"))
    async def submit(message: Message, command: CommandObject) -> None:
        if not await owner_only(message):
            return
        text = (command.args or "").strip()
        if not text:
            await _answer(message, "Usage: /submit <url or text>")
            return
        raw_item_id = await commands.submit(text)
        await _answer(message, f"Submitted raw item {raw_item_id}")

    @dispatcher.message(Command("sources"))
    async def sources(message: Message) -> None:
        if not await owner_only(message):
            return
        await _answer(message, format_sources(await commands.sources()))

    @dispatcher.message(Command("status"))
    async def status(message: Message) -> None:
        if not await owner_only(message):
            return
        await _answer(message, format_status(await commands.status()))

    @dispatcher.message(F.text)
    async def unknown(message: Message) -> None:
        if await owner_only(message):
            await _answer(message, "Unknown command. Try /start")

    logger.info("Telegram bot polling started")
    await dispatcher.start_polling(bot)


def main() -> None:
    asyncio.run(run_polling())


if __name__ == "__main__":
    main()
