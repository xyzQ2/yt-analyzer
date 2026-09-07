"""Render the daily HTML report and optionally email it."""

import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"


def render_report(context: dict, output_path: str) -> None:
    """Render report.html to output_path. Autoescape is on: captions are hostile input."""
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)
    html = env.get_template("report.html").render(**context)
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    logger.info("report written to %s", path)


def send_email(html: str, subject: str, cfg: dict) -> bool:
    """Send the report. Returns False on any failure — never fails the daily run."""
    if not cfg.get("enabled"):
        logger.info("email disabled, skipping send")
        return False

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.get("user", "")
    msg["To"] = cfg.get("to", "")
    msg.set_content("HTML report attached inline.")
    msg.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(cfg["host"], int(cfg["port"]), timeout=30) as smtp:
            smtp.starttls()
            smtp.login(cfg["user"], cfg["password"])
            smtp.send_message(msg)
        logger.info("report emailed to %s", cfg.get("to"))
        return True
    except Exception as exc:
        logger.error("email send failed (report still on disk): %s", exc)
        return False
