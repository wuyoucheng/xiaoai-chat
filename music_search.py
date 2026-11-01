"""音乐搜索模块 - 基于 go-music-dl"""
import asyncio
import logging
import re
import socket
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote, urlencode, urlparse, urlunparse

import aiohttp

logger = logging.getLogger(__name__)


def _get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


_local_ip = _get_local_ip()
MUSIC_DL_BASE = f"http://{_local_ip}:8080/music"
MUSIC_DL_LOCAL = "http://localhost:8080/music"


class SongCardParser(HTMLParser):
    """解析搜索结果 HTML 中的歌曲卡片"""

    def __init__(self):
        super().__init__()
        self.songs = []
        self.current_song = None
        self.in_song_card = False

    def handle_starttag(self, tag, attrs):
        if tag == "li" and any(cls == "song-card" for name, cls in attrs if name == "class"):
            self.in_song_card = True
            self.current_song = {}
            for name, value in attrs:
                if name.startswith("data-"):
                    key = name[5:].replace("-", "_")
                    self.current_song[key] = value or ""

    def handle_endtag(self, tag):
        if tag == "li" and self.in_song_card and self.current_song:
            self.in_song_card = False
            if self.current_song.get("id") and self.current_song.get("source"):
                self.songs.append(self.current_song)
            self.current_song = None


async def search_songs(keyword: str, source: str = "netease", max_results: int = 5) -> list[dict]:
    """搜索歌曲，返回歌曲列表"""
    url = f"{MUSIC_DL_LOCAL}/search?q={quote(keyword)}&source={source}&type=song&page=1"
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    logger.debug(f"搜索 {source} 返回 {resp.status}")
                    return []
                html = await resp.text()
                parser = SongCardParser()
                parser.feed(html)
                # 过滤指定源
                songs = [s for s in parser.songs if s.get("source") == source]
                logger.info(f"搜索 '{keyword}' (源: {source}) 找到 {len(songs)} 首歌曲")
                return songs[:max_results]
        except Exception as e:
            logger.debug(f"搜索 {source} 失败：{e}")
            return []


_BRACKETS = re.compile(r"[（(\[【].*?[）)\]】]")
_VERSION_HINTS = (
    "伴奏", "伴唱", "翻唱", "cover", "live", "演唱会", "片段", "铃声", "dj", "remix",
    "纯音乐", "钢琴", "吉他", "口琴", "童声", "女声版", "男声版", "加速", "降调", "慢速",
)


def _norm(text: str) -> str:
    return "".join(ch for ch in text.lower() if not ch.isspace())


def _artist_votes(songs: list[dict]) -> dict[str, int]:
    """统计各源里出现频次高的歌手——原唱通常会在多个源反复出现"""
    votes: dict[str, int] = {}
    for song in songs:
        for artist in re.split(r"[/、,，&+\s]+", song.get("artist", "")):
            artist = artist.strip().lower()
            if len(artist) >= 2:
                votes[artist] = votes.get(artist, 0) + 1
    return votes


def _score(song: dict, keyword: str, votes: dict[str, int] | None = None) -> float:
    """给候选打分：标题贴近关键词、时长完整、歌手在多源高频出现（原唱）分越高"""
    name = song.get("name", "")
    artist = song.get("artist", "")
    norm_kw = _norm(keyword)
    norm_name = _norm(name)
    plain = _norm(_BRACKETS.sub("", name))

    score = 0.0
    if norm_name == norm_kw:
        score += 60
    elif plain == norm_kw:
        score += 40
    elif norm_kw and norm_kw in norm_name:
        score += 15
    else:
        score -= 20

    if _BRACKETS.search(name):
        score -= 10
    if any(hint in name.lower() for hint in _VERSION_HINTS):
        score -= 30

    try:
        duration = int(song.get("duration", 0))
    except (TypeError, ValueError):
        duration = 0
    if duration >= 200:
        score += 25
    elif duration >= 120:
        score += 10
    elif duration:
        score -= 15

    artists = [a.strip().lower() for a in re.split(r"[/、,，&+\s]+", artist) if len(a.strip()) >= 2]
    for token in re.split(r"[\s,，、/]+", keyword):
        if len(token) >= 2 and token.lower() in artist.lower():
            score += 30
    if votes and artists:
        # 取这首歌里最热门的那个歌手，避免合唱曲目把两个人的票叠加
        best = max(votes.get(a, 0) for a in artists)
        score += 12 * min(best, 4)
    return score


def rank_songs(songs: list[dict], keyword: str, votes: dict[str, int] | None = None) -> list[dict]:
    """按"像不像原版正曲"排序，同分保持搜索原始顺序"""
    return sorted(songs, key=lambda s: -_score(s, keyword, votes))


def build_stream_url(song: dict) -> str:
    """构建音频流 URL"""
    params = {
        "id": song.get("id", ""),
        "source": song.get("source", ""),
        "name": song.get("name", ""),
        "artist": song.get("artist", ""),
        "stream": "1",
    }

    album = song.get("album", "")
    if album:
        params["album"] = album

    cover = song.get("cover", "")
    if cover:
        params["cover"] = cover

    query_string = urlencode(params)
    return f"{MUSIC_DL_BASE}/download?{query_string}"


def prefer_mp3_url(url: str) -> str:
    """migu 的 id 里带音质段，改成 HQ 拿 MP3（FLAC 无法按帧切片）"""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    song_id = qs.get("id", [""])[0]
    if qs.get("source", [""])[0] == "migu" and song_id.count("|") == 2:
        content_id, resource_type, _ = song_id.split("|")
        qs["id"] = [f"{content_id}|{resource_type}|HQ"]
        return urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))
    return url


async def check_song_available(session: aiohttp.ClientSession, song: dict) -> tuple[str, str, str, bool] | None:
    """检查歌曲是否可用，返回 (url, name, source, 是否 MP3)"""
    url = prefer_mp3_url(build_stream_url(song))
    name = f"{song.get('name', '')} - {song.get('artist', '')}"
    source = song.get('source', '')
    
    try:
        headers = {"Range": "bytes=0-0"}
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            if resp.status in (200, 206):
                ctype = resp.headers.get("Content-Type", "").lower()
                is_mp3 = "mpeg" in ctype or "mp3" in ctype
                return url, name, source, is_mp3
    except Exception as e:
        logger.debug(f"检查歌曲失败: {name} - {e}")
    
    return None


async def _check_group(songs: list[dict]) -> tuple[tuple[str, str, str, bool] | None, tuple[str, str, str, bool] | None]:
    """检查一组歌曲，返回 (首选 MP3 候选, 任意可播候选)"""
    async with aiohttp.ClientSession() as session:
        results = await asyncio.gather(*[check_song_available(session, s) for s in songs], return_exceptions=True)

    mp3_hit = None
    fallback = None
    for result in results:
        if isinstance(result, Exception) or result is None:
            continue
        if result[3] and mp3_hit is None:
            mp3_hit = result
        elif not result[3] and fallback is None:
            fallback = result
    return mp3_hit, fallback


def _artist_list(song: dict) -> list[str]:
    return [a.strip().lower() for a in re.split(r"[/、,，&+\s]+", song.get("artist", "")) if len(a.strip()) >= 2]


def _early_candidate(songs: list[dict], keyword: str) -> list[dict] | None:
    """候选是否足够靠谱到可以提前开播：标题完全一致、不是 Live/翻唱等版本、歌手已有多源印证"""
    if not songs:
        return None
    votes = _artist_votes(songs)
    ranked = rank_songs(songs, keyword, votes)
    top = ranked[0]
    name = top.get("name", "")
    if _norm(name) != _norm(keyword) or _BRACKETS.search(name):
        return None
    if any(hint in name.lower() for hint in _VERSION_HINTS):
        return None
    try:
        if 0 < int(top.get("duration", 0)) < 180:
            return None
    except (TypeError, ValueError):
        pass
    if max((votes.get(a, 0) for a in _artist_list(top)), default=0) < 2:
        return None
    return ranked


async def search_and_play(keyword: str, source: str = "netease") -> tuple[str, str] | None:
    """并发搜索所有源；头 2.5 秒就出现高置信候选时立刻开播，否则等满 4 秒再全局排序"""
    sources = ["migu", "netease", "qq", "kugou", "bilibili", "kuwo"]  # 咪咕打平时优先

    logger.info(f"并发搜索 {len(sources)} 个源 (优先级: {', '.join(sources)})...")

    tasks = [asyncio.create_task(search_songs(keyword, source=src, max_results=8)) for src in sources]
    results: dict[str, list[dict]] = {}
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 4.0

    def collect(finished):
        for src, task in zip(sources, tasks):
            if task in finished and not task.cancelled() and task.exception() is None:
                songs = task.result() or []
                if songs:
                    results[src] = songs

    try:
        pending = set(tasks)
        early_fallback = None
        early_checked = False
        while pending and loop.time() < deadline:
            # 边等边看：3 个源返回后先评估一次，够靠谱就立刻开播，慢源继续补齐
            done, pending = await asyncio.wait(pending, timeout=0.4)
            collect(done)
            if early_checked or len(results) < 3:
                continue
            early_checked = True
            early = _early_candidate([s for songs in results.values() for s in songs], keyword)
            if not early:
                continue
            mp3_hit, early_fallback = await _check_group(early[:3])
            if mp3_hit:
                url, name, src_name, _ = mp3_hit
                logger.info(f"提前命中 MP3 歌曲: {name} (源: {src_name})")
                return url, name
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()

    if not results:
        logger.warning(f"所有源都未找到歌曲: {keyword}")
        return None

    # 跨源汇总后统一打分：原唱在多个源反复出现，分数自然更高
    pool = [song for songs in results.values() for song in songs]
    votes = _artist_votes(pool)
    candidates = []
    for src in sources:
        for song in results.get(src, []):
            candidates.append((-_score(song, keyword, votes), sources.index(src), song))
    candidates.sort(key=lambda item: (item[0], item[1]))

    logger.info(f"候选 {len(candidates)} 首，最优: {candidates[0][2].get('name')} - {candidates[0][2].get('artist')}")

    fallback = early_fallback  # 非 MP3 的可播候选，最后兜底
    for start in range(0, len(candidates), 8):
        batch = [item[2] for item in candidates[start:start + 8]]
        mp3_hit, group_fallback = await _check_group(batch)
        if mp3_hit:
            url, name, source_name, _ = mp3_hit
            logger.info(f"找到可用 MP3 歌曲: {name} (源: {source_name})")
            return url, name
        if group_fallback and fallback is None:
            fallback = group_fallback

    if fallback:
        url, name, source_name, _ = fallback
        logger.warning(f"只找到非 MP3 版本，将转码后分段播放: {name} (源: {source_name})")
        return url, name

    logger.warning(f"所有源都未找到可用歌曲: {keyword}")
    return None


_SOURCE_PRIORITY = ["migu", "kuwo", "qq", "kugou", "netease"]


async def _pick_mp3(candidates: list[tuple[str, dict]]) -> tuple[str, dict] | None:
    """并行探测同一首歌的多个源，返回第一个 MP3 版本（按源优先级）"""
    if not candidates:
        return None
    ordered = sorted(candidates, key=lambda c: _SOURCE_PRIORITY.index(c[0])
                     if c[0] in _SOURCE_PRIORITY else 99)
    async with aiohttp.ClientSession() as session:
        checks = await asyncio.gather(*[
            check_song_available(session, song) for _, song in ordered
        ], return_exceptions=True)
    for (src, song), hit in zip(ordered, checks):
        if isinstance(hit, Exception) or not hit:
            continue
        if hit[3]:
            return hit[0], song
    return None


async def search_artist_tracks(artist: str, limit: int = 8) -> list[tuple[str, str]]:
    """多源找歌手的正曲，只留 MP3 可直接切片的版本"""
    sources = ["migu", "kuwo", "qq", "kugou", "netease"]
    raw = await asyncio.gather(*[
        search_songs(artist, source=src, max_results=20) for src in sources
    ], return_exceptions=True)

    low = artist.lower()
    groups: dict[str, list[tuple[str, dict]]] = {}
    src_count: dict[str, set[str]] = {}
    for src, songs in zip(sources, raw):
        if isinstance(songs, Exception) or not songs:
            continue
        for song in songs:
            name = song.get("name", "")
            if low not in (song.get("artist") or "").lower():
                continue
            if _BRACKETS.search(name) or any(hint in name.lower() for hint in _VERSION_HINTS):
                continue
            try:
                if int(song.get("duration", 0)) < 90:
                    continue
            except (TypeError, ValueError):
                pass
            key = _norm(name)
            groups.setdefault(key, []).append((src, song))
            src_count.setdefault(key, set()).add(src)

    if not groups:
        return []

    # 多源都收录的更像正曲，其次看时长
    def rank_item(key: str):
        songs = [s for _, s in groups[key]]
        try:
            dur = max(int(s.get("duration", 0)) for s in songs)
        except (TypeError, ValueError):
            dur = 0
        return (-len(src_count[key]), -dur)

    keys = sorted(groups, key=rank_item)[:limit * 2]
    picks = await asyncio.gather(*[_pick_mp3(groups[k]) for k in keys], return_exceptions=True)

    tracks: list[tuple[str, str]] = []
    for hit in picks:
        if isinstance(hit, Exception) or not hit:
            continue
        url, song = hit
        tracks.append((url, f"{song.get('name', '')} - {song.get('artist', '')}"))
        if len(tracks) >= limit:
            break
    return tracks
