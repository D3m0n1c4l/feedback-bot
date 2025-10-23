import time
import json
import os
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ===== CONFIG =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(os.getenv("ADMIN_ID"))]
TIMEOUT_SECONDS = 3600
DATA_FILE = "bot_data.json"
FEEDBACK_ADMINS = [int(os.getenv("ADMIN_ID"))]  # Admins allowed to submit feedback

# ===== STORAGE =====
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r") as f:
        data = json.load(f)
else:
    data = {"blocked_users": [], "user_last_feedback": {}, "feedback_records": {}}

blocked_users = set(data.get("blocked_users", []))
user_last_feedback = {int(k): v for k, v in data.get("user_last_feedback", {}).items()}
feedback_records = {int(k): v for k, v in data.get("feedback_records", {}).items()}


def save_data():
    with open(DATA_FILE, "w") as f:
        json.dump(
            {
                "blocked_users": list(blocked_users),
                "user_last_feedback": user_last_feedback,
                "feedback_records": feedback_records,
            },
            f,
            indent=2,
        )


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ===== USER MENU =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    buttons = [
        [InlineKeyboardButton("💬 Send Feedback", callback_data="send_feedback")],
        [InlineKeyboardButton("📊 My Last Feedback", callback_data="view_last")],
        [InlineKeyboardButton("❓ Help", callback_data="help")],
    ]

    if is_admin(user_id):
        buttons.append([InlineKeyboardButton("🛠 Admin Panel", callback_data="admin_panel")])
        buttons.append([InlineKeyboardButton("📊 View Average Rating", callback_data="view_avg_rating")])
        buttons.append([InlineKeyboardButton("✉️ Submit Feedback (as user)", callback_data="send_feedback")])

    markup = InlineKeyboardMarkup(buttons)
    await update.message.reply_text("👋 Welcome! Choose an option below:", reply_markup=markup)


# ===== USER BUTTONS =====
async def handle_user_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id

    if data == "help":
        await query.message.reply_text(
            "📘 *Feedback Bot Help*\n\n"
            "⭐ Rate your experience (1–5 stars)\n"
            "💬 Then type your feedback.\n"
            "🕒 You can submit feedback once every hour.\n"
            "🚫 If you are blocked, you won’t be able to send new feedback.",
            parse_mode="Markdown",
        )
    elif data == "view_last":
        last = feedback_records.get(user_id)
        if last:
            text = last.get("text", "No text")
            rating = last.get("rating", "No rating")
            await query.message.reply_text(f"🗒️ *Your last feedback:*\n⭐ {rating}\n{text}", parse_mode="Markdown")
        else:
            await query.message.reply_text("ℹ️ You haven’t sent any feedback yet.")
    elif data == "send_feedback":
        # Check blocked
        if user_id in blocked_users:
            await query.message.reply_text("🚫 You are blocked from sending feedback.")
            return
        # Check cooldown
        last_time = user_last_feedback.get(user_id, 0)
        now = time.time()
        if now - last_time < TIMEOUT_SECONDS:
            remaining = int((TIMEOUT_SECONDS - last_time) / 60)
            await query.message.reply_text(f"⏳ Please wait {remaining} more minutes before sending again.")
            return
        # Ask rating
        buttons = [[InlineKeyboardButton(f"⭐ {i}", callback_data=f"rate_{i}") for i in range(1,6)]]
        markup = InlineKeyboardMarkup(buttons)
        await query.message.reply_text("⭐ Please rate your experience (1–5):", reply_markup=markup)
    elif data == "admin_panel":
        await show_admin_panel(update, context)
    elif data == "view_avg_rating":
        await show_avg_rating(update, context)


# ===== RATING SELECTION =====
async def handle_rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    rating = int(query.data.split("_")[1])
    context.user_data["rating"] = rating
    context.user_data["awaiting_feedback"] = True
    await query.message.reply_text(f"✅ Rating saved: {rating}⭐\nNow please type your feedback below.")


# ===== FEEDBACK TEXT =====
async def handle_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    user_id = user.id

    # Only allow admins in FEEDBACK_ADMINS or normal users
    if is_admin(user_id) and user_id not in FEEDBACK_ADMINS:
        return

    if not context.user_data.get("awaiting_feedback"):
        return

    # Check blocked
    if user_id in blocked_users:
        await update.message.reply_text("🚫 You are blocked from sending feedback.")
        return

    # Check cooldown
    now = time.time()
    last_time = user_last_feedback.get(user_id, 0)
    if now - last_time < TIMEOUT_SECONDS:
        remaining = int((TIMEOUT_SECONDS - last_time) / 60)
        await update.message.reply_text(f"⏳ Please wait {remaining} more minutes.")
        return

    feedback_text = update.message.text
    rating = context.user_data.get("rating", "N/A")
    user_last_feedback[user_id] = now
    feedback_records[user_id] = {"text": feedback_text, "rating": rating}
    context.user_data["awaiting_feedback"] = False
    context.user_data["rating"] = None
    save_data()

    await update.message.reply_text("✅ Thanks for your feedback!")

    for admin_id in ADMIN_IDS:
        buttons = [
            [
                InlineKeyboardButton("💬 Reply", callback_data=f"reply:{user_id}"),
                InlineKeyboardButton("🚫 Block", callback_data=f"block:{user_id}"),
                InlineKeyboardButton("❌ Ignore", callback_data="ignore"),
            ]
        ]
        markup = InlineKeyboardMarkup(buttons)
        msg = (
            f"📬 *New feedback received!*\n\n"
            f"👤 From: @{user.username or user.first_name}\n"
            f"🆔 ID: `{user_id}`\n"
            f"⭐ Rating: {rating}\n\n"
            f"💬 Message:\n{feedback_text}"
        )
        await update.bot.send_message(chat_id=admin_id, text=msg, parse_mode="Markdown", reply_markup=markup)


# ===== ADMIN PANEL =====
async def show_admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
    buttons = [
        [InlineKeyboardButton("📋 View Blocked Users", callback_data="view_blocked")],
        [InlineKeyboardButton("🧹 Clear Feedback Records", callback_data="clear_feedback")],
    ]
    markup = InlineKeyboardMarkup(buttons)
    if query:
        await query.message.reply_text("🛠️ *Admin Panel*", parse_mode="Markdown", reply_markup=markup)
    else:
        await update.message.reply_text("🛠️ *Admin Panel*", parse_mode="Markdown", reply_markup=markup)


async def show_avg_rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ratings = [v.get("rating", 0) for v in feedback_records.values() if isinstance(v, dict)]
    if ratings:
        avg = sum(ratings)/len(ratings)
        await update.callback_query.message.reply_text(f"⭐ Average Rating: {avg:.2f} / 5 ({len(ratings)} submissions)")
    else:
        await update.callback_query.message.reply_text("ℹ️ No ratings yet.")


# ===== ADMIN ACTIONS =====
async def handle_admin_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    if not is_admin(user_id):
        await query.answer("❌ Unauthorized.", show_alert=True)
        return

    data = query.data

    if data == "ignore":
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text("✅ Ignored this feedback.")
    elif data.startswith("block:"):
        target_id = int(data.split(":")[1])
        blocked_users.add(target_id)
        save_data()
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(f"🚫 User {target_id} has been blocked.")
        try:
            await context.bot.send_message(chat_id=target_id, text="🚫 You’ve been blocked from sending feedback.")
        except Exception:
            pass
    elif data.startswith("reply:"):
        target_id = int(data.split(":")[1])
        context.user_data["reply_to"] = target_id
        await query.message.reply_text(f"✏️ Type your reply for user `{target_id}`:", parse_mode="Markdown")
        await query.edit_message_reply_markup(reply_markup=None)
    elif data == "view_blocked":
        if not blocked_users:
            await query.message.reply_text("✅ No users are currently blocked.")
        else:
            users = "\n".join(str(uid) for uid in blocked_users)
            await query.message.reply_text(f"🚫 *Blocked users:*\n{users}", parse_mode="Markdown")
    elif data == "clear_feedback":
        feedback_records.clear()
        save_data()
        await query.message.reply_text("🧹 Cleared all feedback records.")


async def admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    if "reply_to" not in context.user_data:
        return

    target_id = context.user_data.pop("reply_to")
    reply_text = update.message.text

    try:
        await context.bot.send_message(chat_id=target_id, text=f"📢 *Admin reply:*\n{reply_text}", parse_mode="Markdown")
        await update.message.reply_text(f"✅ Reply sent to {target_id}")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Could not send reply: {e}")


# ===== MAIN =====
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # User menu + feedback
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_user_buttons, pattern="^(send_feedback|view_last|help|admin_panel|view_avg_rating)$"))
    app.add_handler(CallbackQueryHandler(handle_rating, pattern="^rate_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_feedback))

    # Admin panel actions
    app.add_handler(CallbackQueryHandler(handle_admin_action, pattern="^(ignore|block:|reply:|view_blocked|clear_feedback)$"))
    app.add_handler(MessageHandler(filters.TEXT & filters.Chat(ADMIN_IDS), admin_reply))

    print("📨 Feedback bot with rating & admin menu is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
