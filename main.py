import asyncio
import logging
from time import time

import config
from xiaoai import create_speakers, XiaoAiSpeaker
from llm_client import chat, reset_history
from tts_engine import generate_tts, get_silence_url

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    print("=" * 50)
    print("  小爱音箱 × 大模型对话")
    print("=" * 50)
    print()

    if not config.MI_USER or not config.MI_PASS:
        print("错误: 请在 .env 文件中配置 MI_USER 和 MI_PASS")
        return
    if not config.LLM_API_KEY:
        print("错误: 请在 .env 文件中配置 LLM_API_KEY")
        return

    speakers = await create_speakers()
    print()
    print(f"大模型: {config.LLM_MODEL} ({config.LLM_API_BASE})")
    print(f"轮询间隔: {config.POLL_INTERVAL}s")
    print(f"监听设备: {len(speakers)} 台")
    for s in speakers:
        print(f"  - {s.name} ({s.device_id[:8]}...)")
    print()
    print("已启动，对小爱音箱说话即可对话...")
    print("按 Ctrl+C 退出")
    print("-" * 50)

    processed: set = set()
    state = {"last_query": "", "last_reply_time": 0.0}
    for s in speakers:
        result = await s.get_latest_ask()
        if result:
            q, ts = result
            processed.add(ts)
            state["last_query"] = q
            state["last_reply_time"] = time()
    logger.info(f"已跳过 {len(processed)} 条历史对话")

    await asyncio.gather(
        *[_poll_loop(s, processed, state) for s in speakers],
        return_exceptions=True,
    )


async def _stop_after_playback(speaker: XiaoAiSpeaker, duration: float):
    """播完音频后播放静音，防止音乐播放器循环"""
    try:
        await asyncio.sleep(duration + 1)
        silence_url = await get_silence_url()
        if silence_url:
            await speaker.play_audio_url(silence_url)
            logger.info(f"[{speaker.name}] 播放完毕，已静音覆盖 ({duration:.1f}s)")
    except Exception as e:
        logger.debug(f"静音覆盖异常: {e}")


async def _poll_loop(speaker: XiaoAiSpeaker, processed: set, state: dict):
    processing = False
    COOLDOWN = 60

    while True:
        try:
            result = await speaker.get_latest_ask()

            if result and not processing:
                query, timestamp_ms = result

                is_dup = (
                    timestamp_ms in processed
                    or (query == state["last_query"]
                        and time() - state["last_reply_time"] < COOLDOWN)
                )

                operation_keywords = [
                    "播放", "放歌", "听音乐", "打开", "关闭", "关掉", "开启",
                    "停止", "暂停", "设置", "调节", "调高", "调低", "变大", "变小",
                    "亮一点", "暗一点", "大声", "小声", "音量", "声音",
                    "天气", "温度", "下雨", "下雪", "晴天", "阴天",
                    "扫地", "清扫", "回充",
                    "空调", "暖气", "制冷", "制热"
                ]
                is_operation = any(kw in query for kw in operation_keywords)

                if is_dup:
                    logger.debug(f"[{speaker.name}] 跳过重复: ts={timestamp_ms}")
                elif is_operation:
                    logger.info(f"[{speaker.name}] 跳过操作指令，由小爱处理: {query}")
                    processed.add(timestamp_ms)
                    state["last_query"] = query
                    state["last_reply_time"] = time()
                else:
                    processed.add(timestamp_ms)
                    state["last_query"] = query
                    state["last_reply_time"] = time()
                    processing = True
                    logger.info(f"[{speaker.name}] 用户: {query}")

                    try:
                        reply = await chat(query)
                        logger.info(f"[{speaker.name}] AI: {reply}")

                        result = await generate_tts(reply)
                        if result:
                            audio_url, duration = result
                            success = await speaker.play_audio_url(audio_url)
                            if success:
                                asyncio.create_task(
                                    _stop_after_playback(speaker, duration)
                                )
                            else:
                                logger.warning(f"[{speaker.name}] 音乐通道失败，尝试 TTS")
                                await speaker.speak(reply)
                        else:
                            logger.warning(f"[{speaker.name}] TTS 生成失败，使用内置 TTS")
                            await speaker.speak(reply)

                    except Exception as e:
                        logger.error(f"[{speaker.name}] 大模型调用失败: {e}")
                        error_result = await generate_tts("抱歉，我暂时无法回答")
                        if error_result:
                            error_url, error_duration = error_result
                            success = await speaker.play_audio_url(error_url)
                            if success:
                                asyncio.create_task(
                                    _stop_after_playback(speaker, error_duration)
                                )
                        else:
                            await speaker.speak("抱歉，我暂时无法回答")
                    finally:
                        processing = False

            await asyncio.sleep(config.POLL_INTERVAL)

        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"[{speaker.name}] 轮询异常: {e}")
            await asyncio.sleep(config.POLL_INTERVAL)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
