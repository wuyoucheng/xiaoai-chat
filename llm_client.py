from openai import AsyncOpenAI
import config

client = AsyncOpenAI(
    api_key=config.LLM_API_KEY,
    base_url=config.LLM_API_BASE,
)

conversation_history: list[dict] = []


async def chat(user_message: str) -> str:
    conversation_history.append({"role": "user", "content": user_message})

    if len(conversation_history) > 20:
        conversation_history[:] = conversation_history[-20:]

    messages = [{"role": "system", "content": config.LLM_SYSTEM_PROMPT}]
    messages.extend(conversation_history)

    resp = await client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=messages,
    )

    reply = resp.choices[0].message.content
    conversation_history.append({"role": "assistant", "content": reply})

    return reply


def reset_history():
    conversation_history.clear()
