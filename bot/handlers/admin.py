from datetime import datetime
from telegram import Update, Chat
from telegram.ext import ContextTypes, CommandHandler, ChatMemberHandler
from telegram.constants import ChatMemberStatus
from bot.config import ADMIN_ID, CHANNEL_ID
from bot.database import (get_conn, get_all_channel_members,
                           upsert_channel_member, mark_member_removed)

def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != ADMIN_ID:
            return
        return await func(update, context)
    return wrapper


async def track_channel_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Fires whenever someone joins or leaves the channel.
    Tracks ALL accounts — including those who joined via forwarded links.
    """
    result = update.chat_member
    if not result:
        return

    # Only track our private channel
    if result.chat.id != CHANNEL_ID:
        return

    member = result.new_chat_member
    user = member.user
    telegram_id = user.id
    username = user.username or ""
    first_name = user.first_name or ""

    # Check if this user is in our database
    conn = get_conn()
    in_db = conn.execute(
        "SELECT id FROM subscribers WHERE telegram_id = ?", (telegram_id,)
    ).fetchone()
    conn.close()
    in_database = in_db is not None

    joined_statuses = {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER}
    left_statuses = {ChatMemberStatus.LEFT, ChatMemberStatus.BANNED, ChatMemberStatus.RESTRICTED}

    if member.status in joined_statuses:
        upsert_channel_member(telegram_id, username, first_name, in_database)

        # Alert admin if unrecognized account joins
        if not in_database:
            try:
                name_display = f"@{username}" if username else first_name
                await context.bot.send_message(
                    chat_id=ADMIN_ID,
                    text=f"⚠️ *Unrecognized Account Joined Channel*\n\n"
                         f"Name: {name_display}\n"
                         f"Telegram ID: `{telegram_id}`\n\n"
                         f"This account has no active subscription in the database.\n"
                         f"They may have joined via a forwarded invite link.\n\n"
                         f"Use /kick {telegram_id} to remove them.",
                    parse_mode="Markdown"
                )
            except Exception as e:
                print(f"Error alerting admin: {e}")

    elif member.status in left_statuses:
        mark_member_removed(telegram_id)


@admin_only
async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: /stats — quick subscriber summary."""
    conn = get_conn()
    active_monthly = conn.execute(
        "SELECT COUNT(*) as cnt FROM subscribers WHERE is_active = 1 "
        "AND stripe_subscription_id != '' AND stripe_subscription_id IS NOT NULL"
    ).fetchone()["cnt"]
    active_one_month = conn.execute(
        "SELECT COUNT(*) as cnt FROM subscribers WHERE is_active = 1 "
        "AND (stripe_subscription_id = '' OR stripe_subscription_id IS NULL)"
    ).fetchone()["cnt"]
    total_cancelled = conn.execute(
        "SELECT COUNT(*) as cnt FROM subscribers WHERE is_active = 0"
    ).fetchone()["cnt"]
    total_in_channel = conn.execute(
        "SELECT COUNT(*) as cnt FROM channel_members WHERE in_channel = 1"
    ).fetchone()["cnt"]
    unrecognized = conn.execute(
        "SELECT COUNT(*) as cnt FROM channel_members WHERE in_channel = 1 AND in_database = 0"
    ).fetchone()["cnt"]
    conn.close()

    warning = f"\n⚠️ *{unrecognized} unrecognized account(s) in channel!* Use /members to review." if unrecognized else ""

    await update.message.reply_text(
        f"📊 *Quick Stats*\n\n"
        f"🔄 Active Monthly Subscribers: *{active_monthly}*\n"
        f"📅 Active One Month Access: *{active_one_month}*\n"
        f"✅ Total Active: *{active_monthly + active_one_month}*\n\n"
        f"❌ Cancelled: *{total_cancelled}*\n\n"
        f"👥 Accounts in Channel: *{total_in_channel}*"
        f"{warning}",
        parse_mode="Markdown"
    )


@admin_only
async def members_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: /members — all accounts currently in channel."""
    members = get_all_channel_members()

    if not members:
        await update.message.reply_text(
            "👥 *Channel Members*\n\nNo members tracked yet.\n\n"
            "_Note: tracking starts from when this update was deployed. "
            "Use /audit to check existing members._",
            parse_mode="Markdown"
        )
        return

    conn = get_conn()
    lines = [f"👥 *All Accounts in Channel* ({len(members)} total)\n"]

    for m in members:
        tid = m["telegram_id"]
        uname = f"@{m['username']}" if m["username"] else m["first_name"] or "Unknown"
        joined = ""
        try:
            joined = datetime.fromisoformat(m["joined_at"]).strftime("%b %d, %Y")
        except Exception:
            pass

        # Check database status
        sub = conn.execute(
            "SELECT is_active, email FROM subscribers WHERE telegram_id = ?", (tid,)
        ).fetchone()

        if not sub:
            status = "⚠️ NOT IN DATABASE"
        elif sub["is_active"]:
            status = f"✅ Active — {sub['email']}"
        else:
            status = f"❌ Cancelled — {sub['email']}"

        lines.append(f"\n{uname}\n🆔 `{tid}`\n📅 Joined: {joined}\n{status}")
        lines.append("─────────────────")

    conn.close()

    message = "\n".join(lines)
    if len(message) > 4000:
        chunks = []
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) > 3800:
                chunks.append(chunk)
                chunk = line + "\n"
            else:
                chunk += line + "\n"
        if chunk:
            chunks.append(chunk)
        for chunk in chunks:
            await update.message.reply_text(chunk, parse_mode="Markdown")
    else:
        await update.message.reply_text(message, parse_mode="Markdown")


@admin_only
async def subscribers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: /subscribers — all database subscribers."""
    conn = get_conn()
    active = conn.execute(
        "SELECT * FROM subscribers WHERE is_active = 1 ORDER BY subscribed_at DESC"
    ).fetchall()
    total_cancelled = conn.execute(
        "SELECT COUNT(*) as cnt FROM subscribers WHERE is_active = 0"
    ).fetchone()["cnt"]
    conn.close()

    if not active:
        await update.message.reply_text(
            f"📊 *Subscriber Report*\n\nActive: 0\nCancelled: {total_cancelled}",
            parse_mode="Markdown"
        )
        return

    lines = [
        f"📊 *Subscriber Report*\n",
        f"✅ Active: {len(active)}  |  ❌ Cancelled: {total_cancelled}\n",
        "─────────────────────"
    ]

    for sub in active:
        email = sub["email"] or "N/A"
        telegram_id = sub["telegram_id"] or "N/A"
        username = sub["username"] or "—"
        stripe_sub_id = (sub["stripe_subscription_id"] or "").strip()
        plan = "🔄 Monthly" if stripe_sub_id else "📅 One Month"
        try:
            exp_date = datetime.fromisoformat(sub["expires_at"]).strftime("%b %d, %Y")
        except Exception:
            exp_date = "N/A"

        lines.append(
            f"\n{plan}\n"
            f"📧 {email}\n"
            f"🆔 `{telegram_id}`\n"
            f"👤 Login: {username}\n"
            f"⏳ Expires: {exp_date}"
        )
        lines.append("─────────────────────")

    message = "\n".join(lines)
    if len(message) > 4000:
        chunks = []
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) > 3800:
                chunks.append(chunk)
                chunk = line + "\n"
            else:
                chunk += line + "\n"
        if chunk:
            chunks.append(chunk)
        for chunk in chunks:
            await update.message.reply_text(chunk, parse_mode="Markdown")
    else:
        await update.message.reply_text(message, parse_mode="Markdown")


@admin_only
async def kick_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: /kick <telegram_id> — remove unrecognized user from channel."""
    if not context.args:
        await update.message.reply_text("Usage: /kick <telegram_id>")
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid Telegram ID.")
        return

    try:
        await context.bot.ban_chat_member(chat_id=CHANNEL_ID, user_id=target_id)
        mark_member_removed(target_id)
        await update.message.reply_text(
            f"✅ User `{target_id}` has been removed and banned from the channel.",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to remove user: {e}")


@admin_only
async def audit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Admin command: /audit — cross-check channel members vs database.
    Checks all known subscribers and flags cancelled ones still in channel.
    """
    await update.message.reply_text("🔍 Running audit, please wait...")

    conn = get_conn()
    all_subs = conn.execute("SELECT * FROM subscribers").fetchall()
    conn.close()

    issues = []
    for sub in all_subs:
        tid = sub["telegram_id"]
        if not tid:
            continue
        try:
            member = await context.bot.get_chat_member(chat_id=CHANNEL_ID, user_id=tid)
            still_in = member.status in (
                ChatMemberStatus.MEMBER,
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.OWNER
            )
            if still_in and not sub["is_active"]:
                issues.append(
                    f"⚠️ Cancelled but still in channel:\n"
                    f"📧 {sub['email']}\n🆔 `{tid}`\n"
                    f"Use /kick {tid} to remove."
                )
        except Exception:
            pass

    if not issues:
        await update.message.reply_text(
            "✅ *Audit Complete*\n\nNo issues found. All cancelled subscribers have been removed from the channel.",
            parse_mode="Markdown"
        )
    else:
        report = "⚠️ *Audit Found Issues:*\n\n" + "\n\n".join(issues)
        await update.message.reply_text(report, parse_mode="Markdown")
