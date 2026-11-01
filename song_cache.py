"""点过的歌本地缓存：命中后跳过搜索和下载，直接切片播放"""
import hashlib
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).with_name("song_cache")
INDEX = CACHE_DIR / "index.json"
MAX_AGE = 7 * 24 * 3600
MAX_BYTES = 400 * 1024 * 1024


def _load() -> dict:
    try:
        return json.loads(INDEX.read_text("utf-8"))
    except Exception:
        return {}


def _save(index: dict):
    try:
        CACHE_DIR.mkdir(exist_ok=True)
        INDEX.write_text(json.dumps(index, ensure_ascii=False), "utf-8")
    except Exception as e:
        logger.debug(f"写缓存索引失败: {e}")


def _key(text: str) -> str:
    return "".join(text.lower().split())


def lookup(keyword: str) -> dict | None:
    """命中返回 {path, name, artist}，过期或文件缺失返回 None"""
    item = _load().get(_key(keyword))
    if not item:
        return None
    path = CACHE_DIR / item.get("file", "")
    if not path.exists() or time.time() - item.get("ts", 0) > MAX_AGE:
        return None
    path.touch()
    return {"path": path, "name": item.get("name", ""), "artist": item.get("artist", "")}


def put(keyword: str, name: str, artist: str, data: bytes):
    if len(data) < 1024 * 1024:
        return
    CACHE_DIR.mkdir(exist_ok=True)
    digest = hashlib.sha1(f"{name}|{artist}".encode()).hexdigest()[:16]
    filename = f"{digest}.mp3"
    try:
        (CACHE_DIR / filename).write_bytes(data)
    except OSError as e:
        logger.debug(f"写缓存文件失败: {e}")
        return
    index = _load()
    index[_key(keyword)] = {
        "file": filename,
        "name": name,
        "artist": artist,
        "ts": time.time(),
    }
    _save(index)
    trim()


def trim():
    """超出容量时按最久未使用删除"""
    files = sorted(CACHE_DIR.glob("*.mp3"), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in files)
    if total <= MAX_BYTES:
        return
    index = _load()
    changed = False
    while files and total > MAX_BYTES:
        old = files.pop(0)
        total -= old.stat().st_size
        try:
            old.unlink()
        except OSError:
            pass
        for key, item in list(index.items()):
            if item.get("file") == old.name:
                index.pop(key)
                changed = True
    if changed:
        _save(index)
