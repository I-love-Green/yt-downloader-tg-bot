from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from services.youtube import download_best_quality as download_video
import asyncio
import os
import requests
import urllib.parse

router = Router()

class DownloadStates(StatesGroup):
    waiting_for_url = State()

TELEGRAM_MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB — змініть якщо у вас інший ліміт

def upload_to_transfersh(file_path: str) -> str | None:
    """Просте завантаження на transfer.sh — повертає URL або None при помилці."""
    url = f"https://transfer.sh/{os.path.basename(file_path)}"
    try:
        with open(file_path, "rb") as f:
            resp = requests.put(url, data=f, timeout=120)
        if resp.status_code in (200, 201):
            return resp.text.strip()
    except Exception:
        pass
    return None

@router.message(Command("download"))
async def cmd_download(message: types.Message, state: FSMContext):
    await message.answer("Надішли мені посилання на YouTube-відео:")
    await state.set_state(DownloadStates.waiting_for_url)

@router.message(DownloadStates.waiting_for_url)
async def process_url(message: types.Message, state: FSMContext):
    url = message.text.strip()
    await message.answer("Завантажую відео, зачекай...")
    
    try:
        file_path = await asyncio.to_thread(download_video, url)

        if not file_path or not os.path.exists(file_path):
            raise RuntimeError("Файл не знайдено після завантаження")

        size = os.path.getsize(file_path)
        if size > TELEGRAM_MAX_FILE_SIZE:
            await message.answer("Файл занадто великий для відправки через Telegram. Спробую завантажити на зовнішній хост...")
            link = await asyncio.to_thread(upload_to_transfersh, file_path)
            # debug/log the returned link
            await message.answer(f"debug: returned link -> {repr(link)}")

            if not link:
                await message.answer("Зовнішній хост не повернув посилання.")
            else:
                link = link.strip()
                parsed = urllib.parse.urlparse(link)
                # перевіряємо коректний протокол і порт (якщо вказаний)
                if parsed.scheme in ("http", "https"):
                    try:
                        if parsed.port is not None and not (1 <= parsed.port <= 65535):
                            raise ValueError("Invalid port")
                    except ValueError:
                        await message.answer("Невірний порт у поверненому URL від хоста.")
                    else:
                        # посилання виглядає нормально — відправляємо користувачу
                        await message.answer(f"🔗 Ось посилання на завантаження: {link}")
                else:
                    await message.answer("Повернений хост віддав некоректний URL (не http/https).")

        else:
            # Відправка як відео (передаємо шлях до файлу)
            await message.answer_video(video=file_path, caption="Готово!")

        try:
            os.remove(file_path)
        except Exception:
            pass

    except Exception as e:
        await message.answer(f"Помилка: {e}")

    finally:
        await state.clear()
