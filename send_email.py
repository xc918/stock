"""Email the generated brief through Yahoo SMTP."""

import os
import smtplib
import ssl
import sys
from datetime import datetime
from email.message import EmailMessage
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
SMTP_HOST = "smtp.mail.yahoo.com"
SMTP_PORT = 465

YAHOO_USER = os.environ["YAHOO_USER"]
YAHOO_APP_PASSWORD = os.environ["YAHOO_APP_PASSWORD"]
MAIL_TO = os.environ.get("MAIL_TO", YAHOO_USER)
SUBJECT_PREFIX = os.environ.get("SUBJECT_PREFIX", "Market Brief")
SLOT = os.environ.get("SLOT", "open")
SLOT_LABEL = {"open": "Open 9:30", "midday": "Midday 12:00", "afternoon": "Afternoon 2:30"}


def attach(msg, path):
    with open(path, "rb") as f:
        data = f.read()
    name = os.path.basename(path)
    subtype = "markdown" if name.endswith(".md") else "csv"
    msg.add_attachment(data, maintype="text", subtype=subtype, filename=name)


def main(paths):
    md_path = paths[0]
    with open(md_path) as f:
        body = f.read()

    msg = EmailMessage()
    label = SLOT_LABEL.get(SLOT, SLOT)
    msg["Subject"] = f"{SUBJECT_PREFIX} — {datetime.now(ET):%Y-%m-%d} — {label} ET"
    msg["From"] = YAHOO_USER
    msg["To"] = MAIL_TO
    msg.set_content(body)
    for path in paths:
        attach(msg, path)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
        server.login(YAHOO_USER, YAHOO_APP_PASSWORD)
        server.send_message(msg)
    print(f"sent to {MAIL_TO} with {len(paths)} attachment(s)")


if __name__ == "__main__":
    main(sys.argv[1:])
