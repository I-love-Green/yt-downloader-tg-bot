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

TELEGRAM_MAX_FILE_SIZE = 50 * 1024 * 1024

def upload_to_transfersh(file_path: str) -> str | None:
    # Simple upload to transfer.sh — returns a URL or None if an error occurs.
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
    Sends a local file via multipart upload:
    - uses types.FSInputFile to guarantee local file upload
    - falls back to document if video fails
    - returns True if sent, False if not
    """
    # Діагностика для чату: покажемо абсолютний шлях та наявність файлу
    abs_path = os.path.abspath(file_path)
    exists = os.path.exists(file_path)
    size = os.path.getsize(file_path) if exists else "N/A"
    # await message.answer(f"debug: abs_path={abs_path!r}, exists={exists}, size={size}")

    if not exists:
        await message.answer("File not found on the server.")
        return False

    try:
        # Використовуємо FSInputFile — спеціальний об'єкт для локальних файлів
        fs_file = types.FSInputFile(file_path)
        # Першочергово відправляємо як відео
        await message.answer_video(video=fs_file, caption=caption)
        return True
    except TelegramBadRequest as e:
        # Лог помилки для діагностики
        await message.answer(f"TelegramBadRequest when sending as a video: {e}")
        try:
            # Повторно створимо FSInputFile і спробуємо як документ
            fs_file = types.FSInputFile(file_path)
            await message.answer_document(document=fs_file, caption=caption)
            return True
        except Exception as e2:
            await message.answer(f"Failed to send as a document: {e2}")
            return False
    except Exception as e:
        await message.answer(f"Error sending file: {e}")
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
    Compress the video so that it approximately fits into target_size_bytes.
    Returns True if the file is successfully created and has a size <= target_size_bytes.
    """
    duration = _get_duration_seconds(input_path)
    if not duration or duration <= 0:
        return False

    # leave a small margin (5%)
    target_bits = target_size_bytes * 8 * 0.95
    audio_bps = audio_bitrate_kbps * 1000
    video_bps = (target_bits / duration) - audio_bps
    # minimum video bitrate
    if video_bps < 80_000:
        # it makes no sense to compress to such low quality
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
        # in case of decoding/encoding error
        try:
            if os.path.exists(output_path):
                os.remove(output_path)
        except Exception:
            pass
        return False

@router.message(Command("download"))
async def cmd_download(message: types.Message, state: FSMContext):
    await message.answer("Send a link to a YouTube video:")
    await state.set_state(DownloadStates.waiting_for_url)

@router.message(DownloadStates.waiting_for_url)
async def process_url(message: types.Message, state: FSMContext):
    url = message.text.strip()
    await message.answer("Downloading video...")
    
    try:
        file_path = await asyncio.to_thread(download_video, url)

        if not file_path or not os.path.exists(file_path):
            raise RuntimeError("File not found after download")

        size = os.path.getsize(file_path)
        if size > TELEGRAM_MAX_FILE_SIZE:
            await message.answer("The file is too large to send via Telegram. I'll try to compress it...")
            # target — slightly less than the limit (1 MB reserve)
            target = TELEGRAM_MAX_FILE_SIZE - (1 * 1024 * 1024)
            compressed_path = os.path.splitext(file_path)[0] + "_compressed.mp4"
            ok = await asyncio.to_thread(compress_video_to_target, file_path, compressed_path, target)
            if ok:
                csize = os.path.getsize(compressed_path)
                await message.answer(f"Compression successful, size {csize} bytes, sending...")
                sent = await send_local_file_to_user(message, compressed_path, caption="Conpleted!")
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
                # if it didn't send — fallthrough to upload
            else:
                await message.answer("Unable to compress to the desired size or error during compression.")

            # fallback: upload to an external host and provide a link
            await message.answer("I'll try to upload it to an external host...")
            link = await asyncio.to_thread(upload_to_transfersh, file_path)
            await message.answer(f"debug: returned link -> {repr(link)}")
            if not link:
                await message.answer("The external host did not return the link.")
            else:
                link = link.strip()
                parsed = urllib.parse.urlparse(link)
                if parsed.scheme in ("http", "https"):
                    try:
                        if parsed.port is not None and not (1 <= parsed.port <= 65535):
                            raise ValueError("Invalid port")
                    except ValueError:
                        await message.answer("Incorrect port in the returned URL from the host.")
                    else:
                        await message.answer(f"Here is the download link: {link}")
                else:
                    await message.answer("The returned host provided an incorrect URL (not http/https).")
        else:
            ok = await send_local_file_to_user(message, file_path, caption="Completed!")
            if not ok:
                await message.answer("Unable to send file directly. Please try again later.")

        try:
            os.remove(file_path)
        except Exception:
            pass

    except Exception as e:
        await message.answer(f"Error: {e}")

    finally:
        await state.clear()