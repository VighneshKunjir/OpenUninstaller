"""Draw the app icon and write packaging/OpenUninstaller.ico (16-256 px, PNG-compressed entries)."""
import os
import struct
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = size / 256
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0, QColor("#4b8ef8"))
    grad.setColorAt(1, QColor("#1f4fc0"))
    bg = QPainterPath()
    bg.addRoundedRect(QRectF(8 * s, 8 * s, 240 * s, 240 * s), 52 * s, 52 * s)
    p.fillPath(bg, grad)
    white = QColor("#ffffff")
    pen = QPen(white, max(1.0, 14 * s), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    # lid + handle
    p.drawLine(QRectF(64 * s, 78 * s, 0, 0).topLeft(), QRectF(192 * s, 78 * s, 0, 0).topLeft())
    p.drawRoundedRect(QRectF(104 * s, 52 * s, 48 * s, 26 * s), 8 * s, 8 * s)
    # bin body
    body = QPainterPath()
    body.moveTo(78 * s, 98 * s)
    body.lineTo(90 * s, 204 * s)
    body.quadTo(92 * s, 214 * s, 102 * s, 214 * s)
    body.lineTo(154 * s, 214 * s)
    body.quadTo(164 * s, 214 * s, 166 * s, 204 * s)
    body.lineTo(178 * s, 98 * s)
    p.drawPath(body)
    if size >= 32:   # ribs only where they stay readable
        thin = QPen(white, max(1.0, 10 * s), Qt.SolidLine, Qt.RoundCap)
        p.setPen(thin)
        for x in (110, 128, 146):
            p.drawLine(QRectF(x * s, 122 * s, 0, 0).topLeft(), QRectF(x * s, 188 * s, 0, 0).topLeft())
    p.end()
    return img


def png_bytes(img: QImage) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data)


def main(out: str = os.path.join(HERE, "OpenUninstaller.ico")):
    QGuiApplication(sys.argv)
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    blobs = [png_bytes(draw(sz)) for sz in sizes]
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = b""
    for sz, blob in zip(sizes, blobs):
        dim = 0 if sz == 256 else sz
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    with open(out, "wb") as f:
        f.write(header + entries + b"".join(blobs))
    draw(256).save(os.path.join(HERE, "icon_preview.png"))
    print("wrote", out)


if __name__ == "__main__":
    main()
