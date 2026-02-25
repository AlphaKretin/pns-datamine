"""
make_preview_gif.py
-------------------
Assembles all portrait PNGs for a given body variant into an animated GIF.

Usage:
    python make_preview_gif.py [char_code] [body] [--fps N] [--bg RRGGBB] [--out FILE]

    char_code   Three-letter character code (default: avi)
    body        Body variant prefix to match (default: b1)
    --fps       Frames per second (default: 4)
    --bg        Background colour as hex, e.g. 2a2a2a (default: 222222)
    --out       Output GIF path (default: {char_code}_{body}_preview.gif)

Reads from output_portraits/{char_code}/ (direct files only, no subfolders).
Files are sorted alphabetically, which groups them by expression core then
eye frame then mouth frame.
"""

import os
import argparse
from PIL import Image

PORTRAITS_DIR = os.path.join(os.path.dirname(__file__), "output_portraits")


def hex_to_rgb(hex_str):
    h = hex_str.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def main():
    parser = argparse.ArgumentParser(
        description="Assemble portrait PNGs into a preview GIF.")
    parser.add_argument("char_code", nargs="?", default="avi",
        help="Character code (default: avi)")
    parser.add_argument("body", nargs="?", default="b1",
        help="Body prefix to match (default: b1)")
    parser.add_argument("--fps", type=float, default=4,
        help="Frames per second (default: 4)")
    parser.add_argument("--bg", default="222222",
        help="Background colour as hex RGB (default: 222222)")
    parser.add_argument("--out", default=None,
        help="Output GIF path (default: {char_code}_{body}_preview.gif)")
    opts = parser.parse_args()

    src_dir = os.path.join(PORTRAITS_DIR, opts.char_code)
    if not os.path.isdir(src_dir):
        print(f"Directory not found: {src_dir}")
        return

    prefix = opts.body + "_"
    files = sorted(
        f for f in os.listdir(src_dir)
        if f.startswith(prefix) and f.endswith(".png")
        and os.path.isfile(os.path.join(src_dir, f))
    )

    if not files:
        print(f"No files matching '{prefix}*.png' found in {src_dir}")
        return

    print(f"Found {len(files)} frames for '{opts.char_code}/{opts.body}'")

    bg_rgb = hex_to_rgb(opts.bg)
    duration_ms = int(1000 / opts.fps)

    frames = []
    for fname in files:
        img = Image.open(os.path.join(src_dir, fname)).convert("RGBA")
        # Composite onto background colour
        bg = Image.new("RGBA", img.size, bg_rgb + (255,))
        bg.alpha_composite(img)
        # Convert to palette mode for GIF
        frames.append(bg.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT))

    out_path = opts.out or f"{opts.char_code}_{opts.body}_preview.gif"

    frames[0].save(
        out_path,
        save_all=True,
        append_images=frames[1:],
        loop=0,
        duration=duration_ms,
        optimize=False,
    )

    size_kb = os.path.getsize(out_path) // 1024
    print(f"Saved {out_path}  ({len(frames)} frames, {duration_ms}ms/frame, {size_kb} KB)")


if __name__ == "__main__":
    main()
