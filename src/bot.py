from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime
from html import escape
import logging
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .avito_api import AvitoClient, IncomingMessage
from .config import Config
from .storage import FileStorage, User


MOSCOW_TZ = ZoneInfo("Europe/Moscow")
logger = logging.getLogger(__name__)


def build_dispatcher(storage: FileStorage) -> Dispatcher:
    router = Router()

    @router.message(Command("start"))
    async def start(message: Message) -> None:
        telegram_id = message.from_user.id
        existing = storage.get_user(telegram_id)
        if existing:
            await message.answer("Доступ уже есть. Я пришлю сюда новые непрочитанные сообщения Авито.")
            return

        full_name = message.from_user.full_name if message.from_user else ""
        username = message.from_user.username if message.from_user and message.from_user.username else ""

        if not storage.has_users():
            storage.add_user(telegram_id, "admin", full_name, username)
            await message.answer(
                "Вы добавлены как главный админ. Команды: /invite для кода, /users для управления доступом."
            )
            return

        await message.answer("Введите код приглашения.")

    @router.message(Command("invite"))
    async def invite(message: Message) -> None:
        user = _current_user(message, storage)
        if not user:
            await message.answer("Введите код приглашения.")
            return
        if not user.is_admin:
            await message.answer("Эта команда доступна только главному админу.")
            return
        code = storage.create_invite()
        await message.answer(f"Одноразовый код приглашения:\n<code>{code}</code>", parse_mode="HTML")

    @router.message(Command("users"))
    async def users(message: Message) -> None:
        user = _current_user(message, storage)
        if not user:
            await message.answer("Введите код приглашения.")
            return
        if not user.is_admin:
            await message.answer("Эта команда доступна только главному админу.")
            return

        registered = storage.users()
        if not registered:
            await message.answer("Список доступа пуст.")
            return

        buttons = []
        for registered_user in registered:
            if registered_user.telegram_id == user.telegram_id:
                continue
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"Удалить {registered_user.name or registered_user.telegram_id}",
                        callback_data=f"revoke:{registered_user.telegram_id}",
                    )
                ]
            )

        text = "Доступ есть у:\n" + "\n".join(
            f"- {'админ' if item.is_admin else 'сотрудник'}: {escape(item.label)}"
            for item in registered
        )
        if not buttons:
            await message.answer(text, parse_mode="HTML")
            return
        await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")

    @router.callback_query(F.data.startswith("revoke:"))
    async def revoke(callback: CallbackQuery) -> None:
        user = storage.get_user(callback.from_user.id)
        if not user or not user.is_admin:
            await callback.answer("Нет доступа", show_alert=True)
            return

        target_id = int(callback.data.split(":", 1)[1])
        if target_id == user.telegram_id:
            await callback.answer("Нельзя удалить главного админа", show_alert=True)
            return

        removed = storage.remove_user(target_id)
        if not removed:
            await callback.answer("Пользователь уже удален", show_alert=True)
            return

        await callback.answer("Доступ отозван")
        await callback.message.edit_text(f"Доступ отозван: {escape(removed.label)}", parse_mode="HTML")

    @router.message()
    async def plain_text(message: Message) -> None:
        telegram_id = message.from_user.id
        existing = storage.get_user(telegram_id)
        if existing:
            await message.answer("Доступ активен. Админ-команды доступны только главному админу.")
            return

        text = (message.text or "").strip().upper()
        if not text:
            await message.answer("Введите код приглашения.")
            return

        if not storage.consume_invite(text):
            await message.answer("Неверный код приглашения. Введите код приглашения.")
            return

        full_name = message.from_user.full_name if message.from_user else ""
        username = message.from_user.username if message.from_user and message.from_user.username else ""
        storage.add_user(telegram_id, "employee", full_name, username)
        await message.answer("Готово, доступ выдан. Теперь вам будут приходить уведомления Авито.")

    dp = Dispatcher()
    dp.include_router(router)
    return dp


async def run_bot(config: Config) -> None:
    storage = FileStorage(config.data_dir)
    avito = AvitoClient(
        config.avito_client_id,
        config.avito_client_secret,
        config.avito_user_id,
        log_responses=config.avito_log_responses,
        debug_fetch_all_chats=config.avito_debug_fetch_all_chats,
    )
    bot = Bot(config.telegram_bot_token)
    dispatcher = build_dispatcher(storage)
    poller = asyncio.create_task(poll_avito(bot, storage, avito, config))

    try:
        await dispatcher.start_polling(bot)
    finally:
        poller.cancel()
        await avito.close()
        await bot.session.close()


async def poll_avito(bot: Bot, storage: FileStorage, avito: AvitoClient, config: Config) -> None:
    while True:
        try:
            processed = storage.processed_messages()
            poll_result = await avito.unread_incoming_messages(processed)
            logger.info(
                "Avito check: chats=%s, unread_chats=%s, checked_message_chats=%s, new_messages=%s, recipients=%s",
                poll_result.total_chats,
                poll_result.unread_chats,
                poll_result.checked_message_chats,
                len(poll_result.new_messages),
                len(storage.recipients()),
            )
            if poll_result.new_messages:
                await asyncio.sleep(config.group_window_seconds)
                processed = storage.processed_messages()
                fresh = [message for message in poll_result.new_messages if message.id not in processed]
                if fresh:
                    recipients = storage.recipients()
                    await send_notifications(bot, recipients, fresh)
                    storage.mark_processed([message.id for message in fresh])
                    logger.info(
                        "Avito notifications sent: messages=%s, recipients=%s",
                        len(fresh),
                        len(recipients),
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Avito polling failed")
        await asyncio.sleep(config.poll_interval_seconds)


async def send_notifications(bot: Bot, recipients: list[int], messages: list[IncomingMessage]) -> None:
    if not recipients:
        return

    for text in _format_notifications(messages):
        for recipient in recipients:
            try:
                await bot.send_message(recipient, text, parse_mode="HTML")
            except Exception:
                logger.exception("Failed to send notification to %s", recipient)


def _format_notifications(messages: list[IncomingMessage]) -> list[str]:
    grouped: dict[str, list[IncomingMessage]] = defaultdict(list)
    for message in messages:
        grouped[message.chat_id].append(message)

    result = []
    for chat_messages in grouped.values():
        first = chat_messages[0]
        lines = [
            "<b>Новое сообщение Авито</b>",
            f"Клиент: {escape(first.author_name)}",
            f"Время: {_format_time(first.created_at)}",
            "Сообщение:",
        ]
        for message in chat_messages:
            prefix = ""
            if len(chat_messages) > 1:
                prefix = f"[{_format_time(message.created_at)}] "
            lines.append(prefix + escape(message.text))
        result.append("\n".join(lines))
    return result


def _format_time(value: datetime) -> str:
    return value.astimezone(MOSCOW_TZ).strftime("%d.%m.%Y %H:%M")


def _current_user(message: Message, storage: FileStorage) -> User | None:
    if not message.from_user:
        return None
    return storage.get_user(message.from_user.id)
