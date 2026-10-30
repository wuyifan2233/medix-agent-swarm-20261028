"""Render a WeChat login link as a PNG the page can show."""
import base64
import io


def qr_data_url(content):
    import qrcode

    image = qrcode.make(str(content), box_size=6, border=2)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
