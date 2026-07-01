# -*- coding: utf-8 -*-
import asyncio
import json
import os
import re
import wave
import struct
import math
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands

# ---------- НАСТРОЙКИ ----------
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
VOICE_CHANNEL_ID = None  # ID голосового канала для обзвона, или None
ALLOWED_ROLES = ["Гос. волна", "Лидер"]
SLOT_DURATION = 15          # минут
MUTE_DURATION = timedelta(minutes=30)
MIN_BOOK_DELAY = timedelta(minutes=5)
TIMEZONE_OFFSET_HOURS = 3   # UTC+3 (Москва)

# ---------- ФАЙЛЫ ----------
REMINDERS_FILE = "reminders.json"
INTERVIEWS_FILE = "interviews.json"
VIOLATIONS_FILE = "violations.json"
QUESTIONS_FILE = "questions.json"

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

def local_to_utc(h, m):
    total = (h * 60 + m - TIMEZONE_OFFSET_HOURS * 60) % (24 * 60)
    return total // 60, total % 60

def utc_to_local(h, m):
    total = (h * 60 + m + TIMEZONE_OFFSET_HOURS * 60) % (24 * 60)
    return total // 60, total % 60

def has_conflict(utc_h, utc_m, interviews, duration=SLOT_DURATION):
    new_start = utc_h * 60 + utc_m
    new_end = new_start + duration
    for slot in interviews:
        s_h, s_m = slot["start"]
        exist_start = s_h * 60 + s_m
        exist_end = exist_start + duration
        if new_start < exist_end and new_end > exist_start:
            return True
    return False

def clean_old(interviews):
    now_utc = datetime.now(timezone.utc)
    cur = now_utc.hour * 60 + now_utc.minute
    return [s for s in interviews if (s["start"][0]*60 + s["start"][1] + SLOT_DURATION) > cur]

def get_next_free(h_local, m_local):
    now_utc = datetime.now(timezone.utc)
    base_local = now_utc.replace(hour=h_local, minute=m_local)
    while True:
        base_local += timedelta(minutes=5)
        lh, lm = base_local.hour, base_local.minute
        uh, um = local_to_utc(lh, lm)
        if not has_conflict(uh, um, bot.interviews):
            return f"{lh:02d}:{lm:02d}"
        if lh == 23 and lm > 55:
            return "сегодня больше нет"

async def reject(ctx, msg):
    await ctx.reply(msg, mention_author=False)
    try:
        await ctx.message.add_reaction("❌")
    except:
        pass
    uid = str(ctx.author.id)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if uid not in bot.violations:
        bot.violations[uid] = {"count": 0, "date": today}
    elif bot.violations[uid]["date"] != today:
        bot.violations[uid] = {"count": 0, "date": today}
    bot.violations[uid]["count"] += 1
    cnt = bot.violations[uid]["count"]
    if cnt == 1:
        final_msg = msg + "\n⚠️ Это ваше первое нарушение за день. При повторном нарушении будет мут на 30 минут."
    else:
        try:
            await ctx.author.timeout(MUTE_DURATION, reason="Повторное нарушение правил гос. волны")
            final_msg = f"🔇 {ctx.author.mention} мут на 30 минут за повторное нарушение."
        except discord.Forbidden:
            final_msg = "⚠️ Не удалось выдать мут (нет прав)."
        bot.violations[uid] = {"count": 0, "date": today}
    save_json(VIOLATIONS_FILE, bot.violations)
    await ctx.reply(final_msg, mention_author=False)
    try:
        await ctx.message.add_reaction("❌")
    except:
        pass

# ---------- БОТ ----------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

bot.interviews = load_json(INTERVIEWS_FILE, [])
bot.violations = load_json(VIOLATIONS_FILE, {})
bot.reminders = load_json(REMINDERS_FILE, [])
bot.questions = load_json(QUESTIONS_FILE, {})
bot.active_exams = {}

async def check_interviews_loop():
    await bot.wait_until_ready()
    notified = set()
    print("[LOOP] Started, offset =", TIMEZONE_OFFSET_HOURS)
    while not bot.is_closed():
        now_utc = datetime.now(timezone.utc)
        bot.interviews = clean_old(bot.interviews)
        for slot in bot.interviews[:]:
            slot_id = f"{slot['family']}-{slot['start'][0]:02d}-{slot['start'][1]:02d}"
            start_dt = now_utc.replace(hour=slot["start"][0], minute=slot["start"][1], second=0, microsecond=0)
            if start_dt <= now_utc and slot_id not in notified:
                channel = bot.get_channel(slot["channel_id"])
                if channel:
                    if slot.get("type") == "обзвон":
                        vc = f"<#{VOICE_CHANNEL_ID}>" if VOICE_CHANNEL_ID else "голосовой канал"
                        text = f"📢 <@{slot['user_id']}>, просьба зайти в голосовой канал {vc}"
                    else:
                        text = f"⏰ <@{slot['user_id']}>, начинается собеседование, заходите"
                    await channel.send(text)
                notified.add(slot_id)
        await asyncio.sleep(30)

@bot.event
async def on_ready():
    print(f"Бот {bot.user} готов!")
    print("Доступные команды:", [cmd.name for cmd in bot.commands])
    bot.loop.create_task(check_interviews_loop())

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if "пицца" in message.content.lower():
        await message.reply("Yummi", mention_author=False)
    if re.search(r"скибиди|skibidi", message.content, re.IGNORECASE):
        await message.reply(
            "Skibidi ua-papa!\n"
            "Skibidi ua-papa-papa!\n"
            "Skibidi ua-papa-papa-papa-papa!\n"
            "Skibidi papa!\n"
            "Skibidi boom-boom, ay!\n"
            "Skibidi boom-boom-boom-boom, ay!\n"
            "Skibidi boom-boom-boom-boom-boom-papa-boom-boom!\n"
            "Skibidi papa!",
            mention_author=False
        )
    if "духи" in message.content.lower():
        await message.reply("faradenza", mention_author=False)

    match = re.search(r"оплачиваю\s+дом\s+на\s+(\d+)\s*д(?:н(?:ей|я|ь)?)?", message.content, re.IGNORECASE)
    if match:
        days = int(match.group(1))
        if days <= 2:
            await message.channel.send(f"{message.author.mention}, оплата всего на {days} дн. – напоминаю сейчас!")
            return
        remind_at = datetime.now(timezone.utc) + timedelta(days=days-2)
        reminder = {
            "user_id": message.author.id,
            "channel_id": message.channel.id,
            "remind_at": remind_at.isoformat(),
            "days": days
        }
        bot.reminders.append(reminder)
        save_json(REMINDERS_FILE, bot.reminders)
        await message.channel.send(
            f"{message.author.mention}, понял! Я напомню об оплате {remind_at.strftime('%d.%m.%Y в %H:%M')} (UTC)."
        )
        async def remind(rem):
            delay = (remind_at - datetime.now(timezone.utc)).total_seconds()
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
        delay = (remind_at - datetime.now(timezone.utc)).total_seconds()
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
        await reject(ctx, "❌ Нет прав.")
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
    h_local, m_local = map(int, time_str.split(":"))
    h_utc, m_utc = local_to_utc(h_local, m_local)
    now_utc = datetime.now(timezone.utc)
    slot_dt = now_utc.replace(hour=h_utc, minute=m_utc, second=0, microsecond=0)
    if slot_dt < now_utc:
        await reject(ctx, "❌ Нельзя записаться на прошедшее время.")
        return
    if slot_dt - now_utc < MIN_BOOK_DELAY:
        await reject(ctx, f"❌ Запись возможна не менее чем за {MIN_BOOK_DELAY.total_seconds()//60} минут до начала.")
        return
    bot.interviews = clean_old(bot.interviews)
    if has_conflict(h_utc, m_utc, bot.interviews):
        next_free = get_next_free(h_local, m_local)
        await reject(ctx, f"❌ Занято. Ближайшее свободное: **{next_free}**.")
        return
    slot = {
        "family": family,
        "start": [h_utc, m_utc],
        "user_id": ctx.author.id,
        "channel_id": ctx.channel.id,
        "type": type_str
    }
    bot.interviews.append(slot)
    save_json(INTERVIEWS_FILE, bot.interviews)
    type_text = "обзвон" if type_str == "обзвон" else "собеседование"
    await ctx.reply(f"✅ Семья **{family}** записана на **{type_text}** в **{time_str}** (местное). Уведомление придёт вовремя.", mention_author=False)
    try:
        await ctx.message.add_reaction("✅")
    except:
        pass

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
    h_local, m_local = map(int, time_str.split(":"))
    h_utc, m_utc = local_to_utc(h_local, m_local)
    for slot in bot.interviews:
        if slot["family"] == family and slot["start"] == [h_utc, m_utc]:
            bot.interviews.remove(slot)
            save_json(INTERVIEWS_FILE, bot.interviews)
            await ctx.reply(f"🗑️ Запись **{family}** на {time_str} отменена.", mention_author=False)
            try:
                await ctx.message.add_reaction("✅")
            except:
                pass
            return
    await ctx.reply("❌ Запись не найдена.", mention_author=False)
    try:
        await ctx.message.add_reaction("❌")
    except:
        pass

@bot.command()
async def list(ctx):
    bot.interviews = clean_old(bot.interviews)
    if not bot.interviews:
        await ctx.reply("Нет активных записей.", mention_author=False)
        return
    msg = "**Записи на гос. волну:**\n"
    for s in sorted(bot.interviews, key=lambda x: x["start"]):
        h_utc, m_utc = s["start"]
        h_local, m_local = utc_to_local(h_utc, m_utc)
        user = bot.get_user(s["user_id"])
        uname = user.mention if user else f"<@{s['user_id']}>"
        t = s.get("type", "собес")
        msg += f"**{s['family']}** — {h_local:02d}:{m_local:02d} ({t}) записал {uname}\n"
    await ctx.reply(msg, mention_author=False)

# ---------- ОБЗВОН ----------
@bot.command(name="обзвон")
async def start_exam(ctx, variant: str = None):
    if variant is None:
        await ctx.send("Укажите номер варианта: `!обзвон 1`, `!обзвон 2`, `!обзвон 3`")
        return
    if variant not in ["1", "2", "3"]:
        await ctx.send("Неверный вариант. Доступны: 1, 2, 3")
        return
    if ctx.author.id in bot.active_exams:
        await ctx.send("У вас уже есть активный обзвон. Сначала завершите его командой `!ответ <ответ>` до конца.")
        return

    questions = bot.questions.get(variant, [])
    if not questions:
        await ctx.send(f"Вариант {variant} пока пуст. Обратитесь к администратору.")
        return

    max_points = sum(q.get("points", 1) for q in questions)
    total_questions = len(questions)
    exam = {
        "variant": variant,
        "channel_id": ctx.channel.id,
        "questions": questions,
        "current": 0,
        "correct": 0,
        "points": 0,
        "max_points": max_points,
        "total": total_questions,
        "pass_threshold": 6
    }
    bot.active_exams[ctx.author.id] = exam

    q = questions[0]
    pts = q.get("points", 1)
    q_number = q.get("number", 1)
    await ctx.send(
        f"**Вопрос {q_number}/{total_questions}** ({pts} балл.): {q['question']}\n"
        f"_Ответьте командой_ `!ответ <ваш ответ>`"
    )

@bot.command(name="ответ")
async def answer_exam(ctx, *, answer: str = None):
    user_id = ctx.author.id
    if user_id not in bot.active_exams:
        return
    exam = bot.active_exams[user_id]
    if ctx.channel.id != exam["channel_id"]:
        return

    if answer is None:
        await ctx.send("Укажите ваш ответ: `!ответ <текст>`")
        return

    q = exam["questions"][exam["current"]]
    if "answers" in q:
        correct_answers = [a.strip().lower() for a in q["answers"]]
    else:
        correct_answers = [q["answer"].strip().lower()]

    user_answer = answer.strip().lower()

    if user_answer in correct_answers:
        exam["correct"] += 1
        pts = q.get("points", 1)
        exam["points"] += pts

    exam["current"] += 1
    if exam["current"] >= exam["total"]:
        correct = exam["correct"]
        total = exam["total"]
        score = exam["points"]
        max_score = exam["max_points"]
        if correct >= exam["pass_threshold"]:
            result_text = "Обзвон пройден"
        else:
            result_text = "Вы не прошли обзвон"
        await ctx.send(
            f"**Обзвон завершён!**\n"
            f"Правильных ответов: {correct} из {total} (нужно ≥ {exam['pass_threshold']})\n"
            f"Набрано баллов: {score} из {max_score}\n"
            f"Результат: **{result_text}**"
        )
        del bot.active_exams[user_id]
    else:
        next_q = exam["questions"][exam["current"]]
        pts = next_q.get("points", 1)
        q_number = next_q.get("number", exam["current"]+1)
        await ctx.send(
            f"Понял, дальше\n"
            f"**Вопрос {q_number}/{exam['total']}** ({pts} балл.): {next_q['question']}\n"
            f"_Ответьте командой_ `!ответ <ваш ответ>`"
        )

# ---------- ВАЙБ 2018 (ГАРАНТИРОВАННО РАБОТАЕТ) ----------
@bot.command(name="вайб")
async def vibe(ctx, year: str = None):
    if year != "2018":
        await ctx.send("Укажи год: `!вайб 2018`")
        return
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("Зайди в голосовой канал!")
        return

    # Генерируем временный WAV-файл (низкий гул, стерео, 5 секунд)
    output = "/tmp/beat.wav"
    sample_rate = 48000
    freq = 80
    duration = 5.0
    with wave.open(output, "w") as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        for i in range(int(sample_rate * duration)):
            sample = int(32767 * 0.5 * math.sin(2 * math.pi * freq * i / sample_rate))
            # стерео: левый = правый
            f.writeframes(struct.pack('<hh', sample, sample))

    vc = await ctx.author.voice.channel.connect()
    # Используем FFmpegOpusAudio – он не требует отдельной библиотеки opus
    source = discord.FFmpegOpusAudio(output)
    vc.play(source)
    while vc.is_playing():
        await asyncio.sleep(0.1)
    await vc.disconnect()
    os.remove(output)


@bot.command(name="отключись")
async def leave(ctx):
    if ctx.guild.voice_client:
        await ctx.guild.voice_client.disconnect()

if __name__ == "__main__":
    bot.run(TOKEN)
    
