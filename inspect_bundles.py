"""
inspect_bundles.py
------------------
Step 1: Dump a human-readable summary of every asset bundle in /bundles/
so we can understand the dicing format before reconstruction.
"""

import os
import struct
import json
import UnityPy
from collections import Counter, defaultdict

BUNDLES_DIR = os.path.join(os.path.dirname(__file__), "bundles")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "inspection")


def parse_vertex_data(vd, tex_w: int, tex_h: int):
    """
    Returns list of (pos_x, pos_y, uv_u, uv_v) tuples.
    Assumes stream-0 = XYZ positions (3 × float32),
            stream-1 = UV0  (2 × float32).
    """
    data = vd.m_DataSize
    vc = vd.m_VertexCount
    s0_size = vc * 3 * 4  # stream-0 byte budget

    verts = []
    for i in range(vc):
        x, y, _z = struct.unpack_from("<fff", data, i * 12)
        u, v = struct.unpack_from("<ff", data, s0_size + i * 8)
        verts.append((x, y, u, v))
    return verts


def quads_from_indices(index_bytes):
    """
    Unity diced sprites use the pattern (a,b,c, c,d,a) per quad.
    Yields (a, b, c, d) index tuples.
    """
    n = len(index_bytes) // 2
    indices = struct.unpack(f"<{n}H", index_bytes)
    for q in range(n // 6):
        base = q * 6
        a, b, c, c2, d, a2 = indices[base : base + 6]
        yield (a, b, c, d)


def summarise_bundle(bundle_path: str) -> dict:
    env = UnityPy.load(bundle_path)

    # --- collect texture info ---
    textures = {}  # path_id -> {name, width, height, format}
    for obj in env.objects:
        if obj.type.name == "Texture2D":
            d = obj.read()
            textures[obj.path_id] = {
                "name": d.m_Name,
                "width": d.m_Width,
                "height": d.m_Height,
                "format": str(d.m_TextureFormat),
            }

    # --- collect sprite info ---
    sprites = []
    for obj in env.objects:
        if obj.type.name != "Sprite":
            continue
        d = obj.read()
        rd = d.m_RD
        tex_pid = rd.texture.path_id
        tex = textures.get(tex_pid, {})
        tw, th = tex.get("width", 0), tex.get("height", 0)

        # vertex data
        vd = rd.m_VertexData
        vc = vd.m_VertexCount

        quad_count = len(bytes(rd.m_IndexBuffer)) // 12  # 6 uint16 per quad

        entry = {
            "name": d.m_Name,
            "path_id": obj.path_id,
            "rect": {
                "x": d.m_Rect.x,
                "y": d.m_Rect.y,
                "w": d.m_Rect.width,
                "h": d.m_Rect.height,
            },
            "pixels_per_unit": d.m_PixelsToUnits,
            "texture": tex.get("name", "?"),
            "texture_path_id": tex_pid,
            "tex_size": f"{tw}x{th}",
            "vertex_count": vc,
            "quad_count": quad_count,
        }

        # sample first quad
        if vc >= 4 and quad_count >= 1:
            verts = parse_vertex_data(vd, tw, th)
            idx_bytes = bytes(rd.m_IndexBuffer)
            for a, b, c, dd in quads_from_indices(idx_bytes):
                q_verts = [verts[a], verts[b], verts[c], verts[dd]]
                xs = [v[0] for v in q_verts]
                ys = [v[1] for v in q_verts]
                us = [v[2] for v in q_verts]
                vs_ = [v[3] for v in q_verts]
                entry["first_quad"] = {
                    "pos": f"({min(xs):.0f},{min(ys):.0f})-({max(xs):.0f},{max(ys):.0f})",
                    "uv": f"u[{min(us):.4f},{max(us):.4f}] v[{min(vs_):.4f},{max(vs_):.4f}]",
                    "tile_size_px": f"{max(xs)-min(xs):.0f}x{max(ys)-min(ys):.0f}",
                    "tex_tile_px": (
                        f"{(max(us)-min(us))*tw:.0f}x{(max(vs_)-min(vs_))*th:.0f}"
                        if tw and th
                        else "?"
                    ),
                }
                break

        sprites.append(entry)

    # --- collect MonoBehaviour info ---
    mono_data = []
    for obj in env.objects:
        if obj.type.name == "MonoBehaviour":
            try:
                tree = obj.read_typetree()
                mono_data.append(tree)
            except Exception:
                pass

    type_counts = Counter(obj.type.name for obj in env.objects)

    return {
        "bundle": os.path.basename(bundle_path),
        "asset_type_counts": dict(type_counts),
        "textures": list(textures.values()),
        "sprites": sprites,
        "mono_behaviours": mono_data,
    }


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    bundle_files = sorted(
        f for f in os.listdir(BUNDLES_DIR)
        if os.path.isfile(os.path.join(BUNDLES_DIR, f))
    )

    print(f"Inspecting {len(bundle_files)} bundle(s)...")
    for fname in bundle_files:
        path = os.path.join(BUNDLES_DIR, fname)
        print(f"  {fname} … ", end="", flush=True)
        try:
            summary = summarise_bundle(path)
            out = os.path.join(OUTPUT_DIR, f"{fname}.json")
            with open(out, "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2, default=str)
            n_sprites = len(summary["sprites"])
            n_textures = len(summary["textures"])
            print(f"{n_sprites} sprites, {n_textures} texture(s) -> {out}")
        except Exception as e:
            print(f"ERROR: {e}")

    print("Done.")


if __name__ == "__main__":
    main()
