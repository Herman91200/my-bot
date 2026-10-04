# database.py
# Модуль для работы с SQLite через aiosqlite.
# Все функции асинхронные — их нужно вызывать через await.

import aiosqlite
from datetime import datetime
from config import DB_PATH


async def init_db() -> None:
    """Создаёт таблицу posts, если её ещё нет."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                text         TEXT    NOT NULL,
                image_url    TEXT,
                publish_time TIMESTAMP NOT NULL,
                status       INTEGER NOT NULL DEFAULT 0
            )
        """)
        await db.commit()


async def add_post(text: str, image_url: str | None, publish_time: datetime) -> int:
    """Добавляет новый пост. Возвращает его ID."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO posts (text, image_url, publish_time, status) VALUES (?, ?, ?, 0)",
            (text, image_url, publish_time.strftime("%Y-%m-%d %H:%M:%S"))
        )
        await db.commit()
        return cursor.lastrowid


async def get_pending_posts() -> list[tuple]:
    """Возвращает список постов со статусом 0 (ожидают публикации)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, text, image_url, publish_time FROM posts WHERE status = 0 ORDER BY publish_time"
        )
        return await cursor.fetchall()


async def get_due_posts(now: datetime) -> list[tuple]:
    """Возвращает посты, у которых время публикации уже наступило и статус = 0."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT id, text, image_url FROM posts "
            "WHERE status = 0 AND publish_time <= ?",
            (now.strftime("%Y-%m-%d %H:%M:%S"),)
        )
        return await cursor.fetchall()


async def mark_published(post_id: int) -> None:
    """Помечает пост как опубликованный (status = 1)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE posts SET status = 1 WHERE id = ?", (post_id,))
        await db.commit()


async def delete_post(post_id: int) -> bool:
    """Удаляет пост по ID. Возвращает True, если запись была найдена."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        await db.commit()
        return cursor.rowcount > 0
