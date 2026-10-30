# ebooks repo

The user buys ebooks and removes the DRM for personal text-to-speech listening on Android. See README.md.

- "Strip the DRM" means: run `bin/strip-drm` (it processes `inbox/`) and report what ended up in `out/`.
- "Make an audiobook" means: run `bin/make-audiobook --list-chapters <epub>` first. Pick a `--chapters` range that
  skips front and back matter (copyright pages, ads, license text), then run it. A full book takes about 15 minutes per
  10 hours of audio, so run it in the background.
- calibre lives at `~/.local/opt/calibre`. It always runs with `CALIBRE_CONFIG_DIRECTORY=.calibre-config` (the scripts set this),
  because the ACSM Input activation and DeDRM key config are stored there.
- Adobe activation is `bin/adobe-activate`. The user runs it in their own terminal, since it prompts for their password.
  Never ask for the password in chat.
- When a book fails with "still DRM-protected", the fix is a missing key for that store. Point to the Keys section in
  README.md. Don't try other cracking approaches.
- Never commit anything from `inbox/`, `out/`, `keys/`, `.calibre-config/` or `.tts-work/`.
