# xiaoai-chat

让小爱音箱接入 AI 大模型，用语音和 AI 对话。

## 原理

通过小米云端 API 轮询小爱音箱的对话记录，截获用户提问，发送给大模型处理后，用 edge-tts 生成语音，通过音乐通道回传音箱播放。

## 支持的大模型

任何兼容 OpenAI API 格式的大模型都可以：

- DeepSeek（默认，成本极低）
- 通义千问
- OpenAI
- 其他兼容接口

## 准备材料

- 小爱音箱（已验证：Play 增强版 L05C）
- 一台同局域网的电脑（Windows / Mac / Linux）
- Python 3.10+
- 大模型 API Key（DeepSeek 充值 10 元可用很久）

## 部署步骤

### 1. 克隆项目

```bash
git clone https://github.com/你的用户名/xiaoai-chat.git
cd xiaoai-chat
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置

复制 `.env.example` 为 `.env`，填入你的信息：

```bash
cp .env.example .env
```

编辑 `.env`：

```
# 小米账号（手机号）
MI_USER=你的小米账号
MI_PASS=你的密码

# 大模型 API
LLM_API_BASE=https://api.deepseek.com/v1
LLM_API_KEY=你的API_KEY
LLM_MODEL=deepseek-chat
```

### 4. 启动

```bash
python main.py
```

首次启动会要求小米账号验证码，按提示操作即可。登录状态会保存到 `.mi.token`，后续启动不需要重复验证。

## 已知限制

- 云端对话 API 有约 24 秒延迟，用户会先听到小爱自带的回答，再听到大模型的回答
- edge-tts 在 Windows 上可能有 IPv6 连接问题，代码已做 IPv4 强制处理
- 操作类指令（播放音乐、控制设备等）会自动过滤，由小爱内置 AI 处理

## 技术细节

- **语音输入**：小米云端对话历史 API 轮询
- **大模型**：OpenAI 兼容接口（DeepSeek / 通义千问 / ChatGPT 等）
- **语音输出**：edge-tts（微软免费 TTS）生成 MP3 → 本地 HTTP 服务器 → `play_by_music_url` 音乐通道播放
- **循环播放修复**：播放完毕后自动发送静音 MP3 覆盖，防止音乐通道循环
- **多设备支持**：自动发现账号下所有小爱音箱，也可通过 `DEVICE_ID` 指定

## License

MIT
