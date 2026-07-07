import os, discord, requests
from discord.ext import commands

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
AI_CHANNEL_ID = 1524041767580733630  # ← замени на свой ID канала

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"ИИ-бот {bot.user} готов!")

@bot.command(name="ии")
@commands.cooldown(1, 30, commands.BucketType.user)
async def ask_ai(ctx, *, question: str = None):
    if ctx.channel.id != AI_CHANNEL_ID:
        return
    if not question:
        await ctx.send("Напиши вопрос после `!ии`")
        return
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        await ctx.send("Ключ API не настроен.")
        return
    try:
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {"model": "mistralai/mistral-7b-instruct", "messages": [{"role": "user", "content": question}], "max_tokens": 200, "temperature": 0.7}
        resp = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload, timeout=15)
        answer = resp.json()["choices"][0]["message"]["content"][:1000]
        await ctx.reply(answer, mention_author=False)
    except Exception as e:
        await ctx.send(f"Ошибка: {e}")

if __name__ == "__main__":
    bot.run(TOKEN)
