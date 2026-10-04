# main.py
# Точка входа: запускает бота, регистрирует хендлеры и фоновую задачу.

import asyncio
import logging
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from config import BOT_TOKEN, CHANNEL_ID, LOG_PATH, CHECK_INTERVAL
import database as db


# ---------- Логирование ----------
# Пишем и в файл, и в консоль, чтобы видеть, что происходит в реальном времени.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# ---------- Инициализация ----------
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


# ---------- FSM: состояния диалога /add ----------
class AddPost(StatesGroup):
    waiting_text = State()       # ждём текст
    waiting_image = State()      # ждём ссылку на картинку или пропуск
    waiting_time = State()       # ждём дату/время


# ---------- /start ----------
@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "👋 Привет! Я бот-планировщик постов.\n\n"
        "Доступные команды:\n"
        "/add — добавить новый пост\n"
        "/list — показать запланированные посты\n"
        "/delete [id] — удалить пост по ID\n"
    )


# ---------- /add ----------
@dp.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext):
    await state.set_state(AddPost.waiting_text)
    await message.answer("✏️ Отправь текст поста:")


@dp.message(AddPost.waiting_text)
async def process_text(message: Message, state: FSMContext):
    await state.update_data(text=message.text)
    await state.set_state(AddPost.waiting_image)
    await message.answer(
        "🖼 Отправь ссылку на картинку (URL).\n"
        "Если картинка не нужна — напиши <b>нет</b>."
    )


@dp.message(AddPost.waiting_image)
async def process_image(message: Message, state: FSMContext):
    image = None if message.text.strip().lower() in ("нет", "-", "no") else message.text.strip()
    await state.update_data(image_url=image)
    await state.set_state(AddPost.waiting_time)
    await message.answer(
        "🕒 Укажи дату и время публикации в формате:\n"
        "<code>ЧЧ:ММ ДД.ММ.ГГГГ</code>\n"
        "Например: <code>14:30 25.12.2025</code>"
    )


@dp.message(AddPost.waiting_time)
async def process_time(message: Message, state: FSMContext):
    try:
        # Парсим дату строго по формату
        publish_time = datetime.strptime(message.text.strip(), "%H:%M %d.%m.%Y")
    except ValueError:
        await message.answer(
            "❌ Неверный формат. Попробуй ещё раз: <code>ЧЧ:ММ ДД.ММ.ГГГГ</code>"
        )
        return

    data = await state.get_data()
    post_id = await db.add_post(
        text=data["text"],
        image_url=data.get("image_url"),
        publish_time=publish_time,
    )
    await state.clear()
    await message.answer(
        f"✅ Пост сохранён! ID: <b>{post_id}</b>\n"
        f"Публикация: <b>{publish_time.strftime('%H:%M %d.%m.%Y')}</b>"
    )
    logger.info(f"Добавлен пост ID={post_id} на {publish_time}")


# ---------- /list ----------
@dp.message(Command("list"))
async def cmd_list(message: Message):
    posts = await db.get_pending_posts()
    if not posts:
        await message.answer("📭 Нет запланированных постов.")
        return

    lines = ["📋 <b>Запланированные посты:</b>\n"]
    for post_id, text, image_url, publish_time in posts:
        short_text = (text[:50] + "...") if len(text) > 50 else text
        img = "🖼" if image_url else "—"
        lines.append(
            f"<b>ID {post_id}</b> | {publish_time} | {img}\n"
            f"<i>{short_text}</i>\n"
        )
    await message.answer("\n".join(lines))


# ---------- /delete ----------
@dp.message(Command("delete"))
async def cmd_delete(message: Message):
    # Разбиваем команду: /delete 5 -> ["/delete", "5"]
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("⚠️ Использование: <code>/delete ID</code>")
        return

    post_id = int(parts[1])
    deleted = await db.delete_post(post_id)
    if deleted:
        await message.answer(f"🗑 Пост ID {post_id} удалён.")
        logger.info(f"Удалён пост ID={post_id}")
    else:
        await message.answer(f"❌ Пост с ID {post_id} не найден.")


# ---------- Фоновая задача публикации ----------
async def scheduler_loop():
    """Каждые CHECK_INTERVAL секунд проверяем базу и публикуем то, что пора."""
    logger.info("Планировщик запущен.")
    while True:
        try:
            now = datetime.now()
            due_posts = await db.get_due_posts(now)

            for post_id, text, image_url in due_posts:
                try:
                    if image_url:
                        # Отправка фото с подписью
                        await bot.send_photo(
                            chat_id=CHANNEL_ID,
                            photo=image_url,
                            caption=text,
                        )
                    else:
                        # Отправка только текста
                        await bot.send_message(chat_id=CHANNEL_ID, text=text)

                    await db.mark_published(post_id)
                    logger.info(f"Опубликован пост ID={post_id}")

                except Exception as e:
                    # Ошибка с одним постом не должна ломать весь цикл
                    logger.error(f"Ошибка публикации поста ID={post_id}: {e}")

        except Exception as e:
            logger.error(f"Ошибка в планировщике: {e}")

        await asyncio.sleep(CHECK_INTERVAL)


# ---------- Точка входа ----------
async def main():
    await db.init_db()
    # Запускаем планировщик параллельно с polling'ом
    asyncio.create_task(scheduler_loop())
    logger.info("Бот запущен и слушает сообщения.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
