from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from bot.config import SENDGRID_API_KEY, FROM_EMAIL, ADMIN_ID
import os

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", FROM_EMAIL)

def _send(to_email: str, subject: str, html_content: str):
    """Internal helper to send email via SendGrid."""
    message = Mail(
        from_email=FROM_EMAIL,
        to_emails=to_email,
        subject=subject,
        html_content=html_content
    )
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        sg.send(message)
        print(f"Email sent to {to_email}: {subject}")
    except Exception as e:
        print(f"Error sending email to {to_email}: {e}")


def send_activation_email(to_email: str, activation_code: str,
                           transaction_id: str, invite_link: str):
    """Send activation code and channel link to subscriber's email."""
    html_content = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: auto;">
        <h2>🎉 Welcome! Your Subscription is Confirmed</h2>
        <p>Thank you for subscribing. Here are your access details — save these:</p>

        <div style="background: #f4f4f4; padding: 20px; border-radius: 8px; margin: 20px 0;">
            <p><strong>Activation Code:</strong></p>
            <h1 style="color: #2c3e50; letter-spacing: 4px;">{activation_code}</h1>
            <p><strong>Transaction ID:</strong> {transaction_id}</p>
        </div>

        <p><strong>Your Private Channel Access Link:</strong></p>
        <a href="{invite_link}" style="background: #0088cc; color: white;
           padding: 12px 24px; text-decoration: none; border-radius: 6px;
           display: inline-block; margin: 10px 0;">
            Join Private Channel
        </a>

        <hr style="margin: 30px 0;">
        <p style="color: #666; font-size: 12px;">
            Save your activation code and transaction ID — you will need them
            to access the bot and manage your subscription.<br><br>
            If you did not make this purchase, please contact support immediately.
        </p>
    </div>
    """
    _send(to_email, "✅ Your Premium Access — Activation Code Inside", html_content)


def send_cancellation_email(to_email: str):
    """Send cancellation confirmation email to subscriber."""
    html_content = """
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: auto;">
        <h2>Subscription Cancelled</h2>
        <p>Your subscription has been successfully cancelled.</p>
        <p>You have been removed from the private channel.</p>
        <p>We hope to see you again. You can resubscribe anytime through our Telegram bot.</p>
        <hr style="margin: 30px 0;">
        <p style="color: #666; font-size: 12px;">
            If you believe this was a mistake, please contact support.
        </p>
    </div>
    """
    _send(to_email, "Subscription Cancellation Confirmed", html_content)


def send_inquiry_email(from_email: str, username: str, telegram_id: int, message: str):
    """Forward user inquiry to admin email."""
    html_content = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: auto;">
        <h2>📩 New Inquiry from Premium Bot</h2>
        <table style="width: 100%; border-collapse: collapse;">
            <tr>
                <td style="padding: 8px; font-weight: bold;">From:</td>
                <td style="padding: 8px;">@{username} (Telegram ID: {telegram_id})</td>
            </tr>
            <tr style="background: #f9f9f9;">
                <td style="padding: 8px; font-weight: bold;">Email:</td>
                <td style="padding: 8px;">{from_email}</td>
            </tr>
        </table>
        <div style="background: #f4f4f4; padding: 20px; border-radius: 8px; margin: 20px 0;">
            <p><strong>Message:</strong></p>
            <p>{message}</p>
        </div>
        <p style="color: #666; font-size: 12px;">
            Reply to this email or contact the user directly on Telegram.
        </p>
    </div>
    """
    _send(ADMIN_EMAIL, f"📩 New Inquiry from @{username}", html_content)


def send_login_credentials_email(to_email: str, username: str):
    """Send login username reminder to subscriber's email."""
    html_content = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: auto;">
        <h2>🔑 Your Login Credentials</h2>
        <p>You requested your login details for Premium Access.</p>

        <div style="background: #f4f4f4; padding: 20px; border-radius: 8px; margin: 20px 0;">
            <p><strong>Username:</strong></p>
            <h2 style="color: #2c3e50; letter-spacing: 2px;">{username}</h2>
        </div>

        <p style="color: #666;">
            For security reasons, your password cannot be sent via email.<br>
            If you have also forgotten your password, please contact support
            via the bot's Help → Write Inquiry option.
        </p>
        <hr style="margin: 30px 0;">
        <p style="color: #999; font-size: 12px;">
            If you did not request this, please ignore this email.
        </p>
    </div>
    """
    _send(to_email, "🔑 Your Premium Bot Login Details", html_content)
