# Paranormasight Datamining Tools
Various tools for working with the specific quirks of the unity bundles in the Paranormasight series. Mostly developed for and tested with The Mermaid's Curse, but may also be useful for The Seven Mysteries of Honjo.

Sprite-related scripts require the UnityPy package to be installed.

## Scripts

### trim_unity.py
Takes in a folder of the asset bundles, e.g. a001, from the game files and removes the garbage data before the UnityFS header. Depending on the program you're using to read these, this may not be necessary, but it can help. Make sure to back up the original files.

### trim_hca.py
Takes in a `.sab.bytes` file from audio asset bundles in The Mermaid's Curse and extracts the HCA format music data. This is only relevant to The Mermaid's Curse — Seven Mysteries of Honjo provides usable audio files directly, instead of Square Enix's SEAD format. Note that VGMStream is supposed to be able to read SEAD but fails with this game, hence the need for this step.

### inspect_bundles.py
Reads character sprite asset bundles from `/bundles/` and writes JSON files to `/inspection/` describing how each character's sprites are assembled: body parts, expression overlays, accessory layers, and their positions. The two scripts below depend on this output.

### reconstruct_sprites.py
Decodes the diced texture atlases in `/bundles/` and reconstructs them into individual sprite PNGs, saved to `/output/{char_code}/` (e.g. `output/avi/`, `output/snb/`). These are the raw sprite pieces — body, eyes, mouth, accessories — rather than finished portraits.

```
python reconstruct_sprites.py [character]
```

The optional `character` argument accepts either a three-letter character code (e.g. `avi`) or a bundle number (e.g. `001` or `a001`). Omit it to process all bundles.

### composite_portraits.py
Composites finished character portraits by layering body, expression, and accessory sprites according to the assembly data from `/inspection/`. Output is saved to `/output_portraits/{char_code}/`. A progress log is written to `/output_portraits/progress.log`.

```
python composite_portraits.py [character] [--rev] [--extra] [--blush] [--all]
```

The optional `character` argument works the same as in `reconstruct_sprites.py`.

**Portrait types generated:**
- **Standard portraits** — body + mandatory accessories + all eye/mouth expression combinations. Eye and mouth tags must match (e.g. `nom` eyes only pair with `nom` mouth). For characters with no expression overlays (back views, dead poses, etc.), a single body-only image is produced instead.
- **`--rev`** — also generates a horizontally-flipped variant for characters with a reversed-accessory pose, saved in a `rev/` subfolder.
- **`--extra`** — also generates variants with optional overlay layers (e.g. blood splatter, sweat), saved in an `extra/` subfolder.
- **`--blush`** — also generates blush variants for base-family bodies (`base`, `b0`–`b9`, `bx`), saved in a `blush/` subfolder.
- **`--all`** — enables all three optional flags at once.

Optional variants can be combined; combined variants are placed in merged subfolders (e.g. `rev_blush/`).

**Output filename format:** `{body}_{core}_e_{eye_frame}_m_{mouth_frame}.png`, e.g. `base_nom_e_b0_m_0.png`. Body-only portraits are simply `{body}.png`.

Note: `reconstruct_sprites.py` must be run first to populate the `/output/` sprite folders before compositing.

### make_preview_gif.py
Assembles all portrait PNGs for a given character and body variant into an animated GIF, cycling through them in filename order (grouped by expression core, then eye frame, then mouth frame).

```
python make_preview_gif.py [char_code] [body] [--fps N] [--bg RRGGBB] [--out FILE]
```

- `char_code` — three-letter character code (default: `avi`)
- `body` — body variant prefix to match (default: `b1`)
- `--fps` — playback speed in frames per second (default: 4)
- `--bg` — background colour as a hex RGB value, e.g. `ffffff` (default: `222222`)
- `--out` — output path for the GIF (default: `{char_code}_{body}_preview.gif`)

Only reads directly from `output_portraits/{char_code}/`; optional variant subfolders (`rev/`, `blush/`, etc.) are not included.

## Information

For record-keeping, here's a summary of the contents of each asset bundle.
- a000: Backgrounds
- a001: Arnav Barnum Sprites
- a002: Azami Kumoi
- a003: Circe Lunarlight
- a004: Storyteller
- a005: Sodo Kiryu
- a006: Shinobu Wakamura
- a007: Sato Shiranami
- a008: Shotaro Wakamura
- a009: Shogo Okiie (unused)
- a010: Tsukasa Awao
- a011: Tsuyu Minakuchi
- a012: Yumeko Shiki
- a013: Yuza Minakuchi
- a014: Kikuko Tsutsui
- a015: Chie Toyama
- a016: Kippei Ikoma
- a017: Masaru Ide
- a018: Yoshiatsu Yamashina

- a020: Misc data
- a021: Misc images: UI, one-off character sprites (e.g. dead), background objects
- a022: Map images
- a023: Menu icons
- a024: Scene scripts
- a025: BGM, in unfriendly format
- a026: Sound effects
- a027: Dummy container for voice lines, same as PNS1
- a028: Ambience

- a034: Transitions (e.g. wipes)
- a035: More UI assets
- a036: Game text
- a037: VFX
- a038: More/duplicate UI assets
- a039: 3D assets (diving)

- a050: Azusa Somekawa sprites
- a051: WIP Kikuko (unused, for testing)
- a052: Sobae sprites
