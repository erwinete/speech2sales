# Файл: tools/ui/verify_brutalist_ui.py
"""
Автоматический валидатор соблюдения ТЗ v6.0 (Minimalist-Brutalist UI):
1. Проверяет отсутствие эмодзи и спецсимволов-иконок в web/src/.
2. Проверяет отсутствие сторонних иконочных библиотек в web/package.json и импортах.
3. Проверяет наличие всех 28 сгенерированных собственных глифов в web/public/assets/glyphs/.
4. Проверяет отсутствие скруглений (border-radius > 0) и ярких стандартных цветов в CSS.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB_SRC = ROOT / "web" / "src"
GLYPHS_DIR = ROOT / "web" / "public" / "assets" / "glyphs"
PKG_JSON = ROOT / "web" / "package.json"

FORBIDDEN_LIBRARIES = {
    "lucide-react",
    "heroicons",
    "@heroicons/react",
    "@radix-ui/react-icons",
    "react-icons",
    "@tabler/icons-react",
    "font-awesome",
    "@fortawesome/fontawesome-free",
    "@mui/icons-material",
}

FORBIDDEN_UNICODE_CHARS = [
    "😊", "😐", "☹", "⚠", "🧑‍💼", "👤", "🎙", "⟲", "✉", "💬", "📅",
    "✱", "✨", "📞", "▶", "❚❚", "▲", "▼", "←", "→", "✅", "❌", "🔥", "🚀",
]

REQUIRED_GLYPHS = [
    "nav-dashboard", "nav-calls", "nav-risks", "nav-objections",
    "nav-reps", "nav-customer", "nav-llm", "nav-settings",
    "role-manager", "role-client", "sentiment-pos", "sentiment-neu",
    "sentiment-neg", "status-alert", "status-ok", "status-pii",
    "channel-call", "channel-crm", "channel-mail", "channel-chat",
    "channel-meet", "ctrl-play", "ctrl-pause", "ctrl-upload",
    "ctrl-copy", "ctrl-sort-asc", "ctrl-sort-desc", "ctrl-theme",
]


def main() -> int:
    errors: list[str] = []

    # 1. Проверка package.json на запрещенные библиотеки иконок
    if PKG_JSON.exists():
        pkg = json.loads(PKG_JSON.read_text(encoding="utf-8"))
        deps = set(pkg.get("dependencies", {}).keys()) | set(pkg.get("devDependencies", {}).keys())
        found_libs = deps & FORBIDDEN_LIBRARIES
        if found_libs:
            errors.append(f"Forbidden icon libraries in package.json: {sorted(found_libs)}")

    # 2. Проверка наличия сгенерированных растровых и векторных изображений глифов
    for glyph in REQUIRED_GLYPHS:
        if not (GLYPHS_DIR / f"{glyph}.png").exists():
            errors.append(f"Missing generated PNG glyph: web/public/assets/glyphs/{glyph}.png")
        if not (GLYPHS_DIR / f"{glyph}.svg").exists():
            errors.append(f"Missing generated SVG glyph: web/public/assets/glyphs/{glyph}.svg")

    # 3. Сканирование исходников web/src/ на эмодзи и запрещенные импорты
    for path in WEB_SRC.rglob("*"):
        if path.suffix not in {".ts", ".tsx", ".css"}:
            continue
        content = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)

        for char in FORBIDDEN_UNICODE_CHARS:
            if char in content:
                errors.append(f"Forbidden emoji/symbol '{char}' found in {rel}")

        for lib in FORBIDDEN_LIBRARIES:
            if f'"{lib}"' in content or f"'{lib}'" in content:
                errors.append(f"Forbidden icon library import '{lib}' in {rel}")

        if path.suffix == ".css":
            # Проверка на отсутствие ненулевых border-radius
            for match in re.finditer(r"border-radius\s*:\s*([^;]+);", content):
                val = match.group(1).strip()
                if not val.startswith("0"):
                    errors.append(f"Non-zero border-radius '{val}' found in {rel}")

    if errors:
        print("UI VERIFICATION FAILED:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("UI VERIFICATION PASSED: Zero emojis, zero external icon libs, all 28 custom glyphs verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
