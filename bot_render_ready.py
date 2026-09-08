import os
import sqlite3
import base64
import logging
from datetime import datetime, timedelta
from io import BytesIO

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from openai import OpenAI
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("physics-bot")

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
DB_PATH = os.getenv("DB_PATH", "physics_bot.db")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN تنظیم نشده است.")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY تنظیم نشده است.")

ai = OpenAI(api_key=OPENAI_API_KEY)

SYSTEM_PROMPT = """تو یک معلم حرفه‌ای فیزیک برای دانش‌آموزان متوسطه دوم ایران هستی.
مباحث اصلی: فیزیک دهم، یازدهم و دوازدهم، حرکت‌شناسی، دینامیک، کار و انرژی،
ویژگی‌های مواد، دما و گرما، الکتریسیته ساکن، جریان و مدار، مغناطیس و القا،
و مباحث مرتبط کتاب‌های درسی ایران.

قواعد پاسخ:
1) پاسخ را به فارسی و متناسب با سطح دانش‌آموز بده.
2) اگر مسئله محاسباتی است: داده‌ها، خواسته، فرمول، جایگذاری، واحد و جواب نهایی را جدا کن.
3) اگر سؤال مفهومی است، اول مفهوم را ساده توضیح بده و سپس در صورت نیاز مثال بزن.
4) اگر تصویر سؤال فرستاده شده، متن و شکل را دقیق بررسی کن و اگر بخشی خوانا نیست صادقانه بگو.
5) از حدس زدن عدد یا صورت مسئله خودداری کن.
6) اگر سؤال خارج از فیزیک متوسطه دوم است، محترمانه اعلام کن.
7) جواب را آموزشی بده؛ فقط جواب نهایی را بدون توضیح ارائه نکن.
8) در صورت وجود چند روش حل، روش ساده‌تر کتاب درسی را اول بیاور.
"""

TOPICS = (
    "📚 مباحث پیشنهادی:\n"
    "• فیزیک دهم: اندازه‌گیری، بردار، حرکت، دینامیک، کار و انرژی، ویژگی مواد، گرما\n"
    "• فیزیک یازدهم: الکتریسیته ساکن، جریان و مدار، مغناطیس و القا\n"
    "• فیزیک دوازدهم: حرکت، دینامیک، نوسان و موج، اتمی و هسته‌ای و مباحث کتاب"
)

def conn():
    return sqlite3.connect(DB_PATH)

def init_db():
    c = conn()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      user_id INTEGER PRIMARY KEY,
      name TEXT, username TEXT, joined TEXT,
      blocked INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS questions(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER, kind TEXT, question TEXT,
      answer TEXT, created TEXT, helpful INTEGER
    );
    CREATE TABLE IF NOT EXISTS feedback(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      question_id INTEGER, user_id INTEGER,
      text TEXT, created TEXT
    );
    CREATE TABLE IF NOT EXISTS settings(
      key TEXT PRIMARY KEY, value TEXT
    );
    """)
    c.commit(); c.close()

def save_user(u):
    c=conn()
    c.execute("""INSERT OR IGNORE INTO users(user_id,name,username,joined)
                 VALUES(?,?,?,?)""",
              (u.id,u.full_name,u.username,datetime.now().isoformat()))
    c.execute("UPDATE users SET name=?,username=? WHERE user_id=?",
              (u.full_name,u.username,u.id))
    c.commit(); c.close()

def blocked(uid):
    c=conn(); r=c.execute("SELECT blocked FROM users WHERE user_id=?",(uid,)).fetchone()
    c.close(); return bool(r and r[0])

def ask_ai(text, image_bytes=None):
    content = [{"type":"input_text","text":text}]
    if image_bytes:
        b64=base64.b64encode(image_bytes).decode("ascii")
        content.append({"type":"input_image",
                        "image_url":f"data:image/jpeg;base64,{b64}"})
    response=ai.responses.create(
        model=MODEL,
        instructions=SYSTEM_PROMPT,
        input=[{"role":"user","content":content}],
        max_output_tokens=1800
    )
    return response.output_text.strip()

def save_question(uid, kind, question, answer):
    c=conn()
    cur=c.cursor()
    cur.execute("""INSERT INTO questions
        (user_id,kind,question,answer,created) VALUES(?,?,?,?,?)""",
        (uid,kind,question,answer,datetime.now().isoformat()))
    qid=cur.lastrowid; c.commit(); c.close()
    return qid

async def start(update, context):
    save_user(update.effective_user)
    if blocked(update.effective_user.id): return
    kb=[
      [InlineKeyboardButton("📚 مباحث",callback_data="topics"),
       InlineKeyboardButton("❓ راهنما",callback_data="help")],
      [InlineKeyboardButton("ℹ️ درباره ربات",callback_data="about")]
    ]
    await update.message.reply_text(
        "سلام 👋\n\nمن دستیار آموزشی فیزیک متوسطه دوم هستم.\n"
        "سؤال فیزیکت را به صورت متن یا عکس بفرست؛ سعی می‌کنم مرحله‌به‌مرحله حلش کنم.",
        reply_markup=InlineKeyboardMarkup(kb))

async def help_cmd(update, context):
    await update.message.reply_text(
        "📌 راهنما\n\n"
        "• سؤال متنی را مستقیم بفرست.\n"
        "• اگر سؤال عکس دارد، عکس را ارسال کن.\n"
        "• برای عکس، بهتر است کل صورت سؤال و شکل واضح باشد.\n"
        "• بعد از پاسخ، با 👍 یا 👎 نظر بده.\n"
        "• برای نظر توضیحی، دکمه «💬 نظر» را بزن.")

async def admin_cmd(update, context):
    if update.effective_user.id != ADMIN_ID:
        return
    await admin_panel(update, context)

async def admin_panel(update, context):
    c=conn()
    users=c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    q=c.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    bad=c.execute("SELECT COUNT(*) FROM questions WHERE helpful=0").fetchone()[0]
    fb=c.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
    today=(datetime.now()-timedelta(days=1)).isoformat()
    todayq=c.execute("SELECT COUNT(*) FROM questions WHERE created>=?",(today,)).fetchone()[0]
    c.close()
    kb=[
      [InlineKeyboardButton("📊 آمار",callback_data="a_stats"),
       InlineKeyboardButton("⚠️ پاسخ‌های بد",callback_data="a_bad")],
      [InlineKeyboardButton("📝 آخرین سؤال‌ها",callback_data="a_latest"),
       InlineKeyboardButton("📢 پیام همگانی",callback_data="a_broadcast")],
      [InlineKeyboardButton("🚫 مدیریت کاربر",callback_data="a_block")]
    ]
    text=(f"⚙️ پنل مدیریت\n\n👥 کاربران: {users}\n"
          f"📚 کل سؤال‌ها: {q}\n🕐 سؤال‌های ۲۴ ساعت اخیر: {todayq}\n"
          f"👎 پاسخ‌های نامطلوب: {bad}\n💬 بازخورد متنی: {fb}")
    if update.callback_query:
        await update.callback_query.edit_message_text(text,reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text(text,reply_markup=InlineKeyboardMarkup(kb))

async def text_handler(update, context):
    u=update.effective_user; save_user(u)
    if blocked(u.id): return
    if context.user_data.get("awaiting_feedback"):
        qid=context.user_data.pop("awaiting_feedback")
        c=conn(); c.execute(
            "INSERT INTO feedback(question_id,user_id,text,created) VALUES(?,?,?,?)",
            (qid,u.id,update.message.text,datetime.now().isoformat()))
        c.commit(); c.close()
        await update.message.reply_text("نظر شما ثبت شد 🌹")
        if ADMIN_ID:
            await context.bot.send_message(ADMIN_ID,f"💬 بازخورد جدید سؤال #{qid}:\n{update.message.text}")
        return

    await update.message.chat.send_action(ChatAction.TYPING)
    try:
        ans=ask_ai(update.message.text)
        qid=save_question(u.id,"text",update.message.text,ans)
        kb=[[InlineKeyboardButton("👍 مفید",callback_data=f"yes:{qid}"),
             InlineKeyboardButton("👎 مفید نبود",callback_data=f"no:{qid}")],
            [InlineKeyboardButton("💬 نظر",callback_data=f"fb:{qid}")]]
        await update.message.reply_text(ans,reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        log.exception(e)
        await update.message.reply_text("متأسفانه فعلاً در پاسخ‌گویی مشکلی پیش آمد. لطفاً دوباره امتحان کنید.")

async def photo_handler(update, context):
    u=update.effective_user; save_user(u)
    if blocked(u.id): return
    await update.message.chat.send_action(ChatAction.TYPING)
    try:
        photo=update.message.photo[-1]
        tgfile=await context.bot.get_file(photo.file_id)
        image=bytes(await tgfile.download_as_bytearray())
        caption=update.message.caption or "این سؤال فیزیک را حل کن و راه‌حل مرحله‌به‌مرحله بده."
        ans=ask_ai(caption,image)
        qid=save_question(u.id,"image",caption,ans)
        kb=[[InlineKeyboardButton("👍 مفید",callback_data=f"yes:{qid}"),
             InlineKeyboardButton("👎 مفید نبود",callback_data=f"no:{qid}")],
            [InlineKeyboardButton("💬 نظر",callback_data=f"fb:{qid}")]]
        await update.message.reply_text(ans,reply_markup=InlineKeyboardMarkup(kb))
    except Exception as e:
        log.exception(e)
        await update.message.reply_text("خواندن یا حل تصویر با مشکل روبه‌رو شد. لطفاً عکس واضح‌تری بفرستید.")

async def callbacks(update, context):
    q=update.callback_query; await q.answer()
    data=q.data
    if data=="topics":
        await q.edit_message_text(TOPICS)
    elif data=="help":
        await q.edit_message_text("سؤال را متنی یا به صورت عکس واضح بفرست.")
    elif data=="about":
        await q.edit_message_text("🤖 دستیار آموزشی فیزیک متوسطه دوم\n\nپاسخ‌ها آموزشی و مرحله‌به‌مرحله‌اند.")
    elif data.startswith(("yes:","no:")):
        val=1 if data.startswith("yes:") else 0
        qid=int(data.split(":")[1]); c=conn()
        c.execute("UPDATE questions SET helpful=? WHERE id=?",(val,qid))
        c.commit(); c.close()
        await q.edit_message_text("بازخورد شما ثبت شد 🌹")
    elif data.startswith("fb:"):
        context.user_data["awaiting_feedback"]=int(data.split(":")[1])
        await q.edit_message_text("💬 لطفاً نظر یا ایراد پاسخ را در یک پیام بفرستید.")
    elif q.from_user.id==ADMIN_ID:
        if data.startswith("a_"):
            await admin_action(q,context,data)

async def admin_action(q,context,data):
    c=conn()
    if data=="a_stats":
        rows=c.execute("""SELECT kind,COUNT(*) FROM questions GROUP BY kind""").fetchall()
        text="📊 آمار\n\n" + "\n".join(f"{k}: {n}" for k,n in rows)
        await q.edit_message_text(text)
    elif data=="a_bad":
        rows=c.execute("""SELECT id,user_id,question FROM questions
                          WHERE helpful=0 ORDER BY id DESC LIMIT 10""").fetchall()
        text="⚠️ آخرین پاسخ‌های نامطلوب:\n\n"
        text += "\n\n".join(f"#{r[0]} | کاربر {r[1]}\n{r[2][:300]}" for r in rows) or "موردی نیست."
        await q.edit_message_text(text)
    elif data=="a_latest":
        rows=c.execute("""SELECT id,user_id,question FROM questions
                          ORDER BY id DESC LIMIT 10""").fetchall()
        text="📝 آخرین سؤال‌ها:\n\n"
        text += "\n\n".join(f"#{r[0]} | {r[1]}\n{r[2][:250]}" for r in rows) or "موردی نیست."
        await q.edit_message_text(text)
    elif data=="a_broadcast":
        context.user_data["broadcast"]=True
        await q.edit_message_text("📢 متن پیام همگانی را بفرستید.")
    elif data=="a_block":
        context.user_data["block_user"]=True
        await q.edit_message_text("🚫 عدد ID کاربر را بفرستید.")
    c.close()

async def admin_text(update,context):
    if update.effective_user.id!=ADMIN_ID: return False
    if context.user_data.get("broadcast"):
        context.user_data.pop("broadcast")
        msg=update.message.text
        c=conn(); ids=[r[0] for r in c.execute("SELECT user_id FROM users WHERE blocked=0")]
        c.close()
        ok=0
        for uid in ids:
            try:
                await context.bot.send_message(uid,msg); ok+=1
            except Exception: pass
        await update.message.reply_text(f"📢 پیام ارسال شد: {ok} کاربر")
        return True
    if context.user_data.get("block_user"):
        context.user_data.pop("block_user")
        try: uid=int(update.message.text.strip())
        except: await update.message.reply_text("ID معتبر نیست."); return True
        c=conn(); c.execute("UPDATE users SET blocked=1 WHERE user_id=?",(uid,)); c.commit(); c.close()
        await update.message.reply_text(f"🚫 کاربر {uid} مسدود شد.")
        return True
    return False

async def routed_text(update,context):
    if await admin_text(update,context): return
    await text_handler(update,context)

telegram_app = None
web_app = FastAPI(title="Physics Yar Bot")

def build_telegram_app():
    app=Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("help",help_cmd))
    app.add_handler(CommandHandler("admin",admin_cmd))
    app.add_handler(CallbackQueryHandler(callbacks))
    app.add_handler(MessageHandler(filters.PHOTO,photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,routed_text))
    return app

@web_app.get("/")
async def health():
    return {"status":"ok","service":"physics-yar-bot"}

@web_app.get("/health")
async def health_check():
    return {"status":"ok"}

@web_app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    global telegram_app
    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return JSONResponse({"ok": True})

@web_app.on_event("startup")
async def startup():
    global telegram_app
    init_db()
    telegram_app = build_telegram_app()
    await telegram_app.initialize()
    await telegram_app.start()
    webhook_base = os.getenv("WEBHOOK_URL") or os.getenv("RENDER_EXTERNAL_URL")
    if not webhook_base:
        raise RuntimeError("WEBHOOK_URL یا RENDER_EXTERNAL_URL تنظیم نشده است.")
    webhook_url = webhook_base.rstrip("/") + "/telegram-webhook"
    await telegram_app.bot.set_webhook(url=webhook_url)
    log.info("Telegram webhook set: %s", webhook_url)

@web_app.on_event("shutdown")
async def shutdown():
    global telegram_app
    if telegram_app:
        await telegram_app.stop()
        await telegram_app.shutdown()

if __name__=="__main__":
    import uvicorn
    port=int(os.getenv("PORT","10000"))
    uvicorn.run(web_app, host="0.0.0.0", port=port)
