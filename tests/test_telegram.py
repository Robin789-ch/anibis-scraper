import io
import unittest
from unittest.mock import patch

from anibis_deals.telegram import TelegramError, deal_plot, send_message


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class Figure:
    def savefig(self, target, **kwargs):
        target.write(b"PNG DATA")


class TelegramBotTest(unittest.TestCase):
    @patch("anibis_deals.telegram.urlopen")
    def test_sends_formatted_photo_notification(self, urlopen) -> None:
        urlopen.return_value = Response(b'{"ok": true, "result": {"message_id": 42}}')

        result = send_message(
            "MacBook Pro <14-inch> · M3 Pro · 18 GB RAM",
            1190,
            1650,
            "https://www.anibis.ch/listing?a=1&b=2",
            Figure(),
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
                send_message("MacBook Air", 700, 900, "https://example.com", object())

    def test_deal_plot_can_be_rendered(self) -> None:
        from matplotlib import pyplot as plt

        figure = deal_plot(1_650, 1_190)
        output = io.BytesIO()
        figure.savefig(output, format="png")
        self.assertTrue(output.getvalue().startswith(b"\x89PNG"))
        plt.close(figure)


if __name__ == "__main__":
    unittest.main()
