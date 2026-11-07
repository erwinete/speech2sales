# Файл: tools/ui/generate_brutalist_glyphs.py
"""
Детерминированный генератор собственных минималистично-бруталистских изображений-глифов.
Генерирует PNG (48x48, прозрачный фон, приглушенный графитовый штрих #353431)
и SVG (24x24) в директорию web/public/assets/glyphs/.
Не требует сторонних иконочных библиотек и внешних зависимостей (использует стандартные struct + zlib).
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parents[2] / "web" / "public" / "assets" / "glyphs"
INK_RGBA = (53, 52, 49, 255)      # #353431 — приглушенный сухой графит
ACCENT_RGBA = (135, 94, 88, 255)  # #875E58 — приглушенная терракота для акцентов


def _encode_png(width: int, height: int, pixels: list[list[tuple[int, int, int, int]]]) -> bytes:
    """Кодирует RGBA-матрицу в валидный PNG без внешних зависимостей."""
    raw_rows = bytearray()
    for row in pixels:
        raw_rows.append(0)  # Filter type 0 (None)
        for r, g, b, a in row:
            raw_rows.extend((r, g, b, a))

    def chunk(chunk_type: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(raw_rows), level=9)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


class BrutalistCanvas:
    """Минималистичный растровый + векторный чертежник на сетке 24x24 (масштаб x2 -> 48x48 PNG)."""

    def __init__(self, scale: int = 2) -> None:
        self.logical_size = 24
        self.scale = scale
        self.size = self.logical_size * scale
        self.pixels = [[(0, 0, 0, 0) for _ in range(self.size)] for _ in range(self.size)]
        self.svg_elements: list[str] = []

    def rect(self, x: int, y: int, w: int, h: int, fill: bool = False, accent: bool = False) -> None:
        color = ACCENT_RGBA if accent else INK_RGBA
        hex_color = "#875E58" if accent else "#353431"
        if fill:
            self.svg_elements.append(
                f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{hex_color}" />'
            )
            for py in range(y * self.scale, (y + h) * self.scale):
                for px in range(x * self.scale, (x + w) * self.scale):
                    if 0 <= px < self.size and 0 <= py < self.size:
                        self.pixels[py][px] = color
        else:
            # Рамка толщиной 1.5-2px (в логической сетке 1px border = 2px в 48x48)
            self.rect(x, y, w, 1, fill=True, accent=accent)
            self.rect(x, y + h - 1, w, 1, fill=True, accent=accent)
            self.rect(x, y, 1, h, fill=True, accent=accent)
            self.rect(x + w - 1, y, 1, h, fill=True, accent=accent)

    def hline(self, x: int, y: int, length: int, thickness: int = 2, accent: bool = False) -> None:
        self.rect(x, y, length, thickness, fill=True, accent=accent)

    def vline(self, x: int, y: int, length: int, thickness: int = 2, accent: bool = False) -> None:
        self.rect(x, y, thickness, length, fill=True, accent=accent)


def build_all_glyphs() -> dict[str, BrutalistCanvas]:
    glyphs: dict[str, BrutalistCanvas] = {}

    # 1. nav-dashboard: Архитектурная сетка 3 секций
    c = BrutalistCanvas()
    c.rect(2, 2, 20, 20, fill=False)
    c.hline(2, 9, 20, 1)
    c.vline(10, 9, 13, 1)
    c.rect(5, 5, 3, 2, fill=True)
    glyphs["nav-dashboard"] = c

    # 2. nav-calls: Ступенчатая импульсная осциллограмма
    c = BrutalistCanvas()
    c.hline(2, 12, 20, 1)
    c.vline(4, 8, 9, 2)
    c.vline(8, 4, 16, 2)
    c.vline(12, 9, 7, 2)
    c.vline(16, 6, 12, 2)
    c.vline(20, 10, 5, 2)
    glyphs["nav-calls"] = c

    # 3. nav-risks: Квадрат с акцентированным сектором отклонения
    c = BrutalistCanvas()
    c.rect(2, 2, 20, 20, fill=False)
    c.hline(2, 12, 20, 1)
    c.vline(12, 2, 20, 1)
    c.rect(14, 4, 6, 6, fill=True, accent=True)
    glyphs["nav-risks"] = c

    # 4. nav-objections: Встречные бруталистские скобки с сечением
    c = BrutalistCanvas()
    c.vline(4, 4, 16, 2)
    c.hline(4, 4, 5, 2)
    c.hline(4, 18, 5, 2)
    c.vline(18, 4, 16, 2)
    c.hline(15, 4, 5, 2)
    c.hline(15, 18, 5, 2)
    c.hline(9, 11, 6, 2, accent=True)
    glyphs["nav-objections"] = c

    # 5. nav-reps: Три горизонтальные шкалы эффективности
    c = BrutalistCanvas()
    for idx, (y_pos, marker_x) in enumerate([(5, 16), (11, 11), (17, 18)]):
        c.hline(3, y_pos, 18, 1)
        c.rect(marker_x, y_pos - 2, 2, 5, fill=True, accent=(idx == 0))
    glyphs["nav-reps"] = c

    # 6. nav-customer: Концентрический квадрат с засечками 360
    c = BrutalistCanvas()
    c.rect(3, 3, 18, 18, fill=False)
    c.rect(8, 8, 8, 8, fill=False)
    c.vline(11, 1, 3, 2)
    c.vline(11, 20, 3, 2)
    c.hline(1, 11, 3, 2)
    c.hline(20, 11, 3, 2)
    glyphs["nav-customer"] = c

    # 7. nav-llm: Узловая матрица нейросети / MCP
    c = BrutalistCanvas()
    c.rect(3, 3, 5, 5, fill=True)
    c.rect(16, 3, 5, 5, fill=True)
    c.rect(3, 16, 5, 5, fill=True)
    c.rect(16, 16, 5, 5, fill=True, accent=True)
    c.hline(8, 5, 8, 1)
    c.hline(8, 18, 8, 1)
    c.vline(5, 8, 8, 1)
    c.vline(18, 8, 8, 1)
    c.rect(10, 10, 4, 4, fill=True)
    glyphs["nav-llm"] = c

    # 8. nav-settings: Технические ползунки конфигурации
    c = BrutalistCanvas()
    c.hline(2, 6, 20, 1)
    c.rect(6, 4, 4, 5, fill=True)
    c.hline(2, 12, 20, 1)
    c.rect(14, 10, 4, 5, fill=True)
    c.hline(2, 18, 20, 1)
    c.rect(9, 16, 4, 5, fill=True)
    glyphs["nav-settings"] = c

    # 9. role-manager: Индекс оператора
    c = BrutalistCanvas()
    c.vline(4, 3, 18, 2)
    c.hline(6, 6, 12, 2)
    c.hline(6, 11, 9, 2)
    c.rect(6, 16, 5, 4, fill=True)
    glyphs["role-manager"] = c

    # 10. role-client: Индекс внешнего абонента
    c = BrutalistCanvas()
    c.vline(18, 3, 18, 2)
    c.hline(6, 6, 12, 2)
    c.hline(9, 11, 9, 2)
    c.rect(13, 16, 5, 4, fill=True, accent=True)
    glyphs["role-client"] = c

    # 11. sentiment-pos: Восходящая ступенчатая характеристика
    c = BrutalistCanvas()
    c.hline(3, 17, 6, 2)
    c.vline(7, 12, 7, 2)
    c.hline(7, 12, 7, 2)
    c.vline(12, 6, 8, 2)
    c.hline(12, 6, 9, 2)
    glyphs["sentiment-pos"] = c

    # 12. sentiment-neu: Две спокойные параллельные рельсы
    c = BrutalistCanvas()
    c.hline(3, 9, 18, 2)
    c.hline(3, 14, 18, 2)
    c.vline(3, 7, 4, 1)
    c.vline(20, 13, 4, 1)
    glyphs["sentiment-neu"] = c

    # 13. sentiment-neg: Нисходящая ступенчатая характеристика
    c = BrutalistCanvas()
    c.hline(3, 6, 7, 2)
    c.vline(8, 6, 7, 2)
    c.hline(8, 12, 7, 2)
    c.vline(13, 12, 7, 2)
    c.hline(13, 17, 8, 2, accent=True)
    glyphs["sentiment-neg"] = c

    # 14. status-alert: Геометрический квадратный сигнал с вертикальным сердечником
    c = BrutalistCanvas()
    c.rect(3, 3, 18, 18, fill=False, accent=True)
    c.vline(11, 7, 6, 2, accent=True)
    c.rect(11, 15, 2, 2, fill=True, accent=True)
    glyphs["status-alert"] = c

    # 15. status-ok: Стабильный центрированный квадрат
    c = BrutalistCanvas()
    c.rect(3, 3, 18, 18, fill=False)
    c.rect(9, 9, 6, 6, fill=True)
    glyphs["status-ok"] = c

    # 16. status-pii: Трафарет редактирования / цензуры ПДн
    c = BrutalistCanvas()
    c.rect(2, 5, 20, 14, fill=False)
    c.rect(5, 9, 14, 6, fill=True)
    c.hline(2, 2, 6, 1)
    c.hline(16, 21, 6, 1)
    glyphs["status-pii"] = c

    # 17. channel-call: Прямоугольный меандр аудиосигнала
    c = BrutalistCanvas()
    c.hline(2, 16, 4, 2)
    c.vline(6, 6, 12, 2)
    c.hline(6, 6, 5, 2)
    c.vline(11, 6, 12, 2)
    c.hline(11, 16, 5, 2)
    c.vline(16, 9, 9, 2)
    c.hline(16, 9, 6, 2)
    glyphs["channel-call"] = c

    # 18. channel-crm: Двунаправленный обмен регистров
    c = BrutalistCanvas()
    c.hline(3, 8, 15, 2)
    c.rect(16, 6, 4, 4, fill=True)
    c.hline(6, 15, 15, 2)
    c.rect(4, 13, 4, 4, fill=True)
    glyphs["channel-crm"] = c

    # 19. channel-mail: Конверт чертежного типа
    c = BrutalistCanvas()
    c.rect(2, 5, 20, 14, fill=False)
    c.hline(2, 10, 20, 1)
    c.vline(11, 5, 6, 2)
    glyphs["channel-mail"] = c

    # 20. channel-chat: Диалоговый терминальный блок
    c = BrutalistCanvas()
    c.rect(3, 4, 18, 13, fill=False)
    c.hline(7, 8, 10, 2)
    c.hline(7, 12, 6, 2)
    c.vline(5, 17, 4, 2)
    glyphs["channel-chat"] = c

    # 21. channel-meet: Сетка слотов времени
    c = BrutalistCanvas()
    c.rect(3, 4, 18, 17, fill=False)
    c.rect(3, 4, 18, 4, fill=True)
    c.hline(3, 13, 18, 1)
    c.vline(11, 8, 13, 1)
    glyphs["channel-meet"] = c

    # 22. ctrl-play: Ступенчатый пусковой индекс
    c = BrutalistCanvas()
    c.vline(6, 4, 16, 3)
    c.vline(9, 6, 12, 3)
    c.vline(12, 8, 8, 3)
    c.vline(15, 10, 4, 3)
    glyphs["ctrl-play"] = c

    # 23. ctrl-pause: Два параллельных стоп-бруса
    c = BrutalistCanvas()
    c.rect(6, 4, 4, 16, fill=True)
    c.rect(14, 4, 4, 16, fill=True)
    glyphs["ctrl-pause"] = c

    # 24. ctrl-upload: Приемный бункер и вектор загрузки
    c = BrutalistCanvas()
    c.vline(3, 14, 7, 2)
    c.vline(19, 14, 7, 2)
    c.hline(3, 19, 18, 2)
    c.vline(11, 4, 11, 2)
    c.hline(8, 7, 8, 2)
    glyphs["ctrl-upload"] = c

    # 25. ctrl-copy: Двойной регистр копирования
    c = BrutalistCanvas()
    c.rect(3, 3, 13, 13, fill=False)
    c.rect(8, 8, 13, 13, fill=False)
    c.rect(11, 11, 7, 7, fill=True)
    glyphs["ctrl-copy"] = c

    # 26. ctrl-sort-asc: Ступени по возрастанию
    c = BrutalistCanvas()
    c.hline(4, 6, 5, 2)
    c.hline(4, 11, 10, 2)
    c.hline(4, 16, 16, 2)
    glyphs["ctrl-sort-asc"] = c

    # 27. ctrl-sort-desc: Ступени по убыванию
    c = BrutalistCanvas()
    c.hline(4, 6, 16, 2)
    c.hline(4, 11, 10, 2)
    c.hline(4, 16, 5, 2)
    glyphs["ctrl-sort-desc"] = c

    # 28. ctrl-theme: Контрастная полуматрица темы
    c = BrutalistCanvas()
    c.rect(3, 3, 18, 18, fill=False)
    c.rect(3, 3, 9, 18, fill=True)
    glyphs["ctrl-theme"] = c

    return glyphs


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    glyphs = build_all_glyphs()
    for name, canvas in glyphs.items():
        png_path = OUTPUT_DIR / f"{name}.png"
        svg_path = OUTPUT_DIR / f"{name}.svg"
        png_path.write_bytes(_encode_png(canvas.size, canvas.size, canvas.pixels))
        svg_body = "\n  ".join(canvas.svg_elements)
        svg_content = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
            f'width="24" height="24" shape-rendering="crispEdges">\n  {svg_body}\n</svg>\n'
        )
        svg_path.write_text(svg_content, encoding="utf-8")
    print(f"Generated {len(glyphs)} minimalist-brutalist glyphs in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
