#!/usr/bin/env python3
"""Regenerate docs/assets/sopcontrol-living-boundary.gif (requires Pillow)."""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets" / "sopcontrol-living-boundary.gif"
W, H = 960, 360
CX, CY = W // 2, H // 2
BASE_R = 118
FRAMES = 48
DURATION_MS = 70
BG = (12, 16, 24, 255)
RING = (56, 189, 248, 255)
RING_INNER = (251, 191, 36, 220)
GLOW = (34, 211, 238, 55)
TEXT_DIM = (148, 163, 184, 255)
GRID = (30, 41, 59, 255)


def radius_at(theta: float, t: float) -> float:
    breath = 1.0 + 0.06 * math.sin(t * 2 * math.pi)
    lobes = (
        0.11 * math.sin(3 * theta + t * 2 * math.pi)
        + 0.07 * math.sin(5 * theta - t * 4 * math.pi)
        + 0.045 * math.sin(2 * theta + t * 6 * math.pi)
        + 0.03 * math.cos(7 * theta + t * 2.5 * math.pi)
    )
    leak = 0.05 * max(0.0, math.sin(theta * 2 - t * 2 * math.pi)) ** 8
    return BASE_R * breath * (1.0 + lobes + leak)


def ring_polygon(t: float, scale: float = 1.0, n: int = 180):
    pts = []
    for i in range(n):
        theta = 2 * math.pi * i / n
        r = radius_at(theta, t) * scale
        pts.append((CX + r * math.cos(theta), CY + r * math.sin(theta)))
    return pts


def draw_frame(t: float) -> Image.Image:
    img = Image.new("RGBA", (W, H), BG)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).polygon(ring_polygon(t, scale=1.18), fill=GLOW)
    glow = glow.filter(ImageFilter.GaussianBlur(radius=18))
    img = Image.alpha_composite(img, glow)
    draw = ImageDraw.Draw(img)
    for x in range(40, W, 40):
        draw.line([(x, 0), (x, H)], fill=GRID, width=1)
    for y in range(20, H, 40):
        draw.line([(0, y), (W, y)], fill=GRID, width=1)
    draw.polygon(ring_polygon(t, scale=0.55), fill=(15, 23, 42, 255), outline=RING_INNER)
    boundary = ring_polygon(t, scale=1.0)
    draw.line(boundary + [boundary[0]], fill=RING, width=4, joint="curve")
    inner = ring_polygon(t + 0.08, scale=0.82)
    draw.line(inner + [inner[0]], fill=(125, 211, 252, 120), width=2, joint="curve")
    draw.ellipse((CX - 4, CY - 4, CX + 4, CY + 4), fill=RING_INNER)
    draw.rectangle([(0, H - 36), (W, H)], fill=(8, 11, 18, 255))
    caption = "finite living boundary  ·  ambiguity breathes  ·  authority in the project"
    bbox = draw.textbbox((0, 0), caption)
    tw = bbox[2] - bbox[0]
    draw.text(((W - tw) // 2, H - 26), caption, fill=TEXT_DIM)
    return img.convert("P", palette=Image.ADAPTIVE, colors=64)


def main() -> None:
    frames = [draw_frame(i / FRAMES) for i in range(FRAMES)]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        OUT,
        save_all=True,
        append_images=frames[1:],
        duration=DURATION_MS,
        loop=0,
        optimize=True,
        disposal=2,
    )
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
