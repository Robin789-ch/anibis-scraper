"""Send a formatted good-buy notification through the Telegram Bot API."""

from __future__ import annotations

import html
import io
import json
import math
import mimetypes
import os
import random
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any, BinaryIO, Protocol, TypeAlias
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from dotenv import load_dotenv

load_dotenv()


class FigureLike(Protocol):
    def savefig(self, target: BinaryIO, **kwargs: Any) -> None: ...


Image: TypeAlias = str | Path | bytes | bytearray | BinaryIO | FigureLike
ImageSource: TypeAlias = Image | Callable[[], Image]


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


def _image_bytes(image: ImageSource) -> tuple[bytes, str, str]:
    value = image() if callable(image) else image
    if isinstance(value, (str, Path)):
        path = Path(value)
        return (
            path.read_bytes(),
            path.name,
            mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        )
    if isinstance(value, (bytes, bytearray)):
        return bytes(value), "deal.png", "image/png"
    if hasattr(value, "savefig"):
        output = io.BytesIO()
        value.savefig(output, format="png", dpi=160, bbox_inches="tight")
        return output.getvalue(), "deal.png", "image/png"
    if hasattr(value, "read"):
        data = value.read()
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("image file must be opened in binary mode")
        return bytes(data), "deal.png", "image/png"
    raise TypeError("image must be a path, bytes, binary file, figure, or callable")


def _multipart(fields: dict[str, str], image: ImageSource) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    marker = f"--{boundary}\r\n".encode()
    body = bytearray()
    for name, value in fields.items():
        body.extend(marker)
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.extend(value.encode())
        body.extend(b"\r\n")

    data, filename, content_type = _image_bytes(image)
    body.extend(marker)
    body.extend(
        (
            'Content-Disposition: form-data; name="photo"; '
            f'filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n'
        ).encode()
    )
    body.extend(data)
    body.extend(f"\r\n--{boundary}--\r\n".encode())
    return bytes(body), boundary


def send_message(
    specs: str,
    price: float,
    expectedPrice: float,
    url: str,
    image: ImageSource,
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
    expected_price = float(expectedPrice)
    if not all(math.isfinite(value) and value >= 0 for value in (price, expected_price)):
        raise ValueError("price and expectedPrice must be finite, non-negative numbers")
    if urlsplit(url).scheme not in {"http", "https"} or not urlsplit(url).netloc:
        raise ValueError("url must be an absolute HTTP(S) URL")

    body, boundary = _multipart(
        {
            "chat_id": chat_id,
            "caption": _caption(specs.strip(), price, expected_price, url),
            "parse_mode": "HTML",
        },
        image,
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


def dummy_plot(expected_price: float = 1_650, actual_price: float = 1_190) -> Any:
    """Return a Matplotlib figure populated with deterministic dummy prices."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rng = random.Random(7)
    expected = [10 ** rng.uniform(2.55, 3.65) for _ in range(75)]
    actual = [value * math.exp(rng.gauss(0, 0.17)) for value in expected]

    figure, axis = plt.subplots(figsize=(8, 6))
    axis.scatter(expected, actual, color="#8793a6", alpha=0.8, label="Market range")
    axis.scatter(
        [expected_price],
        [actual_price],
        color="#d94a62",
        s=70,
        zorder=3,
        label="This good buy",
    )
    bounds = (250, 5_000)
    axis.plot(bounds, bounds, "--", color="#173a5e", label="Expected = asking")
    axis.set(xscale="log", yscale="log", xlim=bounds, ylim=bounds)
    axis.set_title("Actual asking price versus model expectation")
    axis.set_xlabel("Expected asking price (CHF)")
    axis.set_ylabel("Actual asking price (CHF)")
    axis.grid(True, color="#d3d3d3")
    axis.legend(loc="upper left")
    figure.tight_layout()
    return figure


if __name__ == "__main__":
    send_message(
        specs="MacBook Pro 14-inch · M3 Pro · 18 GB RAM · 512 GB SSD",
        price=1_190,
        expectedPrice=1_650,
        url="https://www.anibis.ch/",
        image=lambda: dummy_plot(1_650, 1_190),
    )
