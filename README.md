# ebooks

Remove DRM from ebooks I've bought and turn them into audiobooks with a local AI voice.

```
inbox/  ──bin/strip-drm──▶  out/Author - Title.epub  ──bin/make-audiobook──▶  out/Author - Title.m4b  ──▶  Android
```

## Workflow

1. Drop the book in `inbox/`. Accepted types: `.acsm` downloads, EPUB, AZW/AZW3, KFX/KFX-ZIP, MOBI, PDF and Kobo files.
2. Run `bin/strip-drm` to get a DRM-free EPUB in `out/`. Originals that worked move to `inbox/done/`.
3. Run `bin/make-audiobook` to create a chaptered M4B next to each EPUB that doesn't already have one.
4. Copy the `.m4b` to the phone (see [Listening on Android](#listening-on-android)).

`bin/strip-drm --keep-format` skips the EPUB conversion, for example to keep a PDF as a PDF.

## Where to buy

Buy from **Kobo** or **Google Play Books** when you can. Both have very large catalogs. Both sell books with Adobe DRM
as an `.acsm` download, and those work entirely on this Linux machine with no Windows needed:

- **Kobo:** go to kobo.com → My Books → the book's ⋯ menu → Download, then pick the EPUB/Adobe option. That gives you an `.acsm` file.
  Some Kobo titles are labeled DRM-free, and their EPUB needs no key.
- **Google Play Books:** go to play.google.com/books → the book's ⋮ menu → Export → "Export ACSM for EPUB".
- **DRM-free shops** need nothing at all: Standard Ebooks, Project Gutenberg, Humble Bundle, Tor/Baen, and many indie authors.
- **Amazon** has the biggest selection but is by far the hardest (see the table below). Use it only for books you can't get elsewhere.
  Kindle Unlimited books are loans and can't be exported.

## Setup

```sh
bin/setup
```

This installs calibre to `~/.local/opt/calibre` with no sudo needed. Plugins go into a private config folder,
`.calibre-config/`, so they don't touch any other calibre setup:

- **DeDRM**, from [Satsuoni's fork](https://github.com/Satsuoni/DeDRM_tools). This fork keeps up with Amazon's 2025+ Kindle DRM.
  Pin a version with `DEDRM_VERSION=v10.0.xx bin/setup`.
- **ACSM Input (DeACSM)**, which downloads `.acsm` purchases the way Adobe Digital Editions would, on Linux.
  Setup builds it from the newest master CI build, because the 2022 release predates calibre 9. That step needs `gh` auth.
- **Obok**, for Kobo desktop libraries.
- **KFX Input**, for Kindle KFX / KFX-ZIP files.
- **Kokoro TTS** in a uv virtualenv at `tts/.venv`. It uses CUDA on the RTX 3060.

### One-time Adobe activation (for Kobo and Google Play)

Over SSH, with no display needed:

First create a **ByteBooks ID** at https://dtsbytebooks.com/transition-help. ByteBooks took over Adobe's
ebook DRM service on 2026-06-23. A plain Adobe ID that works on adobe.com is rejected with "User does not exist"
until it has a ByteBooks ID. If you've used the Adobe ID for ebooks before, use its migrate option with the *same*
email. Otherwise, create a new ByteBooks ID.

```sh
bin/adobe-activate            # prompts for Adobe ID email + password (hidden)
bin/adobe-activate --status   # check it; re-exports backups
```

This links ACSM Input to your Adobe ID, emulating ADE 2.0.1, which is the plugin's recommended default. It then writes
two files to `keys/`: an activation backup ZIP and the `.der` decryption key. Keep copies of both somewhere safe,
because Adobe limits how many activations an account gets. DeDRM picks the key up automatically the next time
`bin/strip-drm` runs. 
With a desktop session instead, `bin/calibre-gui` → Preferences → Plugins → ACSM Input → Customize does the same thing.
That also works over SSH via `ssh -X` if your client runs an X server.

## Keys for other sources

Configure these in `bin/calibre-gui` under Preferences → Plugins → DeDRM → Customize. Keep exported key files in `keys/`,
which is gitignored.

| Source | What DeDRM needs |
|---|---|
| Kobo or Google Play `.acsm` downloads | The ACSM Input activation above. |
| Other Adobe ADEPT EPUB/PDF (library loans, many other stores) | The same Adobe activation, or a `.der` key exported from ADE. |
| Kobo desktop app | The Obok plugin. Kepubs copied off a Kobo e-reader need the device serial instead. |
| Kindle, older books, or books sent via "Download & transfer via USB" | The serial number of a registered e-ink Kindle (DeDRM → eInk Kindle ebooks). |
| Kindle, current KFX-ZIP | Hardest case. You need the Microsoft Store Kindle app on a real Windows install or VM with TPM, plus the version-matched `MSIXKFXArchiver*.exe` from the DeDRM release. That tool produces `.kfx-zip` files and a `.k4i` key. Import the key with DeDRM → Kindle for Mac/PC → Import Existing Keyfiles. Wine does not work for this. |
| Apple Books (FairPlay) | Not supported. |

## Audiobooks

`bin/make-audiobook` reads the EPUB with [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) on the GPU, at roughly
40× realtime on the 3060, so a 10-hour book takes about 15 minutes. It writes an M4B with chapter markers, the cover,
and the title and author.

```sh
bin/make-audiobook --list-chapters book.epub              # see what will be read
bin/make-audiobook --chapters 2-30 book.epub              # skip front/back matter
bin/make-audiobook --sample --voice bm_george book.epub   # audition a voice on the first ~1500 chars
bin/make-audiobook --voice am_michael --speed 1.1 book.epub
```

- **Voices:** the first letter sets the accent (`a` = American, `b` = British). The second letter is `f` or `m`.
  Good ones to try are `af_heart` (the default), `af_bella`, `am_michael`, `am_fenrir`, `bf_emma` and `bm_george`.
  See the [full list](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md).
- **GPU sharing:** if the GPU has less than ~1.5 GB free (for example while the KoboldCpp server is loaded), it falls back
  to the CPU at roughly 4× realtime instead of ~40×. Force a choice with `--device cuda` or `--device cpu`.
- **Resuming:** chapters render to `.tts-work/` first, so re-running an interrupted book picks up where it stopped.
  Delete `.tts-work/<book>` once you're happy with the M4B.

## Listening on Android

- **Players:** [Smart AudioBook Player](https://play.google.com/store/apps/details?id=ak.alizandro.smartaudiobookplayer)
  and [Voice](https://github.com/PaulWoitaschek/Voice) (open source) both handle M4B chapters, remember your position,
  and let you change playback speed.
- **Getting files to the phone:** use USB, Google Drive, or Syncthing set to sync `out/` → the phone's `Audiobooks/` folder.
  Syncthing makes it automatic.
- **Self-hosting:** [Audiobookshelf](https://www.audiobookshelf.org/) is a server with an Android app that streams books
  and syncs progress across devices. It's worth it if you want this to work like an Audible library.
- **No pre-rendering:** to listen to an EPUB directly, ElevenReader (cloud voices, with usage limits) and @Voice Aloud
  Reader (on-device Android voices) both import EPUBs.

Only use this on books you own, for personal use.
