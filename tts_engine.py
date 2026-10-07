import asyncio
import logging
import os
import socket
import tempfile
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import aiohttp
import edge_tts
from mutagen.mp3 import MP3

logger = logging.getLogger(__name__)

TTS_DIR = Path(tempfile.gettempdir()) / "xiaoai_tts"
TTS_DIR.mkdir(exist_ok=True)

TTS_VOICE = "zh-CN-XiaoxiaoNeural"

_server_started = False
_server_port = 0
_server_ip = ""


def _get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class _QuietHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(TTS_DIR), **kwargs)

    def log_message(self, format, *args):
        pass


def _start_server():
    global _server_started, _server_port, _server_ip
    if _server_started:
        return

    server = HTTPServer(("0.0.0.0", 0), _QuietHandler)
    _server_port = server.server_address[1]
    _server_ip = _get_local_ip()

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _server_started = True
    logger.info(f"TTS 文件服务已启动: http://{_server_ip}:{_server_port}")


async def generate_tts(text: str, retries: int = 3) -> tuple[str, float] | None:
    """用 edge-tts 生成 MP3 文件，返回 (URL, 时长秒数)"""
    _start_server()

    filename = f"tts_{hash(text) & 0xFFFFFFFF}.mp3"
    filepath = TTS_DIR / filename
    duration_file = filepath.with_suffix(".duration")

    if filepath.exists() and duration_file.exists():
        try:
            duration = float(duration_file.read_text())
            url = f"http://{_server_ip}:{_server_port}/{filename}"
            return url, duration
        except Exception:
            pass

    if not filepath.exists():
        ipv4_connector = aiohttp.TCPConnector(family=socket.AF_INET)
        for attempt in range(retries):
            try:
                communicate = edge_tts.Communicate(
                    text, TTS_VOICE, connector=ipv4_connector,
                )
                await communicate.save(str(filepath))
                logger.info(f"TTS 音频已生成: {filepath.name} ({filepath.stat().st_size} bytes)")
                break
            except Exception as e:
                logger.warning(f"edge-tts 生成失败 (尝试 {attempt+1}/{retries}): {e}")
                if attempt < retries - 1:
                    await asyncio.sleep(1)
                    ipv4_connector = aiohttp.TCPConnector(family=socket.AF_INET)
                else:
                    logger.error(f"edge-tts 生成最终失败")
                    return None

    try:
        audio = MP3(filepath)
        duration = audio.info.length
        duration_file.write_text(f"{duration:.2f}")
        logger.info(f"MP3 时长: {duration:.1f}s")
    except Exception as e:
        logger.warning(f"读取 MP3 时长失败: {e}")
        duration = 0

    url = f"http://{_server_ip}:{_server_port}/{filename}"
    return url, duration


_silence_url: str | None = None


async def get_silence_url() -> str | None:
    """生成一段静音 MP3 的 URL，用于覆盖循环播放"""
    global _silence_url
    if _silence_url:
        return _silence_url

    silence_path = TTS_DIR / "silence.mp3"
    if not silence_path.exists():
        # 生成有效的静音 MP3 (MPEG1 Layer3, 48kbps, 24kHz, mono)
        # 每帧 144 字节，约 72ms，生成约 2 秒静音
        frame_header = bytes([0xFF, 0xFB, 0x60, 0xC4])
        frame_data = frame_header + b'\x00' * 140
        try:
            with open(silence_path, 'wb') as f:
                for _ in range(28):
                    f.write(frame_data)
            logger.info(f"静音文件已生成: {silence_path.stat().st_size} bytes")
        except Exception as e:
            logger.error(f"静音文件生成失败: {e}")
            return None

    _start_server()
    _silence_url = f"http://{_server_ip}:{_server_port}/silence.mp3"
    return _silence_url
