# -*- coding: utf-8 -*-
"""
morning_brief.py —— 让小爱音箱在固定时间主动播报（不用喊"小爱同学"）

复用 xiaoai-chat 现有能力：
  - xiaoai.create_speakers()         登录 + 拿到设备
  - tts_engine.generate_tts()        edge-tts 生成 MP3 并起本地 http 服务
  - speaker.play_audio_url()         音乐通道抢占播放（空闲状态也有效）

用法：
  python morning_brief.py --dry      只打印播报稿，不出声（先验证文案）
  python morning_brief.py --now      立刻播一次（拍素材用）
  python morning_brief.py            常驻，每天到 BRIEF_TIME 自动播

.env 可配置：
  BRIEF_TIME=07:00        播报时间
  BRIEF_CITY=Taizhou      天气城市（英文或拼音，wttr.in 支持）
  BRIEF_NOTE=记得吃药     自定义提醒（可留空）
  BRIEF_USE_LLM=1         用大模型把稿子润色成口语（默认 0，模板直出更稳）
"""

import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta

import aiohttp

import config
from xiaoai import create_speakers
from tts_engine import generate_tts, get_silence_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("brief")

BRIEF_TIME = os.getenv("BRIEF_TIME", "07:00")
BRIEF_CITY = os.getenv("BRIEF_CITY", "Taizhou")
BRIEF_CITY_CN = os.getenv("BRIEF_CITY_CN", "泰州")
BRIEF_NOTE = os.getenv("BRIEF_NOTE", "")
USE_LLM = os.getenv("BRIEF_USE_LLM", "0") == "1"
WEEK_CN = "一二三四五六日"

# wttr.in 的 lang=zh 实际不生效，用 WWO 天气代码本地映射
CODE_ZH = {
    "113": "晴", "116": "多云", "119": "阴", "122": "阴天",
    "143": "薄雾", "248": "有雾", "260": "有雾",
    "176": "可能有阵雨", "263": "零星小雨", "266": "毛毛雨",
    "293": "零星小雨", "296": "小雨", "299": "间断中雨", "302": "中雨",
    "305": "间断大雨", "308": "大雨", "353": "小阵雨", "356": "中阵雨", "359": "强阵雨",
    "200": "有雷阵雨", "386": "有雷阵雨", "389": "强雷雨",
    "179": "可能有雪", "182": "可能有雨夹雪", "185": "可能有冻雨",
    "227": "吹雪", "230": "暴雪", "323": "零星小雪", "326": "小雪",
    "329": "中雪", "332": "中雪", "335": "大雪", "338": "大雪",
    "368": "小阵雪", "371": "大阵雪", "374": "有小冰粒", "377": "有冰粒",
}


def zh_desc(code) -> str:
    return CODE_ZH.get(str(code), "天气不明")



async def fetch_weather(city: str) -> dict | None:
    """wttr.in 免费天气，无需 API Key"""
    url = f"https://wttr.in/{city}?format=j1&lang=zh"
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.get(url) as r:
                if r.status != 200:
                    logger.warning(f"天气接口返回 {r.status}")
                    return None
                data = await r.json(content_type=None)

        cur = data["current_condition"][0]
        today = data["weather"][0]
        hourly = today.get("hourly") or [{}]
        midday = hourly[4] if len(hourly) > 4 else hourly[0]

        return {
            "desc": zh_desc(midday.get("weatherCode") or cur.get("weatherCode")),
            "temp_now": cur.get("temp_C", "?"),
            "max": today.get("maxtempC", "?"),
            "min": today.get("mintempC", "?"),
            "rain": midday.get("chanceofrain", ""),
        }
    except Exception as e:
        logger.warning(f"天气获取失败: {e}")
        return None


def build_script(weather: dict | None) -> str:
    now = datetime.now()
    parts = [f"早上好，今天是 {now.month} 月 {now.day} 日，星期{WEEK_CN[now.weekday()]}。"]

    if weather:
        w = f"{BRIEF_CITY_CN}今天{weather['desc']}，{weather['min']} 到 {weather['max']} 度，现在 {weather['temp_now']} 度"
        if weather.get("rain") and str(weather["rain"]).isdigit() and int(weather["rain"]) >= 50:
            w += f"，降水概率百分之{weather['rain']}，出门记得带伞"
        parts.append(w + "。")
    else:
        parts.append("天气没取到，出门前自己看一眼窗外。")

    if BRIEF_NOTE:
        parts.append(f"提醒你一下：{BRIEF_NOTE}。")

    parts.append("播报完毕，祝你今天顺利。")
    return "".join(parts)


async def polish_with_llm(script: str) -> str:
    """可选：把模板稿润色成更像人说的口播稿"""
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_API_BASE)
        resp = await client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[
                {"role": "system", "content": "你是早晨播报员。把用户给的要点改写成一段自然口语，"
                                              "不超过120字，不要加标题、不要分条、不要emoji。"},
                {"role": "user", "content": script},
            ],
        )
        text = (resp.choices[0].message.content or "").strip()
        return text or script
    except Exception as e:
        logger.warning(f"润色失败，用模板稿: {e}")
        return script


async def speak_once(speakers, script: str):
    logger.info(f"播报稿（{len(script)} 字）: {script}")
    result = await generate_tts(script)
    if not result:
        logger.error("TTS 生成失败")
        return
    audio_url, duration = result

    for s in speakers:
        ok = await s.play_audio_url(audio_url)
        if not ok:
            logger.warning(f"[{s.name}] 音乐通道失败，改用内置 TTS")
            await s.speak(script)
            continue
        logger.info(f"[{s.name}] 开始播报，预计 {duration:.1f}s")
        await asyncio.sleep(duration + 1)
        silence = await get_silence_url()
        if silence:
            await s.play_audio_url(silence)   # 静音覆盖，防止音乐通道循环
            logger.info(f"[{s.name}] 播报结束，已静音覆盖")


def next_run_at(now: datetime) -> datetime:
    hh, mm = (int(x) for x in BRIEF_TIME.split(":"))
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


async def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""

    # --dry：只出稿不出声，先看文案顺不顺
    if mode == "--dry":
        weather = await fetch_weather(BRIEF_CITY)
        script = build_script(weather)
        if USE_LLM:
            script = await polish_with_llm(script)
        print("\n" + "=" * 50)
        print(script)
        print("=" * 50)
        print(f"字数 {len(script)}｜天气数据 {'有' if weather else '没取到'}")
        return

    speakers = await create_speakers()

    if mode == "--now":
        weather = await fetch_weather(BRIEF_CITY)
        script = build_script(weather)
        if USE_LLM:
            script = await polish_with_llm(script)
        await speak_once(speakers, script)
        print("播报完成")
        return

    # 常驻：每天 BRIEF_TIME 触发
    logger.info(f"定时播报已启动：每天 {BRIEF_TIME}｜城市 {BRIEF_CITY}")
    spoken_date = None
    while True:
        now = datetime.now()
        if now.strftime("%Y-%m-%d") != spoken_date and now.strftime("%H:%M") == BRIEF_TIME:
            try:
                weather = await fetch_weather(BRIEF_CITY)
                script = build_script(weather)
                if USE_LLM:
                    script = await polish_with_llm(script)
                await speak_once(speakers, script)
                spoken_date = now.strftime("%Y-%m-%d")
                logger.info("今日播报完成，等待下一天")
            except Exception as e:
                logger.error(f"播报异常: {e}")
        await asyncio.sleep(15)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
