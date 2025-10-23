from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from services.youtube import download_best_quality as download_video
import asyncio
import os
import requests
import urllib.parse
import subprocess
import math
from aiogram.exceptions import TelegramBadRequest

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

async def send_local_file_to_user(message: types.Message, file_path: str, caption: str = ""):
    """
    Надсилає локальний файл через multipart upload:
    - використовує types.FSInputFile для гарантованої відправки локального файлу
    - робить fallback на document, якщо video не пройшло
    - повертає True якщо відправлено, False якщо ні
    """
    # Діагностика для чату: покажемо абсолютний шлях та наявність файлу
    abs_path = os.path.abspath(file_path)
    exists = os.path.exists(file_path)
    size = os.path.getsize(file_path) if exists else "N/A"
    await message.answer(f"debug: abs_path={abs_path!r}, exists={exists}, size={size}")

    if not exists:
        await message.answer("Файл не знайдено на сервері (перевірте шлях і права доступу).")
        return False

    try:
        # Використовуємо FSInputFile — спеціальний об'єкт для локальних файлів
        fs_file = types.FSInputFile(file_path)
        # Першочергово відправляємо як відео
        await message.answer_video(video=fs_file, caption=caption)
        return True
    except TelegramBadRequest as e:
        # Лог помилки для діагностики
        await message.answer(f"TelegramBadRequest при відправці як відео: {e}")
        try:
            # Повторно створимо FSInputFile і спробуємо як документ
            fs_file = types.FSInputFile(file_path)
            await message.answer_document(document=fs_file, caption=caption)
            return True
        except Exception as e2:
            await message.answer(f"Не вдалося відправити як документ: {e2}")
            return False
    except Exception as e:
        await message.answer(f"Помилка при відправці файлу: {e}")
        return False

def _get_duration_seconds(path: str) -> float | None:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, check=True
        )
        return float(out.stdout.strip())
    except Exception:
        return None

def compress_video_to_target(input_path: str, output_path: str, target_size_bytes: int, audio_bitrate_kbps: int = 128) -> bool:
    """
    Стиснути відео так, щоб приблизно вміститися в target_size_bytes.
    Повертає True якщо файл успішно створений і має розмір <= target_size_bytes.
    """
    duration = _get_duration_seconds(input_path)
    if not duration or duration <= 0:
        return False

    # залишаємо невеликий запас (5%)
    target_bits = target_size_bytes * 8 * 0.95
    audio_bps = audio_bitrate_kbps * 1000
    video_bps = (target_bits / duration) - audio_bps
    # мінімальний бітрейт відео
    if video_bps < 80_000:
        # не має сенсу стиснути до такої низької якості
        return False

    video_k = max(100, int(video_bps / 1000))
    audio_k = audio_bitrate_kbps

    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-c:v", "libx264",
        "-b:v", f"{video_k}k",
        "-maxrate", f"{video_k}k",
        "-bufsize", f"{max(2*video_k, video_k)}k",
        "-preset", "fast",
        "-c:a", "aac",
        "-b:a", f"{audio_k}k",
        "-movflags", "+faststart",
        output_path
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(output_path) and os.path.getsize(output_path) <= target_size_bytes:
            return True
        return False
    except Exception:
        # на випадок помилки декодування/кодування
        try:
            if os.path.exists(output_path):
                os.remove(output_path)
        except Exception:
            pass
        return False

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
            await message.answer("Файл занадто великий для відправки через Telegram. Пробую стиснути...")
            # ціль — трохи менше ліміту (1 MB запас)
            target = TELEGRAM_MAX_FILE_SIZE - (1 * 1024 * 1024)
            compressed_path = os.path.splitext(file_path)[0] + "_compressed.mp4"
            ok = await asyncio.to_thread(compress_video_to_target, file_path, compressed_path, target)
            if ok:
                csize = os.path.getsize(compressed_path)
                await message.answer(f"Стиснення успішне, розмір {csize} байт, відправляю...")
                sent = await send_local_file_to_user(message, compressed_path, caption="Готово (стискання)")
                try:
                    os.remove(compressed_path)
                except Exception:
                    pass
                if sent:
                    try:
                        os.remove(file_path)
                    except Exception:
                        pass
                    await state.clear()
                    return
                # якщо не відправилось — fallthrough to upload
            else:
                await message.answer("Не вдалося стиснути до потрібного розміру або помилка при компресії.")

            # fallback: завантажити на зовнішній хост і віддати лінк
            await message.answer("Спробую завантажити на зовнішній хост...")
            link = await asyncio.to_thread(upload_to_transfersh, file_path)
            await message.answer(f"debug: returned link -> {repr(link)}")
            if not link:
                await message.answer("Зовнішній хост не повернув посилання.")
            else:
                link = link.strip()
                parsed = urllib.parse.urlparse(link)
                if parsed.scheme in ("http", "https"):
                    try:
                        if parsed.port is not None and not (1 <= parsed.port <= 65535):
                            raise ValueError("Invalid port")
                    except ValueError:
                        await message.answer("Невірний порт у поверненому URL від хоста.")
                    else:
                        await message.answer(f"🔗 Ось посилання на завантаження: {link}")
                else:
                    await message.answer("Повернений хост віддав некоректний URL (не http/https).")
        else:
            ok = await send_local_file_to_user(message, file_path, caption="Готово!")
            if not ok:
                await message.answer("Не вдалося відправити файл напряму. Спробуйте пізніше або завантажте вручну.")

        try:
            os.remove(file_path)
        except Exception:
            pass

    except Exception as e:
        await message.answer(f"Помилка: {e}")

    finally:
        await state.clear()