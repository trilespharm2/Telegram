from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail
from bot.config import SENDGRID_API_KEY, FROM_EMAIL

def send_activation_email(to_email, activation_code, transaction_id, invite_link):
    html_content = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: auto;">
        <h2>🎉 Welcome! Your Subscription is Confirmed</h2>
        <div style="background: #f4f4f4; padding: 20px; border-radius: 8px; margin: 20px 0;">
            <p><strong>Activation Code:</strong></p>
            <h1 style="color: #2c3e50; letter-spacing: 4px;">{activation_code}</h1>
            <p><strong>Transaction ID:</strong> {transaction_id}</p>
        </div>
        <p><strong>Your Private Channel Access Link:</strong></p>
        <a href="{invite_link}" style="background: #0088cc; color: white; padding: 12px 24px;
           text-decoration: none; border-radius: 6px; display: inline-block;">
            Join Private Channel
        </a>
        <p style="color: #666; font-size: 12px; margin-top: 30px;">
            Save your activation code and transaction ID for future access.
        </p>
    </div>
    """
    message = Mail(from_email=FROM_EMAIL, to_emails=to_email,
                   subject="✅ Your Premium Access — Activation Code Inside",
                   html_content=html_content)
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        sg.send(message)
    except Exception as e:
        print(f"Error sending email: {e}")

def send_cancellation_email(to_email):
    html_content = """
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: auto;">
        <h2>Subscription Cancelled</h2>
        <p>Your subscription has been successfully cancelled.</p>
        <p>You will retain access until the end of your current billing period.</p>
    </div>
    """
    message = Mail(from_email=FROM_EMAIL, to_emails=to_email,
                   subject="Subscription Cancellation Confirmed",
                   html_content=html_content)
    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        sg.send(message)
    except Exception as e:
        print(f"Error sending cancellation email: {e}")
