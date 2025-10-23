from pytubefix import YouTube
import os
import subprocess

def download_best_quality(url):
    try:
        yt = YouTube(url)
        video_stream = yt.streams.filter(adaptive=True, file_extension='mp4', type='video').order_by('resolution').desc().first()
        audio_stream = yt.streams.filter(adaptive=True, file_extension='mp4', type='audio').order_by('abr').desc().first()
        video_file = video_stream.download(filename="temp_video.mp4")
        audio_file = audio_stream.download(filename="temp_audio.mp4")
        output_file = yt.title.replace(" ", "_") + ".mp4"
        subprocess.run([
            "ffmpeg", "-y",
            "-i", video_file,
            "-i", audio_file,
            "-c", "copy",
            output_file
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        os.remove(video_file)
        os.remove(audio_file)
        # ensure downloads folder exists and move merged file there
        os.makedirs("downloads", exist_ok=True)
        dest_path = os.path.join("downloads", output_file)
        os.replace(output_file, dest_path)
        return dest_path
    except Exception as e:
        # не ховати помилку — пробросимо її щоб хендлер міг повідомити користувача
        raise RuntimeError(f"youtube download error: {e}") from e