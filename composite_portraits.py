"""
composite_portraits.py
-----------------------
Composites full character portraits from pre-extracted sprite PNGs.

Portrait layer structure:
  1. Body sprite        - base / b1 / b2 / side / back / p0-p5 / dead …
  2. Eye expression     - e_nom_* / e_sml_* / e_p0_* / …
  3. Mouth expression   - m_nom_* / m_sml_* / m_p0_* / …
  4. Accessory          - {body}_add  OR  {body}_addrev  (exactly one)
  5. Extra overlays     - {body}_add1 / _add3 / _add5 / … (optional per body)
  6. Cheek overlay      - base_cheek (optional; base-family bodies only)

Expression matching:
  Only eye/mouth pairs whose core tag matches are combined.
  Core tag = expression base stripped of its e_/m_ prefix and any trailing
  single-letter sub-variant suffix (_s, _j, _i, _a, …).
  e.g.  e_nom, e_nom_s, e_nom_j  all have core "nom" and pair with
        m_nom, m_nom_i, m_nom_a  (also core "nom").

Usage:
  python composite_portraits.py [character] [--rev] [--extra] [--blush] [--all]

  character   Optional character ID, e.g. 012 or a012. Omit to process all.
  --rev       Also generate mirrored-accessory variants  → rev/
  --extra     Also generate optional-overlay variants    → extra/
  --blush     Also generate blush variants               → blush/
  --all       Enable all three flags above.

  Variant subfolders are created inside output_portraits/ as needed.
  The standard (no-flag) output always goes directly into output_portraits/.

Output directory: output_portraits/
Progress log:     output_portraits/progress.log
"""

import os
import re
import argparse
import UnityPy
from PIL import Image

BUNDLES_DIR = os.path.join(os.path.dirname(__file__), "bundles")
SPRITES_DIR = os.path.join(os.path.dirname(__file__), "output")
OUTPUT_DIR  = os.path.join(os.path.dirname(__file__), "output_portraits")

EYE_FRAME_PREF   = ["n1", "n0", "f0", "f1", "b0", "b1", "n2"]
MOUTH_FRAME_PREF = ["1", "0", "2"]

_png_cache: dict = {}
_log_file = None

# Bodies that receive the cheek/blush layer: base, b0-b9, bx.
# Excludes back, backx, side, dead, p0-p5, etc.
_BASE_FAMILY_RE = re.compile(r"^(base|b[0-9x])$")


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


def log(msg):
    print(msg, flush=True)
    if _log_file:
        _log_file.write(msg + "\n")
        _log_file.flush()


# ---------------------------------------------------------------------------
# Hierarchy parsing helpers
# ---------------------------------------------------------------------------

def build_transform_tree(env):
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
# Expression helpers
# ---------------------------------------------------------------------------

def parse_eye_name(name):
    m = re.fullmatch(r"(e_\w+?)_([a-z]\d+)", name)
    return (m.group(1), m.group(2)) if m else None


def parse_mouth_name(name):
    m = re.fullmatch(r"(m_\w+?)_(\d+)", name)
    return (m.group(1), m.group(2)) if m else None


def expression_core(base):
    """
    Extract the core matching tag from an expression base name.
    Strips the e_/m_ prefix and any trailing single-letter sub-variant suffix.
      e_nom   -> nom    e_nom_s  -> nom    e_nom_j  -> nom
      m_nom   -> nom    m_nom_i  -> nom    m_nom_a  -> nom
      e_p0    -> p0     e_p0_s   -> p0
      e_side  -> side   e_dead   -> dead
    """
    _, _, tag = base.partition("_")          # strip e_/m_ prefix
    if re.search(r"_[a-z]$", tag):           # trailing _X single-letter suffix
        tag = tag[:-2]
    return tag


def expr_unique(base, core):
    """
    Return the sub-variant part of an expression base after stripping the
    e_/m_ prefix and the shared core tag.
      e_bld,  core=bld  -> ""    (nothing beyond the core)
      e_nom_a, core=nom -> "a"   (trailing sub-variant letter)
    """
    _, _, tag = base.partition("_")   # drop e_/m_ prefix
    if tag == core:
        return ""
    if tag.startswith(core + "_"):
        return tag[len(core) + 1:]
    return tag  # fallback (shouldn't happen)


# ---------------------------------------------------------------------------
# Compositing group derivation
# ---------------------------------------------------------------------------

def derive_groups(transforms, body_params):
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
    Returns:
      { "cheek": [names],
        body_name: {"add": [names], "addrev": [names], "extras": [names]}, … }

    Classification:
      _addrev      -> "addrev"  (mandatory mirrored alternative)
      _add\\d+      -> "extras"  (optional overlays; all numbered adds)
      everything else -> "add"  (mandatory standard accessory)
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
                elif re.search(r"_add\d+$", name):
                    extras_list.append(name)
                else:
                    add_list.append(name)
            result[child_go] = {"add": add_list,
                                 "addrev": addrev_list,
                                 "extras": extras_list}
    return result


# ---------------------------------------------------------------------------
# Sprite rect loading (Transform-corrected world coordinates)
# ---------------------------------------------------------------------------

def load_sprite_rects(env, transforms):
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
            if d.m_Name.startswith("dice_"):
                continue
            r = d.m_Rect
            name = d.m_Name
            wx, wy = sprite_world.get(name, (0.0, 0.0))
            rects[name] = (wx + r.x, wy + r.y, r.width, r.height)
    return rects


# ---------------------------------------------------------------------------
# Canvas / compositing helpers
# ---------------------------------------------------------------------------

def union_rect(rects_list):
    if not rects_list:
        return (0, 0, 0, 0)
    ls = [r[0] for r in rects_list]
    bs = [r[1] for r in rects_list]
    rs = [r[0]+r[2] for r in rects_list]
    ts = [r[1]+r[3] for r in rects_list]
    return (min(ls), min(bs), max(rs)-min(ls), max(ts)-min(bs))


def world_to_canvas(rect, canvas_rect):
    cx, cy, cw, ch = canvas_rect
    x, y, w, h = rect
    return int(round(x - cx)), int(round(ch - (y + h - cy)))


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


def load_png(char_code, sprite_name):
    safe = sprite_name.replace("/", "_").replace("\\", "_").replace(" ", "_")
    path = os.path.join(SPRITES_DIR, char_code, f"{safe}.png")
    if path in _png_cache:
        return _png_cache[path]
    if not os.path.exists(path):
        _png_cache[path] = None
        return None
    img = Image.open(path).convert("RGBA")
    _png_cache[path] = img
    return img


def composite_portrait(layers, sprite_rects, canvas_rect, char_code):
    cw, ch = int(round(canvas_rect[2])), int(round(canvas_rect[3]))
    canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    for name in layers:
        img = load_png(char_code, name)
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

def process_bundle(bundle_path, out_dir, opts):
    global _png_cache
    _png_cache = {}

    bundle_name = os.path.basename(bundle_path)
    env = UnityPy.load(bundle_path)

    char_code  = get_char_code(env) or bundle_name
    char_dir   = os.path.join(out_dir, char_code)   # base portrait output dir

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

    groups       = derive_groups(transforms, body_params)
    add_parts    = derive_add_parts(transforms)
    cheek_layers = add_parts.get("cheek", [])

    def canvas_for_body(body, group):
        """Bounding rect covering all possible layers so all variants share dimensions."""
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
        Return list of (save_dir, extra_layers, flip) for each enabled variant.
        Standard always goes to char_dir; optional variants to named subdirs.
        The rev variant sets flip=True so the whole portrait is mirrored.
        """
        info = add_parts.get(body, {})
        if not isinstance(info, dict):
            info = {"add": info, "addrev": [], "extras": []}

        add_list    = info.get("add",    [])
        addrev_list = info.get("addrev", [])
        extras_list = info.get("extras", [])
        use_cheek   = cheek_layers and bool(_BASE_FAMILY_RE.match(body))

        acc_opts = [("", add_list, False)]
        if opts.rev and addrev_list:
            acc_opts.append(("rev", addrev_list, True))

        ext_opts = [("", [])]
        if opts.extra and extras_list:
            ext_opts.append(("extra", extras_list))

        ck_opts = [("", [])]
        if opts.blush and use_cheek:
            ck_opts.append(("blush", cheek_layers))

        variants = []
        for acc_sfx, acc_lyr, flip in acc_opts:
            for ext_sfx, ext_lyr in ext_opts:
                for ck_sfx, ck_lyr in ck_opts:
                    parts = [c for c in (acc_sfx, ext_sfx, ck_sfx) if c]
                    subdir_name = "_".join(parts)
                    subdir = char_dir if not subdir_name else os.path.join(char_dir, subdir_name)
                    variants.append((subdir, acc_lyr + ext_lyr + ck_lyr, flip))
        return variants

    def save(img, subdir, fname, flip=False):
        if flip:
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
        os.makedirs(subdir, exist_ok=True)
        img.save(os.path.join(subdir, fname), compress_level=1)

    saved = 0
    total_bodies = sum(len(g["bodies"]) for g in groups)
    body_index = 0

    for gi, group in enumerate(groups):
        eye_exprs   = group["eyes"]
        mouth_exprs = group["mouths"]

        for body in group["bodies"]:
            body_index += 1
            if body not in sprite_rects:
                log(f"  [{char_code}] ({body_index}/{total_bodies}) {body} — skipped (no rect)")
                continue

            canvas_rect = canvas_for_body(body, group)
            if canvas_rect is None or canvas_rect[2] <= 0 or canvas_rect[3] <= 0:
                log(f"  [{char_code}] ({body_index}/{total_bodies}) {body} — skipped (no canvas)")
                continue

            variants = build_variants(body)
            body_saved = 0

            has_exprs = bool(eye_exprs or mouth_exprs)

            # --- Body-only portraits ---
            # For "xxx" (WIP character), always output body-only since expressions
            # are incomplete. For everyone else, only output body-only if there are
            # no expressions to pair with (avoids mouthless-looking portraits).
            if char_code == "xxx" or not has_exprs:
                for subdir, extra_lyr, flip in variants:
                    img = composite_portrait(
                        [body] + extra_lyr, sprite_rects, canvas_rect, char_code)
                    save(img, subdir, f"{body}.png", flip)
                    saved += 1
                    body_saved += 1

            # --- Expression portraits ---
            if not has_exprs:
                continue

            # Group expression bases by core tag; only generate matching pairs.
            eye_by_core: dict = {}
            for e_base, e_frames in eye_exprs.items():
                eye_by_core.setdefault(expression_core(e_base), {})[e_base] = e_frames

            mouth_by_core: dict = {}
            for m_base, m_frames in mouth_exprs.items():
                mouth_by_core.setdefault(expression_core(m_base), {})[m_base] = m_frames

            # --- Mouth-only portraits (e.g. back poses where eyes are hidden) ---
            if not eye_by_core and mouth_by_core:
                for core, m_bases in sorted(mouth_by_core.items()):
                    for m_base, m_frames in m_bases.items():
                        for mf in m_frames:
                            m_sprite = f"{m_base}_{mf}"
                            m_u = expr_unique(m_base, core)
                            m_part = f"m_{m_u}_{mf}" if m_u else f"m_{mf}"
                            if core == body:
                                fname_stem = f"{body}_{m_part}"
                            else:
                                fname_stem = f"{body}_{core}_{m_part}"
                            for subdir, extra_lyr, flip in variants:
                                img = composite_portrait(
                                    [body, m_sprite] + extra_lyr,
                                    sprite_rects, canvas_rect, char_code)
                                save(img, subdir, f"{fname_stem}.png", flip)
                                saved += 1
                                body_saved += 1

            for core in sorted(set(eye_by_core) & set(mouth_by_core)):
                for e_base, e_frames in eye_by_core[core].items():
                    for ef in e_frames:
                        e_sprite = f"{e_base}_{ef}"

                        for m_base, m_frames in mouth_by_core[core].items():
                            for mf in m_frames:
                                m_sprite = f"{m_base}_{mf}"
                                expr = [e_sprite, m_sprite]

                                # Filename: {body}_{core}_e_{e_unique+frame}_m_{m_unique+frame}
                                # e.g. base_bld_e_b0_m_0  or  base_nom_e_a_b0_m_0
                                # When core == body (e.g. pose p1 with e_p1/m_p1),
                                # omit the redundant core: p1_e_f0_m_1 not p1_p1_e_f0_m_1
                                e_u = expr_unique(e_base, core)
                                m_u = expr_unique(m_base, core)
                                e_part = f"e_{e_u}_{ef}" if e_u else f"e_{ef}"
                                m_part = f"m_{m_u}_{mf}" if m_u else f"m_{mf}"
                                if core == body:
                                    fname_stem = f"{body}_{e_part}_{m_part}"
                                else:
                                    fname_stem = f"{body}_{core}_{e_part}_{m_part}"

                                for subdir, extra_lyr, flip in variants:
                                    img = composite_portrait(
                                        [body] + expr + extra_lyr,
                                        sprite_rects, canvas_rect, char_code)
                                    fname = f"{fname_stem}.png"
                                    save(img, subdir, fname, flip)
                                    saved += 1
                                    body_saved += 1

            log(f"  [{char_code}] ({body_index}/{total_bodies}) {body} — {body_saved} portrait(s)")

    log(f"  [{char_code}] total saved: {saved} portrait(s)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    global _log_file

    parser = argparse.ArgumentParser(
        description="Composite character portraits from Unity asset bundles.")
    parser.add_argument(
        "character", nargs="?",
        help="Character ID to process, e.g. avi. Omit to process all.")
    parser.add_argument(
        "--rev", action="store_true",
        help="Also generate mirrored-accessory variants in a rev/ subfolder.")
    parser.add_argument(
        "--extra", action="store_true",
        help="Also generate optional-overlay variants in an extra/ subfolder.")
    parser.add_argument(
        "--blush", action="store_true",
        help="Also generate blush variants in a blush/ subfolder.")
    parser.add_argument(
        "--all", dest="all_variants", action="store_true",
        help="Enable all optional variant flags (--rev --extra --blush).")
    opts = parser.parse_args()
    if opts.all_variants:
        opts.rev = opts.extra = opts.blush = True

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    log_path = os.path.join(OUTPUT_DIR, "progress.log")
    _log_file = open(log_path, "w", encoding="utf-8")

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
            # Match by bundle number (e.g. "001" or "1" matches "a001")
            if bname.lstrip("a") == query.lstrip("a"):
                bundle_files.append(path)
                continue
            # Match by char code (e.g. "avi") — requires a quick load
            env = UnityPy.load(path)
            if get_char_code(env) == query:
                bundle_files.append(path)
        if not bundle_files:
            print(f"No bundle matching '{opts.character}' found in {BUNDLES_DIR}")
            return
    else:
        bundle_files = all_files

    log(f"Compositing portraits from {len(bundle_files)} bundle(s) -> {OUTPUT_DIR}")
    log(f"Progress log: {log_path}")

    for path in bundle_files:
        bname = os.path.basename(path)
        log(f"  {bname} ...")
        try:
            process_bundle(path, OUTPUT_DIR, opts)
        except Exception as e:
            import traceback
            log(f"  ERROR in {bname}: {e}")
            traceback.print_exc()

    log("Done.")
    _log_file.close()


if __name__ == "__main__":
    main()
