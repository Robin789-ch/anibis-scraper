"""Send formatted prospect notifications through the Telegram Bot API."""

import html
import io
import json
import math
import os
import sqlite3
import uuid
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from dotenv import load_dotenv

load_dotenv()


class TelegramError(RuntimeError):
    """A readable Telegram notification failure."""


def _format_chf(value: float) -> str:
    decimals = 0 if value.is_integer() else 2
    return f"CHF {value:,.{decimals}f}".replace(",", "’")


def _caption(specs: str, price: float, expected_price: float, url: str) -> str:
    return (
        "<b>🔥 Good MacBook deal</b>\n\n"
        f"<b>Model</b>\n{html.escape(specs)}\n\n"
        f"<b>Price:</b> {_format_chf(price)}\n"
        f"<b>Expected price:</b> {_format_chf(expected_price)}\n"
        f'<a href="{html.escape(url, quote=True)}">View listing on Anibis →</a>'
    )


def _multipart(fields: dict[str, str], figure: Any) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    marker = f"--{boundary}\r\n".encode()
    body = bytearray()
    for name, value in fields.items():
        body.extend(marker)
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(value.encode())
        body.extend(b"\r\n")

    output = io.BytesIO()
    figure.savefig(output, format="png", dpi=160, bbox_inches="tight")
    body.extend(marker)
    body.extend(
        (
            'Content-Disposition: form-data; name="photo"; '
            'filename="deal.png"\r\nContent-Type: image/png\r\n\r\n'
        ).encode()
    )
    body.extend(output.getvalue())
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    return bytes(body), boundary


def send_message(
    specs: str,
    price: float,
    expected_price: float,
    url: str,
    figure: Any,
    *,
    bot_token: str | None = None,
    chat_id: str | None = None,
    timeout: float = 30,
) -> dict[str, Any]:
    """Send one photo notification and return Telegram's response payload.

    ``bot_token`` and ``chat_id`` default to the ``TELEGRAM_BOT_TOKEN`` and
    ``TELEGRAM_CHAT_ID`` environment variables.
    """
    bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        raise TelegramError("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID before sending")
    if not specs.strip():
        raise ValueError("specs must not be empty")
    price = float(price)
    expected_price = float(expected_price)
    if not all(math.isfinite(value) and value >= 0 for value in (price, expected_price)):
        raise ValueError("prices must be finite, non-negative numbers")
    if urlsplit(url).scheme not in {"http", "https"} or not urlsplit(url).netloc:
        raise ValueError("url must be an absolute HTTP(S) URL")

    body, boundary = _multipart(
        {
            "chat_id": chat_id,
            "caption": _caption(specs.strip(), price, expected_price, url),
            "parse_mode": "HTML",
        },
        figure,
    )
    request = Request(
        f"https://api.telegram.org/bot{bot_token}/sendPhoto",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except HTTPError as error:
        try:
            detail = json.loads(error.read()).get("description", f"HTTP {error.code}")
        except json.JSONDecodeError, AttributeError:
            detail = f"HTTP {error.code}"
        raise TelegramError(f"Telegram rejected the notification: {detail}") from error
    except URLError as error:
        raise TelegramError(f"Could not reach Telegram: {error.reason}") from error

    if not payload.get("ok"):
        raise TelegramError(
            f"Telegram rejected the notification: {payload.get('description', 'unknown error')}"
        )
    return payload


def deal_plot(expected_price: float, actual_price: float) -> Any:
    """Return a compact expected-versus-asking-price figure."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(7, 3))
    bars = axis.barh(
        ["Asking price", "Model expectation"],
        [actual_price, expected_price],
        color=["#d94a62", "#173a5e"],
    )
    axis.bar_label(bars, labels=[_format_chf(actual_price), _format_chf(expected_price)])
    axis.set(title="Anibis asking price versus model expectation", xlabel="CHF")
    axis.spines[["top", "right", "left"]].set_visible(False)
    figure.tight_layout()
    return figure


def _specs(prospect: dict[str, Any]) -> str:
    family = prospect["familyCPU"]
    chip = prospect["generationCPU"] + (f" {family}" if family != "Base" else "")
    return (
        f"MacBook {prospect['serie']} {prospect['screenSize']}-inch · {chip} · "
        f"{prospect['RAM']} GB RAM · {prospect['storageGB']:g} GB SSD"
    )


def notify_new_prospects(database: Path, prospects: Iterable[dict[str, Any]]) -> int:
    """Notify prospects not previously sent and remember each successful send."""
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS notifications (
                listingID TEXT PRIMARY KEY,
                notifiedAt TEXT NOT NULL
            )
            """
        )
        connection.commit()
        notified = {
            row[0] for row in connection.execute("SELECT listingID FROM notifications")
        }
        sent = 0
        for prospect in prospects:
            listing_id = str(prospect["listingID"])
            if listing_id in notified:
                continue
            expected_price = float(prospect["expectedPrice"])
            actual_price = float(prospect["price"])
            figure = deal_plot(expected_price, actual_price)
            try:
                send_message(
                    _specs(prospect),
                    actual_price,
                    expected_price,
                    prospect["url"],
                    figure,
                )
            finally:
                from matplotlib import pyplot as plt

                plt.close(figure)
            connection.execute(
                "INSERT INTO notifications VALUES (?, ?)",
                (listing_id, datetime.now(UTC).isoformat()),
            )
            connection.commit()
            sent += 1
        return sent
