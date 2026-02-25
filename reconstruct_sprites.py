"""
reconstruct_sprites.py
-----------------------
Reconstructs full sprites from Unity diced-texture asset bundles.

How diced textures work
~~~~~~~~~~~~~~~~~~~~~~~
Unity's "Sprite Dicing" workflow cuts each sprite into small uniform tiles
("dice"), packs only the non-empty tiles into a compact atlas texture, and
records a mesh of axis-aligned quads that maps each atlas tile back to its
correct position in the original sprite.

For every Sprite asset:
  • m_RD.texture          → PPtr to the Texture2D atlas
  • m_RD.m_VertexData     → interleaved stream data
      stream 0  →  XYZ position  (3 × float32 per vertex)
      stream 1  →  UV0           (2 × float32 per vertex)
  • m_RD.m_IndexBuffer    → triangle list (uint16), two triangles per quad:
                            pattern (a,b,c, c,d,a)
  • m_Rect                → bounding box of the sprite in position space
                            (x, y = bottom-left corner; y-axis points up)

Reconstruction steps
~~~~~~~~~~~~~~~~~~~~
1. Decode the atlas Texture2D to a PIL RGBA image.
2. Parse vertex data → list of (pos_x, pos_y, uv_u, uv_v).
3. Parse index buffer → list of (a, b, c, d) quad vertex indices.
4. Create an RGBA canvas of size (m_Rect.width, m_Rect.height).
5. For each quad:
     a. Collect the 4 vertices and find their axis-aligned bounds.
     b. Compute source region in the atlas:
          tex_x = u * tex_width
          tex_y = (1 - v) * tex_height   (flip V: Unity UV origin is bottom-left)
     c. Compute destination region in the canvas:
          dst_x = pos_x - m_Rect.x
          dst_y = m_Rect.height - (pos_y - m_Rect.y)   (flip Y: image origin is top-left)
     d. Crop source region from atlas, paste at destination.
6. Save canvas as PNG.
"""

import os
import re
import struct
import argparse
import UnityPy
from PIL import Image

BUNDLES_DIR = os.path.join(os.path.dirname(__file__), "bundles")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")


def get_char_code(env):
    """Return the character code (e.g. 'avi') from the dice atlas name.
    Checks Sprite assets first, then Texture2D assets as a fallback."""
    for type_name in ("Sprite", "Texture2D"):
        for obj in env.objects:
            if obj.type.name == type_name:
                d = obj.read()
                m = re.match(r"dice_([a-z]+)", d.m_Name)
                if m:
                    return m.group(1)
    return None


# ---------------------------------------------------------------------------
# Vertex / index parsing
# ---------------------------------------------------------------------------

def parse_vertices(vd, vertex_count: int):
    """
    Parse VertexData into a list of (pos_x, pos_y, uv_u, uv_v).

    Stream layout (confirmed from UnityPy channel inspection):
      stream 0 : XYZ  →  vertex_count × 3 float32  (12 bytes/vertex)
      stream 1 : UV0  →  vertex_count × 2 float32  ( 8 bytes/vertex)
    The two streams are stored back-to-back in m_DataSize.
    """
    data = vd.m_DataSize
    s0_end = vertex_count * 12  # stream-0 ends here

    verts = []
    for i in range(vertex_count):
        x, y, _z = struct.unpack_from("<fff", data, i * 12)
        u, v = struct.unpack_from("<ff", data, s0_end + i * 8)
        verts.append((x, y, u, v))
    return verts


def iter_quads(index_buffer_bytes: bytes):
    """
    Unity diced sprites always emit two back-to-back triangles per quad:
        (a, b, c) and (c, d, a)
    Yield the 4 unique vertex indices (a, b, c, d) for every quad.
    """
    n = len(index_buffer_bytes) // 2
    indices = struct.unpack(f"<{n}H", index_buffer_bytes)
    for q in range(n // 6):
        base = q * 6
        a, b, c, _c2, d, _a2 = indices[base : base + 6]
        yield a, b, c, d


# ---------------------------------------------------------------------------
# Sprite reconstruction
# ---------------------------------------------------------------------------

def reconstruct_sprite(sprite_data, atlas_img: Image.Image) -> Image.Image:
    """
    Given a decoded Sprite object and its atlas PIL image,
    return a reconstructed PIL RGBA image.
    """
    d = sprite_data
    rd = d.m_RD
    rect = d.m_Rect

    canvas_w = int(round(rect.width))
    canvas_h = int(round(rect.height))
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    tw, th = atlas_img.size

    verts = parse_vertices(rd.m_VertexData, rd.m_VertexData.m_VertexCount)
    idx_bytes = bytes(rd.m_IndexBuffer)

    for a, b, c, dd in iter_quads(idx_bytes):
        quad = [verts[a], verts[b], verts[c], verts[dd]]

        # --- position bounds → destination on canvas ---
        xs = [v[0] for v in quad]
        ys = [v[1] for v in quad]
        pos_x0, pos_x1 = min(xs), max(xs)
        pos_y0, pos_y1 = min(ys), max(ys)  # pos_y0 < pos_y1 (bottom, top in Unity)

        dst_l = int(round(pos_x0 - rect.x))
        dst_t = int(round(canvas_h - (pos_y1 - rect.y)))  # flip Y
        dst_r = int(round(pos_x1 - rect.x))
        dst_b = int(round(canvas_h - (pos_y0 - rect.y)))

        # --- UV bounds → source region in atlas ---
        us = [v[2] for v in quad]
        vs = [v[3] for v in quad]
        u0, u1 = min(us), max(us)
        v0, v1 = min(vs), max(vs)  # v0 < v1 (bottom, top in UV space)

        # Flip V: UV origin is bottom-left; image origin is top-left
        src_l = int(round(u0 * tw))
        src_t = int(round((1.0 - v1) * th))
        src_r = int(round(u1 * tw))
        src_b = int(round((1.0 - v0) * th))

        # Guard against degenerate quads
        if dst_r <= dst_l or dst_b <= dst_t or src_r <= src_l or src_b <= src_t:
            continue

        tile = atlas_img.crop((src_l, src_t, src_r, src_b))

        # Resize if source and destination tile sizes differ (shouldn't happen,
        # but protects against floating-point rounding edge cases)
        dst_w, dst_h = dst_r - dst_l, dst_b - dst_t
        src_w, src_h = src_r - src_l, src_b - src_t
        if (src_w, src_h) != (dst_w, dst_h):
            tile = tile.resize((dst_w, dst_h), Image.NEAREST)

        canvas.paste(tile, (dst_l, dst_t))

    return canvas


# ---------------------------------------------------------------------------
# Bundle processing
# ---------------------------------------------------------------------------

def process_bundle(bundle_path: str, out_dir: str):
    bundle_name = os.path.splitext(os.path.basename(bundle_path))[0]
    env = UnityPy.load(bundle_path)

    char_code = get_char_code(env) or bundle_name
    char_dir = os.path.join(out_dir, char_code)
    os.makedirs(char_dir, exist_ok=True)

    # Decode every Texture2D in this bundle once
    textures: dict[int, Image.Image] = {}
    for obj in env.objects:
        if obj.type.name == "Texture2D":
            d = obj.read()
            textures[obj.path_id] = d.image.convert("RGBA")

    if not textures:
        print(f"  [{char_code}] No textures found, skipping.")
        return

    saved = 0
    skipped = 0
    for obj in env.objects:
        if obj.type.name != "Sprite":
            continue

        d = obj.read()

        # Skip the dice-atlas sprites themselves (ppu=100, named "dice_*")
        if d.m_Name.startswith("dice_"):
            skipped += 1
            continue

        # Skip sprites with empty vertex data
        vd = d.m_RD.m_VertexData
        if vd.m_VertexCount == 0:
            skipped += 1
            continue

        tex_pid = d.m_RD.texture.path_id
        atlas = textures.get(tex_pid)
        if atlas is None:
            print(f"  [{char_code}] WARNING: texture {tex_pid} not found for sprite '{d.m_Name}'")
            skipped += 1
            continue

        try:
            img = reconstruct_sprite(d, atlas)
        except Exception as e:
            print(f"  [{char_code}] ERROR reconstructing '{d.m_Name}': {e}")
            skipped += 1
            continue

        safe_name = d.m_Name.replace("/", "_").replace("\\", "_").replace(" ", "_")
        img.save(os.path.join(char_dir, f"{safe_name}.png"))
        saved += 1

    print(f"  [{char_code}] saved {saved} sprites, skipped {skipped}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Reconstruct sprites from Unity asset bundles.")
    parser.add_argument(
        "character", nargs="?",
        help="Character to process: char code (e.g. avi) or bundle ID (e.g. 001). "
             "Omit to process all.")
    opts = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    all_files = sorted(
        os.path.join(BUNDLES_DIR, f)
        for f in os.listdir(BUNDLES_DIR)
        if os.path.isfile(os.path.join(BUNDLES_DIR, f))
    )

    if opts.character:
        query = opts.character.lower()
        bundle_files = []
        for path in all_files:
            bname = os.path.basename(path)
            # Match by bundle number (strip leading 'a' and zeros)
            num = bname.lstrip("a")
            if num == query.lstrip("a"):
                bundle_files.append(path)
                continue
            # Match by char code: load briefly to check
            env = UnityPy.load(path)
            code = get_char_code(env)
            if code == query:
                bundle_files.append(path)
        if not bundle_files:
            print(f"No bundle matching '{opts.character}' found.")
            return
    else:
        bundle_files = all_files

    print(f"Processing {len(bundle_files)} bundle(s) -> {OUTPUT_DIR}")
    for path in bundle_files:
        print(f"  {os.path.basename(path)} …")
        process_bundle(path, OUTPUT_DIR)

    print("Done.")


if __name__ == "__main__":
    main()
