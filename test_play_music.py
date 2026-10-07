"""
测试：空闲状态下，L05C 音箱能否通过 play_by_music_url 播放音频。

用法：
1. 确保音箱处于空闲状态（没有对话、没有播放）
2. 运行此脚本
3. 观察音箱是否播放音频

如果音箱播放了音频，说明音乐通道在空闲状态下可用！
"""
import asyncio
import logging

from xiaoai import create_speakers
from tts_engine import generate_tts

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    print("=" * 60)
    print("测试：空闲音箱能否通过音乐通道播放 TTS 音频")
    print("=" * 60)
    print()
    print("请确保音箱处于空闲状态（没有对话、没有播放）")
    print()

    speakers = await create_speakers()
    if not speakers:
        print("没有找到设备")
        return

    speaker = speakers[0]
    print(f"\n测试设备: {speaker.name} ({speaker.device_id[:8]}...)")
    print(f"型号: {speaker.hardware}")

    # 生成 TTS 音频
    test_text = "你好，这是通过音乐通道播放的测试音频。如果你听到了这段话，说明音乐通道在空闲状态下可用。"
    print(f"\n正在生成 TTS 音频...")
    print(f"文本: {test_text}")

    audio_url = await generate_tts(test_text)
    if not audio_url:
        print("TTS 生成失败！")
        return

    print(f"音频 URL: {audio_url}")
    print(f"\n3 秒后开始播放...")
    await asyncio.sleep(3)

    print(f"\n尝试通过 play_by_music_url 播放...")
    result = await speaker.play_audio_url(audio_url)
    print(f"API 返回: {result}")

    print()
    if result:
        print("请检查音箱是否播放了音频！")
        print("如果播放了，说明音乐通道在空闲状态下可用。")
    else:
        print("API 返回失败，音乐通道可能不支持空闲播放。")

    print()
    print("=" * 60)
    print("接下来测试 text_to_speech（对比用）")
    print("=" * 60)
    await asyncio.sleep(3)

    print("\n尝试通过 text_to_speech 播放...")
    await speaker.speak("这是通过 TTS 通道播放的测试")
    print("请检查音箱是否播放了音频。")
    print("(预期：不会播放，因为音箱处于空闲状态)")


if __name__ == "__main__":
    asyncio.run(main())
