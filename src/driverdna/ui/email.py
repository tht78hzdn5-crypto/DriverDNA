import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def send_reset_email(host: str, port: int, user: str, password: str, to_email: str, reset_link: str) -> None:
    msg = MIMEMultipart()
    msg['From'] = "noreply@driverdna.com"
    msg['To'] = to_email
    msg['Subject'] = "Password Reset - DriverDNA"

    body = f"""Hello,

You requested a password reset for DriverDNA. Please click the link below to set a new password:

{reset_link}

If you did not request this, please ignore this email.
    """
    msg.attach(MIMEText(body, 'plain'))

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.send_message(msg)
