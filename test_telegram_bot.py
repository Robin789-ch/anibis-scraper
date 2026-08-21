import io
import unittest
from unittest.mock import patch

from telegram_bot import TelegramError, dummy_plot, send_message


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class TelegramBotTest(unittest.TestCase):
    @patch("telegram_bot.urlopen")
    def test_sends_formatted_photo_notification(self, urlopen) -> None:
        urlopen.return_value = Response(b'{"ok": true, "result": {"message_id": 42}}')

        result = send_message(
            "MacBook Pro <14-inch> · M3 Pro · 18 GB RAM",
            1190,
            1650,
            "https://www.anibis.ch/listing?a=1&b=2",
            lambda: b"PNG DATA",
            bot_token="secret",
            chat_id="123",
        )

        request = urlopen.call_args.args[0]
        body = request.data
        self.assertEqual(result["result"]["message_id"], 42)
        self.assertEqual(request.full_url, "https://api.telegram.org/botsecret/sendPhoto")
        self.assertIn(b"MacBook Pro &lt;14-inch&gt;", body)
        self.assertIn(b"CHF 1\xe2\x80\x99190", body)
        self.assertIn(b"View listing on Anibis", body)
        self.assertIn(b"PNG DATA", body)

    def test_requires_credentials_before_rendering_image(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(TelegramError, "TELEGRAM_BOT_TOKEN"):
                send_message("MacBook Air", 700, 900, "https://example.com", b"png")

    def test_dummy_plot_can_be_rendered(self) -> None:
        from matplotlib import pyplot as plt

        figure = dummy_plot()
        output = io.BytesIO()
        figure.savefig(output, format="png")
        self.assertTrue(output.getvalue().startswith(b"\x89PNG"))
        plt.close(figure)


if __name__ == "__main__":
    unittest.main()
