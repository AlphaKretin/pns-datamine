# Paranormasight Datamining Tools
Various tools for working with the specific quirks of the unity bundles in the Paranormasight series. Mostly developed for and testing with The Mermaid's Curse, but may also be useful for The Seven Mysteries of Honjo.

Sprite-related scripts require the UnityPy package to be installed.

## Scripts

### trim_unity.py
Takes in a folder of the asset bundles, e.g. a001, from the game files and removes the garbage data before the UnityFS header. Depending on the program you're using to read these, this may not be necessary, but it can help. Make sure to back up the original files

### trim_hca.py
Takes in .sab.bytes file from audio asset bundles in The Mermaid's Curse and extracts the hca format music data from them. This is only relevant to The Mermaid's Curse - Seven Mysteries of Honjo provides usable audio files directly, instead of Square Enix's SEAD format. Note that VGMStream is supposed to be able to read SEAD, but fails with this game, hence the need for this step.

### inspect_bundles.py
Looks through asset bundles in the `/bundles/` directory, expecting those containing character sprites. Creates json files in the `/inspection/` directory that contains information on how the sprites are assembled, for use with the two scripts below.

### reconstruct_sprites.py
Extracts the diced character textures from the asset bundles in the `/bundles/` directory and uses the information in the `/inspection/` directory to reconstruct them into coherent sprites placed in the `/output/` directory. Note that these are not full character sprites, but instead the individual pieces that make them up. For that, you want the next script.

### composite_portraits.py
Uses the information in the `/inspection/` directory and the sprites in the `/output/` directory to assemble complete character portraits by layering the different elements together in all the appropriate combinations, creating them in the ``output_portraits/` directory. Note that some sprites do not appear perfectly correct, and that this will take a long time to run and generate 10 GB of images!

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
- a025: BGM, in unfriendtly format
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
- a051: WIP Kikuko (unsued, for testing)
- a052: Sobae sprites