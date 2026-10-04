# note: this document describes the capabilities and limitations of the native `com.apple.MercuryPoster` lock-screen wallpaper engine on iOS 27, based on on-device inspection of the `PRBPosterExtensionDataStore`.

## 1. What MercuryPoster Is

`com.apple.MercuryPoster` is the native lock-screen wallpaper provider on iOS 26.2+/27, peer of `com.apple.WallpaperKit.CollectionsPoster` (the Marble / iOS 16-era format). MercuryPoster powers the all-new lock-screen rendering pipeline on iOS 26+.

---

## 2. On-Device Structure

```
PRBPosterExtensionDataStore/61/Extensions/com.apple.MercuryPoster/
  ProviderInfo.plist
  configurations/<UUID>/
    com.apple.posterkit.role.identifier  ← PRPosterRoleLockScreen
    com.apple.posterkit.provider.descriptor.identifier
    providerInfo.plist
    versions/3/                          ← version 3 (CollectionsPoster uses 0)
      com.apple.posterkit.provider.instance.renderingConfiguration.plist
      com.apple.posterkit.provider.instance.complicationLayout.plist
      com.apple.posterkit.provider.instance.titleStyleConfiguration.plist
      com.apple.posterkit.provider.instance.quickActions.plist
      RuntimeSnapshotMetadata-{hash}-lock.plist
      RuntimeSnapshotMetadata-{hash}-home.plist
      RuntimeSnapshotColorStatisticsMetadata-{hash}-lock.plist
      RuntimeSnapshotColorStatisticsMetadata-{hash}-home.plist
      RuntimeSnapshot-{hash}-lock.atx    ← 3.2 MB, snapshot in .atx format
      RuntimeSnapshot-{hash}-home.atx    ← 3.2 MB, snapshot in .atx format
      supplements/0/
      contents/
```

On iOS 27 (24A435) only **one** configuration ships: `FFC91C29-91A7-42E0-A46C-00AFE0C3A8F4`.

---

## 3. RuntimeSnapshot (.atx) Format

The key element of MercuryPoster is the binary `.atx` files (Apple Texture format).

Fully reverse-engineered from a live iOS 27.0.1 (`24A446`) device, iPhone 15 (`iPhone15,4`),
UDID `00008120-0006155436F0E01E`, 3,293,208 bytes each for `-lock.atx` and `-home.atx`.

### 3.1 What the file actually is

A `.atx` snapshot is **not** a mesh, a layer stack or a depth map. It is a **single
flat ASTC-compressed RGBA texture** — one already-composited frame for one role:

| Property | Value |
|---|---|
| Container | `AAPL\x0d\x0a\x1a\x0a` |
| Payload codec | ASTC, 4×4 blocks, 16 bytes each |
| Texture | 320×640 blocks → **1280×2560 px RGBA** |
| Block count | 204800 (exact, byte-aligned) |
| Payload size | 3,276,800 bytes |
| Alpha | uniformly 255 (opaque composite) |

1280×2560 is the render target **padded up** from the 1179×2556 device pixels. This matches
the earlier guess that the snapshot is "a dense graphics format (compressed texture data)",
but rules out the earlier assumption that it carries a mip-map pyramid — there is exactly
**one** ASTC level in the file.

Because the frame is already flattened, the depth/parallax information is **baked into the
pixels**. It is not recoverable from the snapshot; it lives upstream in the layer stack.

### 3.2 Byte layout

```
0x0000  8   magic "AAPL\x0d\x0a\x1a\x0a"
0x0008  4   u32 84 — HEAD chunk size (tag + payload, ends at 0x0060)
0x000C  4   "HEAD"
0x0010  4   u32 1 — version
0x0020  4   u32 37808   (meaning unconfirmed)
0x0024  4   u32 6408    (meaning unconfirmed)
0x0028  4   u32 1179 — texture width, device pixels
0x002C  4   u32 2556 — texture height, device pixels
0x0030  ..  u32 flags / counters (1,0,1,1,1,0,1)
0x004C  16  trailer signature 67 44 5d ff 0b 88 0e ab 67 76 e0 b6 a2 b6 15 e3
0x005C  4   u32 3 — chunk count
0x0060  12  chunk entry: u32 id=1, u32 size=16264, char[4] "FILL"
0x006C  ..  FILL body: 16264 zero bytes — reserved headroom for the chunk table
0x3FF4  4   u32 3276820 — size of the following chunk, counted from the "astc" magic
0x3FF8  4   "astc" — payload magic
0x3FFC  4   u32 3276816
0x4000  ..  204800 × 16-byte ASTC 4×4 blocks
end     16  trailer signature, repeated verbatim
end      4  "END "
```

Chunk table entries are `{u32 id, u32 size, char[4] tag}` (12 bytes). Only the `FILL`
reservation is populated in this snapshot.

### 3.3 Verification

Decoding with `texture2ddecoder.decode_astc(payload, 1280, 2560, 4, 4)` returns exactly
13,107,200 bytes (1280×2560×4) and yields a coherent image:

- alpha channel uniformly 255 (opaque composite);
- horizontal band means form a smooth gradient, e.g. lock screen
  `(71,12,38) → (85,18,47) → (99,24,56) → (120,34,67) → (168,61,88) → (149,45,63) → … → (97,17,56)`,
  i.e. real wallpaper content, not decompression garbage.

`-lock.atx` and `-home.atx` differ in 4.2% of pixels (136,759 of 3,276,800), and the
difference bounding box spans nearly the whole frame (`x 0..1279, y 40..2435`), so MercuryPoster
renders a genuinely different scene per role rather than only a different clock overlay.

### 3.4 Snapshot metadata plist

Metadata that accompanies the texture:

Snapshot metadata plist:
```
PUIPosterSnapshotBundleInfoKeyAssetSize: {393, 852}
PUIPosterSnapshotBundleInfoKeyScale: 3.0
PUIPosterSnapshotBundleInfoKeyDeviceInterfaceOrientation: 1
PUIPosterSnapshotBundleInfoKeyHasColorStatistics: 1
PUIPosterSnapshotBundleInfoKeyPosterProvider: com.apple.MercuryPoster
PUIPosterSnapshotBundleInfoKeySnapshotImageFormat: atx
PUIPosterSnapshotBundleInfoKeySnapshotVersion: 15
```

---

## 4. Capabilities

| Capability | Supported | Notes |
|---|---|---|
| Depth button | Yes | native renderer, `depthEffectDisabled: false` |
| Parallax / gyro | Yes | `motionEffectsDisabled: false` |
| Quick actions (camera) | Yes | `quickActions.plist` on lock screen |
| Complication layout | Yes | clock, complications |
| Lock → home transition animation | Yes | separate lock + home `.atx` snapshots |
| LKState animations (chest opening, breathing, etc.) | No | no CAML → no LKState |
| Text / interactive layers | No | pure bitmap snapshot |
| Custom `wallpaper.ca` | No | MercuryPoster does not parse this format |
| Hot-swappable content (`.tendies`) | Partially | snapshot only replacable if `.atx` can be generated |

---

## 5. The Two iOS 27 Lock-Screen Formats Compared

| | **CollectionsPoster** (Marble) | **MercuryPoster** |
|---|---|---|
| Extension ID | `com.apple.WallpaperKit.CollectionsPoster` | `com.apple.MercuryPoster` |
| Config version | 0 (Versions/0) | 3 (Versions/3) |
| Main content | `wallpaper.ca/main.caml` (CAML ParameterizedCA) | `RuntimeSnapshot-{hash}-{state}.atx` (bitmap) |
| Wallpaper.plist | Yes | No |
| Depth button | Native iOS 27 wallpapers only | Yes (native renderer) |
| LKState animations | Renderer does not play them (native Marble ships empty `<states/>`) | No CAML → no animations |
| Parallax / gyro groups | CAML gyro groups | built into the snapshot |
| Render type | CollectsParams → CA → texture → post | snapshot rendered ahead by the engine |
| Customization | High (edit CAML layers) | Low (`.atx` is opaque) |
| Example | Marble Four, stock "lemon" wallpaper | single FFC91C29 configuration |

---

## 6. Where the Depth Effect Actually Lives

Verified on-device on iOS 27.0.1. **There is no grayscale depth map anywhere.** A sweep of the
PosterBoard sqlite (`posterAttributes`) and of every provider plist found no depth field. The
only depth-related keys in the entire store are two booleans in
`PRPosterRenderingConfiguration`:

```
depthEffectDisabled : Bool
motionEffectsDisabled : Bool
```

Depth is expressed structurally, as **separated layers with a z-position**, and the parallax
comes from moving those layers at different rates.

### 6.1 MercuryPoster — layers authored by the artist

MercuryPoster ships its depth already decomposed, as a `.wallpaper` bundle of CoreAnimation
layer bundles (found under `com.apple.WallpaperKit.CollectionsPoster`, same PosterKit pipeline):

```
7400.WWDC_2022_Background-390w-844h@3x~iphone.ca/assets/Head Mask.HEIC   ← subject, with alpha
7400.WWDC_2022_Foreground-390w-844h@3x~iphone.ca/assets/Body.HEIC
7400.WWDC_2022_Floating-390w-844h@3x~iphone.ca/assets/ubuntu-icon.png
                                            + index.xml, assetManifest.caml,
                                              Main.caml, Root_Layer.js
```

### 6.2 Photos PNG — layers generated on device

A plain PNG from the camera roll is handled by a different provider,
`com.apple.PhotosUIPrivate.PhotosPosterProvider`, at
`configurations/<cfg>/versions/0/contents/<asset>/`. iOS derives the layers itself:

```
input.segmentation/                      ← on-device ML segmentation
├── segmentation.data.aar      7.8 KB    ← AA01/TYP1/FPATP + bplist, version 79
└── asset.resource/
    ├── Adjusted.JPG         2.0 MB
    └── proxy.heic             315 KB
output.layerStack/                       ← the actual parallax layers
├── Contents.json
├── portrait-layer_spatial-photo-foreground.spatialocclusion          z=10.0     29 B
├── portrait-layer_spatial-photo-background.mxi                       z=5.0   7.6 MB
├── portrait-layer_background.HEIC                                    z=5.0    361 KB
├── portrait-layer_background-backfill.HEIC                           z=4.5    599 KB
├── portrait-layer_spatial-photo-background-backfill.mxi              z=4.5  10.8 MB
└── portrait-layer_spatial-photo-foreground-backfill.spatialocclusion z=9.5     29 B
```

- **`.mxi` is the depth representation.** Container `TFHC`, brand `ixm!`; the header is
  immediately followed by a **1024 × 272 grid of float32 values** — a vertex height-field that
  PosterKit displaces for parallax. It is a mesh, not a grayscale map.
- **`.spatialocclusion` carries no data.** The file is exactly 29 bytes: the ASCII string
  `Spatial Photo Occlusion Layer`. It is a sentinel telling the compositor that the layer has
  occlusion; the actual subject lives in the mesh.
- **`-backfill` layers are oversized** (`3025×4033` versus a `visibleFrame` of `1612×3495`) so
  that shifting the layer during parallax never exposes an edge.
- `Contents.json` drives it: `depthEnabled: true`, `spatialPhotoEnabled: true`,
  `parallaxDisabled: false`, `userAdjustedVisibleFrame: true`, plus `portraitLayout` with
  `salientContentFrame`, `adaptiveTimeFrame` and `clockAreaLuminance`.
- `segmentation.data.aar` carries the ML verdicts: `spatialPhotoStatus: 3`,
  `scores.segmentation` / `scores.crop` / `scores.layout`, a 31×31 `lightMap`,
  `colorAnalysis`, and `spatialPhotoLayoutsByDisplayContext["393x852@3x"]` — the layout is
  computed per display context.

### 6.3 Consequence for wallpaper tooling

MercuryPoster and a Photos PNG converge on the same pipeline; only the *source* of the layers
differs (authored `.wallpaper` bundle vs. on-device `input.segmentation`). Both end up flattened
into the role-specific `.atx` described in section 3 — which is where the depth is lost.

Because the `.atx` filename embeds the sha1 of its content
(`RuntimeSnapshot-<sha1>-lock.atx`), a stale snapshot is not invalidated automatically when the
wallpaper changes. GoldenNugget currently never references `.atx` or `RuntimeSnapshot` at all
(`rg 'atx|RuntimeSnapshot' src/` → 0 hits), so old snapshots are never removed on apply.

---

## 7. The "Mercury SimpleMinecraftChest" Experiment

`build_mercury_chest.py` built a tendie that:
1. Took the CAML from `iPhone 17.tendies` (Marble)
2. Placed it under `descriptors/Mercury SimpleMinecraftChest`
3. GoldenNugget routes any folder named with `mercury` → `com.apple.MercuryPoster`

**Problem**: MercuryPoster **does not read** `wallpaper.ca`. It looks for `.atx` snapshots. As a result:
- CAML wallpaper dropped into Mercury → renders as empty / placeholder
- The depth button never appears for the same reason
- Parallax does not work

This confirms MercuryPoster and CollectionsPoster are **two separate rendering pipelines** on iOS 27.

---

## 8. Takeaways for Development

1. **Depth button** appears only on native MercuryPoster wallpapers (`.atx` snapshots). Custom CollectionsPoster configurations (Marble format) cannot get the button — this is a render-engine limitation, not a plist one.

2. **LKState animations** (chest opening, breathing, etc.):
   - CollectionsPoster: ignored — native Marble ships empty `<states/>`
   - MercuryPoster: impossible — no CAML, animations cannot be authored through snapshots

3. **Custom lock-screen wallpapers on iOS 27**:
   - Only working path: CollectionsPoster + ParameterizedCA `wallpaper.ca`
   - Parallax (gyro groups) works
   - Static layers work
   - State animations (Locked/Unlock/Sleep) do not work

4. **Generating `.atx` snapshots**:
   - Format is now understood (section 3): `AAPL` container wrapping one flat
     ASTC 4×4 RGBA texture of 1280×2560 px, 204800 blocks
   - Because it is a plain texture container, a custom `.atx` **is** generatable —
     encode a flattened 1280×2560 frame to ASTC 4×4 and wrap it
   - Still missing: how the engine decides when to (re)render, so a hand-written
     `.atx` risks being overwritten or ignored

5. **Stale snapshots must be removed on wallpaper change.** The `.atx` filename embeds the
   sha1 of its content (`RuntimeSnapshot-<sha1>-lock.atx`), so iOS has no way to notice the
   wallpaper changed. GoldenNugget never references `.atx`/`RuntimeSnapshot`
   (`rg 'atx|RuntimeSnapshot' src/` → 0 hits) and therefore leaves old snapshots in place
   after an apply, which can make the device keep rendering the previous wallpaper.

6. **Best achievable result** for custom wallpapers:
   - Format: Marble / parameterized `wallpaper.ca`
   - Split content: Background (fill) + Floating (objects) + parallax groups
   - Depth cannot be enabled, but parallax can

---

## 9. References

- PosterBoard path: `/Library/Application Support/PRBPosterExtensionDataStore/61/Extensions/com.apple.MercuryPoster`
- Experiment script: `/tmp/.private/awesomenull/opencode/build_mercury_chest.py`
- Tendie output: `/home/awesomenull/Загрузки/SimpleMinecraftChest-Mercury.tendies`
- On-device Mercury config: `ipsw_work/pb_store/reconstructed/.../FFC91C29-91A7-42E0-A46C-00AFE0C3A8F4`
- Rendering config: `renderingConfiguration.plist` → `motionEffectsDisabled: false, depthEffectDisabled: false` (matches Marble)