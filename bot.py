# -*- coding: utf-8 -*-
import asyncio
import json
import os
import re
from datetime import datetime, timedelta

import discord
from discord.ext import commands

# ---------- НАСТРОЙКИ (ЗАМЕНИ ЗДЕСЬ) ----------
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
VOICE_CHANNEL_ID = 1435163969219334306  # ID голосового канала для обзвона, или None
ALLOWED_ROLES = ["Временный лидер", "Зам начальника", "Зам создателя", "Создатель 🔧"]
SLOT_DURATION = 15  # минут
MUTE_DURATION = timedelta(minutes=30)
VIOLATION_WINDOW = timedelta(minutes=5)

# ---------- ФАЙЛЫ ----------
REMINDERS_FILE = "reminders.json"
INTERVIEWS_FILE = "interviews.json"
VIOLATIONS_FILE = "violations.json"

def load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def check_time_format(time_str):
    try:
        h, m = map(int, time_str.split(":"))
        return 0 <= h <= 23 and 0 <= m <= 59 and m % 5 == 0
    except:
        return False

def has_conflict(h, m, interviews, duration=SLOT_DURATION):
    new_start = h * 60 + m
    new_end = new_start + duration
    for slot in interviews:
        s_h, s_m = slot["start"]
        exist_start = s_h * 60 + s_m
        exist_end = exist_start + duration
        if new_start < exist_end and new_end > exist_start:
            return True
    return False

def clean_old(interviews):
    now = datetime.now()
    cur = now.hour * 60 + now.minute
    return [s for s in interviews if (s["start"][0]*60 + s["start"][1] + SLOT_DURATION) > cur]

# ---------- БОТ ----------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

bot.interviews = load_json(INTERVIEWS_FILE, [])
bot.violations = load_json(VIOLATIONS_FILE, {})
bot.reminders = load_json(REMINDERS_FILE, [])

# ---------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ----------
def get_next_free(h, m):
    now = datetime.now()
    base = now.replace(hour=h, minute=m, second=0, microsecond=0)
    while True:
        base += timedelta(minutes=5)
        nh, nm = base.hour, base.minute
        if not has_conflict(nh, nm, bot.interviews):
            return f"{nh:02d}:{nm:02d}"
        if nh == 23 and nm > 55:
            return "сегодня больше нет"

async def reject(ctx, msg):
    await ctx.reply(msg, mention_author=False)
    uid = str(ctx.author.id)
    now_iso = datetime.now().isoformat()
    if uid not in bot.violations:
        bot.violations[uid] = {"count": 0, "last_time": None}
    last = bot.violations[uid]["last_time"]
    cnt = bot.violations[uid]["count"]
    if last:
        last_dt = datetime.fromisoformat(last)
        if (datetime.now() - last_dt) < VIOLATION_WINDOW and cnt >= 1:
            try:
                await ctx.author.timeout(MUTE_DURATION, reason="Повторное нарушение")
                await ctx.reply(f"🔇 {ctx.author.mention} мут 30 мин за повторное нарушение.", mention_author=False)
            except:
                await ctx.reply("⚠️ Не удалось выдать мут.", mention_author=False)
            bot.violations[uid] = {"count": 0, "last_time": now_iso}
            save_json(VIOLATIONS_FILE, bot.violations)
            return
    bot.violations[uid] = {"count": cnt+1, "last_time": now_iso}
    save_json(VIOLATIONS_FILE, bot.violations)

# ---------- ФОНОВАЯ ПРОВЕРКА УВЕДОМЛЕНИЙ (КАЖДЫЕ 30 СЕКУНД) ----------
async def check_interviews_loop():
    await bot.wait_until_ready()
    notified = set()  # чтобы не уведомлять дважды
    while not bot.is_closed():
        now = datetime.now()
        bot.interviews = clean_old(bot.interviews)
        for slot in bot.interviews[:]:
            slot_id = f"{slot['family']}-{slot['start'][0]:02d}-{slot['start'][1]:02d}"
            start_dt = now.replace(hour=slot["start"][0], minute=slot["start"][1], second=0, microsecond=0)
            if start_dt <= now and slot_id not in notified:
                channel = bot.get_channel(slot["channel_id"])
                if channel:
                    if slot.get("type") == "обзвон":
                        vc = f"<#{VOICE_CHANNEL_ID}>" if VOICE_CHANNEL_ID else "голосовой канал"
                        text = f"📢 <@{slot['user_id']}>, просьба зайти в голосовой канал {vc}"
                    else:
                        text = f"⏰ <@{slot['user_id']}>, начинается собеседование, заходите"
                    await channel.send(text)
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Отправлено уведомление для {slot['family']} на {slot['start']}")
                notified.add(slot_id)
        await asyncio.sleep(30)

# ---------- СОБЫТИЯ БОТА ----------
@bot.event
async def on_ready():
    print(f"Бот {bot.user} готов!")
    print("Доступные команды:", [cmd.name for cmd in bot.commands])
    bot.loop.create_task(check_interviews_loop())

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    match = re.search(r"оплачиваю\s+дом\s+на\s+(\d+)\s*д(?:н(?:ей|я|ь)?)?", message.content, re.IGNORECASE)
    if match:
        days = int(match.group(1))
        if days <= 2:
            await message.channel.send(f"{message.author.mention}, оплата всего на {days} дн. – напоминаю сейчас!")
            return
        remind_at = datetime.now() + timedelta(days=days-2)
        reminder = {
            "user_id": message.author.id,
            "channel_id": message.channel.id,
            "remind_at": remind_at.isoformat(),
            "days": days
        }
        bot.reminders.append(reminder)
        save_json(REMINDERS_FILE, bot.reminders)
        await message.channel.send(
            f"{message.author.mention}, понял! Я напомню об оплате {remind_at.strftime('%d.%m.%Y в %H:%M')} (за 2 дня до окончания)."
        )
        async def remind(rem):
            delay = (remind_at - datetime.now()).total_seconds()
            if delay > 0:
                await asyncio.sleep(delay)
            user = bot.get_user(rem["user_id"]) or await bot.fetch_user(rem["user_id"])
            text = f"🔔 Напоминание: срок оплаты дома истекает через 2 дня (оплачено было на {rem['days']} дн.)."
            try:
                await user.send(text)
            except:
                ch = bot.get_channel(rem["channel_id"])
                if ch:
                    await ch.send(f"<@{rem['user_id']}>, {text}")
            bot.reminders = [r for r in bot.reminders if r != rem]
            save_json(REMINDERS_FILE, bot.reminders)
        bot.loop.create_task(remind(reminder))
    else:
        await bot.process_commands(message)

@bot.event
async def setup_hook():
    for rem in bot.reminders:
        remind_at = datetime.fromisoformat(rem["remind_at"])
        delay = (remind_at - datetime.now()).total_seconds()
        if delay > 0:
            async def remind(rem):
                await asyncio.sleep(delay)
                user = bot.get_user(rem["user_id"]) or await bot.fetch_user(rem["user_id"])
                text = f"🔔 Напоминание: срок оплаты дома истекает через 2 дня (оплачено было на {rem['days']} дн.)."
                try:
                    await user.send(text)
                except:
                    ch = bot.get_channel(rem["channel_id"])
                    if ch:
                        await ch.send(f"<@{rem['user_id']}>, {text}")
                bot.reminders = [r for r in bot.reminders if r != rem]
                save_json(REMINDERS_FILE, bot.reminders)
            bot.loop.create_task(remind(rem))

# ---------- КОМАНДЫ ГОС. ВОЛНЫ ----------
@bot.command()
async def sobes(ctx, *, text: str):
    if not any(role.name in ALLOWED_ROLES for role in ctx.author.roles):
        await ctx.reply("❌ Нет прав.", mention_author=False)
        return
    parts = [p.strip() for p in text.split("|")]
    if len(parts) < 2:
        await reject(ctx, "❌ Формат: `!sobes Семья | 13:00 | обзвон`")
        return
    family = parts[0]
    time_str = parts[1]
    type_str = parts[2].lower() if len(parts) >= 3 else "собеседование"
    if not family:
        await reject(ctx, "❌ Укажите семью.")
        return
    if not check_time_format(time_str):
        await reject(ctx, "❌ Время должно быть ЧЧ:ММ и кратно 5 минутам.")
        return
    h, m = map(int, time_str.split(":"))
    now = datetime.now()
    slot_dt = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if slot_dt < now:
        await reject(ctx, "❌ Нельзя записаться на прошедшее время.")
        return
    bot.interviews = clean_old(bot.interviews)
    if has_conflict(h, m, bot.interviews):
        next_free = get_next_free(h, m)
        await reject(ctx, f"❌ Занято. Ближайшее свободное: **{next_free}**.")
        return
    slot = {
        "family": family,
        "start": [h, m],
        "user_id": ctx.author.id,
        "channel_id": ctx.channel.id,
        "type": type_str
    }
    bot.interviews.append(slot)
    save_json(INTERVIEWS_FILE, bot.interviews)
    type_text = "обзвон" if type_str == "обзвон" else "собеседование"
    await ctx.reply(f"✅ Семья **{family}** записана на **{type_text}** в **{time_str}**. Уведомление придёт вовремя.", mention_author=False)

@bot.command()
async def cancel(ctx, *, text: str = None):
    if not text:
        await ctx.reply("Используй: `!cancel Семья | 13:00`", mention_author=False)
        return
    parts = [p.strip() for p in text.split("|")]
    if len(parts) < 2:
        await ctx.reply("❌ Неверный формат.", mention_author=False)
        return
    family = parts[0]
    time_str = parts[1]
    if not check_time_format(time_str):
        await ctx.reply("❌ Время должно быть ЧЧ:ММ кратно 5.", mention_author=False)
        return
    h, m = map(int, time_str.split(":"))
    for slot in bot.interviews:
        if slot["family"] == family and slot["start"] == [h, m]:
            bot.interviews.remove(slot)
            save_json(INTERVIEWS_FILE, bot.interviews)
            await ctx.reply(f"🗑️ Запись **{family}** на {time_str} отменена.", mention_author=False)
            return
    await ctx.reply("❌ Запись не найдена.", mention_author=False)

@bot.command()
async def list(ctx):
    bot.interviews = clean_old(bot.interviews)
    if not bot.interviews:
        await ctx.reply("Нет активных записей.", mention_author=False)
        return
    msg = "**Записи на гос. волну:**\n"
    for s in sorted(bot.interviews, key=lambda x: x["start"]):
        h, m = s["start"]
        user = bot.get_user(s["user_id"])
        uname = user.mention if user else f"<@{s['user_id']}>"
        t = s.get("type", "собес")
        msg += f"**{s['family']}** — {h:02d}:{m:02d} ({t}) записал {uname}\n"
    await ctx.reply(msg, mention_author=False)

# ---------- ЗАПУСК ----------
if __name__ == "__main__":
    bot.run(TOKEN)