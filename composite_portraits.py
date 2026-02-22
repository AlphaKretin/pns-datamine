"""
composite_portraits.py
-----------------------
Composites full character portraits from pre-extracted sprite PNGs.

Portrait layer structure (derived from the Unity scene hierarchy under 'top'):
  1. Body sprite        - base / b1 / b2 / side / back / p0-p5 / b0 / dead ...
  2. Eye expression     - e_nom_* / e_sml_* / ... / e_p0_* / ...
  3. Mouth expression   - m_nom_* / m_sml_* / ... / m_p0_* / ...
  4. Accessory          - {body}_add  OR  {body}_addrev  (exactly one, mandatory)
  5. Extra overlays     - {body}_add1 / _add3 / _add5 / ... (optional per body)
  6. Cheek overlay      - base_cheek (optional; only for base-family bodies)

Optional layer variants and their filename suffixes:
  (no suffix) : standard accessory (_add), no extras, no blush
  _rev        : mirrored accessory (_addrev) instead of _add
  _extra      : includes the body's optional numbered-add overlays
  _blush      : includes the cheek layer  (base/b0/b1/b2/bx bodies only)
  Suffixes stack in that order, e.g. _rev_extra_blush.

Positioning note:
  Each sprite GO has a Transform with a local position that offsets it from its
  parent.  The m_Rect stored in the Sprite asset is in the GO's LOCAL coordinate
  space.  Actual world rect = Transform_world_pos + m_Rect.
  We compute world positions by walking the hierarchy tree.

Grouping rule:
  Walk the ordered child list of 'top'.  A run of consecutive body GOs shares
  the eye/mouth expression GOs that immediately follow them before the next body.

Frame selection (for a single static portrait):
  Eyes:   prefer  n1 -> n0 -> f0 -> f1 -> b0 -> b1
  Mouths: prefer  1 -> 0 -> 2

Output directory: output_portraits/
Progress log:     output_portraits/progress.log
"""

import os
import re
import UnityPy
from PIL import Image

BUNDLES_DIR = os.path.join(os.path.dirname(__file__), "bundles")
SPRITES_DIR = os.path.join(os.path.dirname(__file__), "output")
OUTPUT_DIR  = os.path.join(os.path.dirname(__file__), "output_portraits")

EYE_FRAME_PREF   = ["n1", "n0", "f0", "f1", "b0", "b1", "n2"]
MOUTH_FRAME_PREF = ["1", "0", "2"]

# Per-bundle PNG cache cleared between bundles.
_png_cache: dict = {}
_log_file = None

# Bodies that are considered "base-facing" and can receive the cheek/blush layer.
# Matches: "base", "b0"…"b9", "bx"  — excludes back, backx, side, dead, p0-p5.
_BASE_FAMILY_RE = re.compile(r"^(base|b[0-9x])$")


def log(msg):
    print(msg, flush=True)
    if _log_file:
        _log_file.write(msg + "\n")
        _log_file.flush()


# ---------------------------------------------------------------------------
# Hierarchy parsing helpers
# ---------------------------------------------------------------------------

def build_transform_tree(env):
    """
    Returns {path_id: {"go_name", "parent", "children", "lp": (x,y)}}
    """
    pid_to_go = {}
    for obj in env.objects:
        if obj.type.name == "GameObject":
            pid_to_go[obj.path_id] = obj.read().m_Name

    transforms = {}
    for obj in env.objects:
        if obj.type.name == "Transform":
            t = obj.read_typetree()
            lp = t.get("m_LocalPosition", {"x": 0.0, "y": 0.0})
            transforms[obj.path_id] = {
                "go_name" : pid_to_go.get(t["m_GameObject"]["m_PathID"], ""),
                "parent"  : t["m_Father"]["m_PathID"],
                "children": [c["m_PathID"] for c in t.get("m_Children", [])],
                "lp"      : (lp.get("x", 0.0), lp.get("y", 0.0)),
            }
    return transforms


def _world_pos(pid, transforms, memo):
    if pid in memo:
        return memo[pid]
    t = transforms.get(pid)
    if t is None:
        r = (0.0, 0.0)
    else:
        lx, ly = t["lp"]
        p = t["parent"]
        if p == 0 or p not in transforms:
            r = (lx, ly)
        else:
            px, py = _world_pos(p, transforms, memo)
            r = (px + lx, py + ly)
    memo[pid] = r
    return r


def find_node(transforms, name):
    for pid, t in transforms.items():
        if t["go_name"] == name:
            return pid
    return None


def children_names(transforms, pid):
    return [(c, transforms[c]["go_name"])
            for c in transforms[pid]["children"] if c in transforms]


# ---------------------------------------------------------------------------
# Expression / body identification helpers
# ---------------------------------------------------------------------------

def parse_eye_name(name):
    m = re.fullmatch(r"(e_\w+?)_([a-z]\d+)", name)
    return (m.group(1), m.group(2)) if m else None


def parse_mouth_name(name):
    m = re.fullmatch(r"(m_\w+?)_(\d+)", name)
    return (m.group(1), m.group(2)) if m else None


# ---------------------------------------------------------------------------
# Compositing group derivation
# ---------------------------------------------------------------------------

def derive_groups(transforms, body_params):
    """
    Walk 'top' children and group bodies with their following expressions.
    Returns [{bodies, eyes: {base:[frames]}, mouths: {base:[frames]}}].
    """
    top_pid = find_node(transforms, "top")
    if top_pid is None:
        return []

    body_set = set(body_params)
    groups, cur_bodies, cur_eyes, cur_mouths = [], [], {}, {}

    def flush():
        if cur_bodies:
            groups.append({"bodies": list(cur_bodies),
                           "eyes": dict(cur_eyes),
                           "mouths": dict(cur_mouths)})

    for _, go_name in children_names(transforms, top_pid):
        if go_name in body_set:
            if cur_eyes or cur_mouths:
                flush()
                cur_bodies, cur_eyes, cur_mouths = [], {}, {}
            cur_bodies.append(go_name)
        elif go_name == "add_parts":
            pass
        else:
            ep = parse_eye_name(go_name)
            if ep:
                cur_eyes.setdefault(ep[0], []).append(ep[1])
                continue
            mp = parse_mouth_name(go_name)
            if mp:
                cur_mouths.setdefault(mp[0], []).append(mp[1])

    flush()
    return groups


def derive_add_parts(transforms):
    """
    Parse the add_parts subtree.

    Returns:
      {
        "cheek":    [sprite_names],   # shared optional blush layer (basecmn)
        body_name: {
          "add":    [sprite_names],   # standard accessory (no number suffix)
          "addrev": [sprite_names],   # mirrored alternative accessory
          "extras": [sprite_names],   # optional overlays (_add1, _add3, _add5 …)
        },
      }

    Accessory classification for per-body grandchildren:
      name ends with _addrev      -> "addrev"
      name matches _add\\d+ suffix -> "extras"  (ALL numbered adds are optional)
      everything else             -> "add"       (standard _add, always used)
    """
    add_pid = find_node(transforms, "add_parts")
    if add_pid is None:
        return {}

    result = {"cheek": []}
    for c_pid in transforms[add_pid]["children"]:
        if c_pid not in transforms:
            continue
        child_go = transforms[c_pid]["go_name"]
        if child_go == "basecmn":
            for gc_pid in transforms[c_pid]["children"]:
                if gc_pid in transforms:
                    name = transforms[gc_pid]["go_name"]
                    if name not in result["cheek"]:
                        result["cheek"].append(name)
        else:
            add_list, addrev_list, extras_list = [], [], []
            for gc in transforms[c_pid]["children"]:
                if gc not in transforms:
                    continue
                name = transforms[gc]["go_name"]
                if name.endswith("_addrev"):
                    addrev_list.append(name)
                elif re.search(r"_add\d+$", name):   # any numbered add = optional
                    extras_list.append(name)
                else:
                    add_list.append(name)
            result[child_go] = {
                "add":    add_list,
                "addrev": addrev_list,
                "extras": extras_list,
            }
    return result


# ---------------------------------------------------------------------------
# Sprite rect reading  (Transform-corrected world coordinates)
# ---------------------------------------------------------------------------

def load_sprite_rects(env, transforms):
    """Returns {sprite_name: (x, y, w, h)} in Transform-corrected world coords."""
    memo = {}

    def wp(pid):
        return _world_pos(pid, transforms, memo)

    sprite_world: dict = {}

    top_pid = find_node(transforms, "top")
    if top_pid:
        for c_pid, c_name in children_names(transforms, top_pid):
            if c_name not in sprite_world:
                sprite_world[c_name] = wp(c_pid)

    add_pid = find_node(transforms, "add_parts")
    if add_pid:
        for c_pid, c_name in children_names(transforms, add_pid):
            if c_name not in sprite_world:
                sprite_world[c_name] = wp(c_pid)
            for gc_pid, gc_name in children_names(transforms, c_pid):
                if gc_name not in sprite_world:
                    sprite_world[gc_name] = wp(gc_pid)

    rects = {}
    for obj in env.objects:
        if obj.type.name == "Sprite":
            d = obj.read()
            if d.m_PixelsToUnits == 100.0:
                continue
            r = d.m_Rect
            name = d.m_Name
            wx, wy = sprite_world.get(name, (0.0, 0.0))
            rects[name] = (wx + r.x, wy + r.y, r.width, r.height)
    return rects


# ---------------------------------------------------------------------------
# Canvas helpers
# ---------------------------------------------------------------------------

def union_rect(rects_list):
    if not rects_list:
        return (0, 0, 0, 0)
    ls = [r[0] for r in rects_list]
    bs = [r[1] for r in rects_list]
    rs = [r[0]+r[2] for r in rects_list]
    ts = [r[1]+r[3] for r in rects_list]
    l, b, r_, t = min(ls), min(bs), max(rs), max(ts)
    return (l, b, r_-l, t-b)


def world_to_canvas(rect, canvas_rect):
    cx, cy, cw, ch = canvas_rect
    x, y, w, h = rect
    dst_l = int(round(x - cx))
    dst_t = int(round(ch - (y + h - cy)))
    return dst_l, dst_t


# ---------------------------------------------------------------------------
# Frame selection
# ---------------------------------------------------------------------------

def best_eye_frame(frames):
    for p in EYE_FRAME_PREF:
        if p in frames:
            return p
    return frames[0] if frames else None


def best_mouth_frame(frames):
    for p in MOUTH_FRAME_PREF:
        if p in frames:
            return p
    return frames[0] if frames else None


# ---------------------------------------------------------------------------
# Portrait compositing
# ---------------------------------------------------------------------------

def load_png(bundle_name, sprite_name):
    safe = sprite_name.replace("/", "_").replace("\\", "_").replace(" ", "_")
    path = os.path.join(SPRITES_DIR, f"{bundle_name}_{safe}.png")
    if path in _png_cache:
        return _png_cache[path]
    if not os.path.exists(path):
        _png_cache[path] = None
        return None
    img = Image.open(path).convert("RGBA")
    _png_cache[path] = img
    return img


def composite_portrait(layers, sprite_rects, canvas_rect, bundle_name):
    cw, ch = int(round(canvas_rect[2])), int(round(canvas_rect[3]))
    canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    for name in layers:
        img = load_png(bundle_name, name)
        if img is None or name not in sprite_rects:
            continue
        dl, dt = world_to_canvas(sprite_rects[name], canvas_rect)
        if dl < -img.width or dt < -img.height:
            continue
        canvas.alpha_composite(img, dest=(max(dl, 0), max(dt, 0)))
    return canvas


# ---------------------------------------------------------------------------
# Bundle processing
# ---------------------------------------------------------------------------

def process_bundle(bundle_path, out_dir):
    global _png_cache
    _png_cache = {}

    bundle_name = os.path.basename(bundle_path)
    env = UnityPy.load(bundle_path)

    transforms   = build_transform_tree(env)
    sprite_rects = load_sprite_rects(env, transforms)

    body_params = []
    for obj in env.objects:
        if obj.type.name == "MonoBehaviour":
            try:
                t = obj.read_typetree()
                if "m_bodyParameters" in t:
                    body_params = t["m_bodyParameters"]
                    break
            except Exception:
                pass

    if not body_params:
        log(f"  [{bundle_name}] No bodyParameters found, skipping.")
        return

    groups    = derive_groups(transforms, body_params)
    add_parts = derive_add_parts(transforms)
    cheek_layers = add_parts.get("cheek", [])

    def canvas_for_body(body, group):
        """
        Bounding rect for all possible layers of this body so that every
        portrait variant for the same body has the same canvas dimensions.
        """
        relevant = [body]
        for e_base, e_frames in group["eyes"].items():
            f = best_eye_frame(e_frames)
            if f:
                relevant.append(f"{e_base}_{f}")
        for m_base, m_frames in group["mouths"].items():
            f = best_mouth_frame(m_frames)
            if f:
                relevant.append(f"{m_base}_{f}")
        info = add_parts.get(body, {})
        if isinstance(info, dict):
            relevant += info.get("add",    [])
            relevant += info.get("addrev", [])
            relevant += info.get("extras", [])
        if cheek_layers and _BASE_FAMILY_RE.match(body):
            relevant += cheek_layers
        rects = [sprite_rects[n] for n in relevant if n in sprite_rects]
        return union_rect(rects) if rects else sprite_rects.get(body)

    def build_variants(body):
        """
        Return list of (layer_list_suffix, suffix_string) pairs for all optional
        layer combinations relevant to this body.
        """
        info = add_parts.get(body, {})
        if not isinstance(info, dict):
            info = {"add": info, "addrev": [], "extras": []}

        add_list    = info.get("add",    [])
        addrev_list = info.get("addrev", [])
        extras_list = info.get("extras", [])
        use_cheek   = cheek_layers and bool(_BASE_FAMILY_RE.match(body))

        acc_variants = [(add_list, "")]
        if addrev_list:
            acc_variants.append((addrev_list, "_rev"))

        extra_variants = [([], "")]
        if extras_list:
            extra_variants.append((extras_list, "_extra"))

        ck_variants = [([], "")]
        if use_cheek:
            ck_variants.append((cheek_layers, "_blush"))

        return [
            (acc + ext + ck, acc_sfx + ext_sfx + ck_sfx)
            for acc, acc_sfx in acc_variants
            for ext, ext_sfx in extra_variants
            for ck,  ck_sfx  in ck_variants
        ]

    saved = 0
    total_groups = len(groups)

    for gi, group in enumerate(groups):
        eye_exprs   = group["eyes"]
        mouth_exprs = group["mouths"]

        for body in group["bodies"]:
            if body not in sprite_rects:
                continue

            canvas_rect = canvas_for_body(body, group)
            if canvas_rect is None or canvas_rect[2] <= 0 or canvas_rect[3] <= 0:
                continue

            variants = build_variants(body)  # [(extra_layers, suffix), ...]

            # --- Body-only portraits (default / base expression) ---
            for extra_layers, sfx in variants:
                layers = [body] + extra_layers
                img = composite_portrait(layers, sprite_rects, canvas_rect, bundle_name)
                img.save(os.path.join(out_dir, f"{bundle_name}_{body}{sfx}.png"),
                         compress_level=1)
                saved += 1

            # --- Expression-overlaid portraits ---
            if not eye_exprs and not mouth_exprs:
                continue

            eye_iter   = list(eye_exprs.items())   or [(None, [])]
            mouth_iter = list(mouth_exprs.items()) or [(None, [])]

            for e_base, e_frames in eye_iter:
                ef       = best_eye_frame(e_frames) if e_frames else None
                e_sprite = f"{e_base}_{ef}" if (e_base and ef) else None
                e_part   = e_base or "no_eye"

                for m_base, m_frames in mouth_iter:
                    mf       = best_mouth_frame(m_frames) if m_frames else None
                    m_sprite = f"{m_base}_{mf}" if (m_base and mf) else None
                    m_part   = m_base or "no_mouth"

                    expr = ([e_sprite] if e_sprite else []) + ([m_sprite] if m_sprite else [])

                    for extra_layers, sfx in variants:
                        layers = [body] + expr + extra_layers
                        img = composite_portrait(
                            layers, sprite_rects, canvas_rect, bundle_name)
                        fname = f"{bundle_name}_{body}_{e_part}_{m_part}{sfx}.png"
                        img.save(os.path.join(out_dir, fname), compress_level=1)
                        saved += 1

        log(f"  [{bundle_name}] group {gi+1}/{total_groups} ({'+'.join(group['bodies'])}) done")

    log(f"  [{bundle_name}] total saved: {saved} portrait(s)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    global _log_file
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    log_path = os.path.join(OUTPUT_DIR, "progress.log")
    _log_file = open(log_path, "w", encoding="utf-8")

    bundle_files = sorted(
        os.path.join(BUNDLES_DIR, f)
        for f in os.listdir(BUNDLES_DIR)
        if os.path.isfile(os.path.join(BUNDLES_DIR, f))
    )

    log(f"Compositing portraits from {len(bundle_files)} bundle(s) -> {OUTPUT_DIR}")
    log(f"Progress log: {log_path}")

    for path in bundle_files:
        bname = os.path.basename(path)
        log(f"  {bname} ...")
        try:
            process_bundle(path, OUTPUT_DIR)
        except Exception as e:
            import traceback
            log(f"  ERROR in {bname}: {e}")
            traceback.print_exc()

    log("Done.")
    _log_file.close()


if __name__ == "__main__":
    main()
