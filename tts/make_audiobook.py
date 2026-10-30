"""Turn DRM-free EPUBs into chaptered M4B audiobooks with local Kokoro TTS.

Usage: bin/make-audiobook [options] [EPUB ...]   (default: every out/*.epub without an .m4b)

Chapters render to .tts-work/<book>/NNN.wav first, so an interrupted run
resumes where it stopped. The finished .m4b lands next to the EPUB in out/.
"""
import argparse
import re
import subprocess
import sys
import time
import warnings
from pathlib import Path

import ebooklib
import imageio_ffmpeg
import numpy as np
import soundfile as sf
from bs4 import BeautifulSoup
from ebooklib import epub

REPO = Path(__file__).resolve().parent.parent
OUT, WORK = REPO / "out", REPO / ".tts-work"
RATE = 24000
PARAGRAPH_GAP = np.zeros(int(RATE * 0.35), dtype=np.float32)
CHAPTER_TAIL = np.zeros(int(RATE * 1.5), dtype=np.float32)
BLOCK_TAGS = ["p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "br", "tr"]

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)


def toc_titles(book):
    titles = {}

    def walk(nodes):
        for node in nodes:
            if isinstance(node, tuple):
                node, children = node
                walk(children)
            href = getattr(node, "href", None)
            if href:
                titles.setdefault(href.split("#")[0], node.title)

    walk(book.toc)
    return titles


def chapters(book, min_chars):
    """Yield (title, text) for each spine document with enough text to read."""
    titles = toc_titles(book)
    for idref, _ in book.spine:
        item = book.get_item_with_id(idref)
        if item is None or item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        soup = BeautifulSoup(item.get_content(), "html.parser")
        for tag in soup(["script", "style", "nav"]):
            tag.decompose()
        for tag in soup.find_all(BLOCK_TAGS):
            tag.insert_after("\n")
        text = re.sub(r"[ \t\xa0]+", " ", soup.get_text())
        text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        if len(text) < min_chars:
            continue
        heading = soup.find(["h1", "h2", "h3"])
        title = titles.get(item.get_name()) or (heading.get_text(" ", strip=True) if heading else None)
        yield (title or "")[:80], text


def cover_image(book, dest):
    candidates = list(book.get_items_of_type(ebooklib.ITEM_COVER))
    candidates += [i for i in book.get_items_of_type(ebooklib.ITEM_IMAGE) if "cover" in i.get_name().lower()]
    if not candidates:
        return None
    item = candidates[0]
    path = dest / ("cover" + Path(item.get_name()).suffix.lower())
    path.write_bytes(item.get_content())
    return path


def synthesize(pipeline, text, voice, speed, dest):
    pieces = []
    for result in pipeline(text, voice=voice, speed=speed, split_pattern=r"\n+"):
        if result.audio is not None:
            pieces += [result.audio.cpu().numpy().astype(np.float32), PARAGRAPH_GAP]
    pieces.append(CHAPTER_TAIL)
    tmp = dest.with_suffix(".tmp.wav")
    sf.write(tmp, np.concatenate(pieces), RATE)
    tmp.rename(dest)


def meta_escape(s):
    return re.sub(r"([=;#\\\n])", r"\\\1", s)


def assemble(wavs, titles, meta, cover, dest, work):
    lines = [";FFMETADATA1", f"title={meta_escape(meta['title'])}", f"album={meta_escape(meta['title'])}",
             f"artist={meta_escape(meta['author'])}", "genre=Audiobook"]
    start = 0
    for wav, title in zip(wavs, titles):
        end = start + int(sf.info(wav).duration * 1000)
        lines += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={start}", f"END={end}", f"title={meta_escape(title)}"]
        start = end
    (work / "chapters.txt").write_text("\n".join(lines) + "\n")
    (work / "concat.txt").write_text("".join(f"file '{w.name}'\n" for w in wavs))

    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
           "-f", "concat", "-safe", "0", "-i", str(work / "concat.txt"),
           "-i", str(work / "chapters.txt")]
    if cover:
        cmd += ["-i", str(cover), "-map", "2:v", "-c:v", "copy", "-disposition:v", "attached_pic"]
    cmd += ["-map", "0:a", "-map_metadata", "1", "-map_chapters", "1",
            "-c:a", "aac", "-b:a", "64k", "-ac", "1", "-movflags", "+faststart", "-f", "mp4", str(dest)]
    subprocess.run(cmd, check=True)


def parse_range(spec, n):
    """'1-3,5,8-' -> [1, 2, 3, 5, 8, ..., n]"""
    picked = []
    for part in spec.split(","):
        lo, _, hi = part.partition("-")
        picked += range(int(lo or 1), int(hi or n) + 1) if "-" in part else [int(lo)]
    return [i for i in picked if 1 <= i <= n]


def first_meta(book, field, default):
    values = book.get_metadata("DC", field)
    return values[0][0] if values else default


def convert(path, args, pipeline):
    book = epub.read_epub(str(path), options={"ignore_ncx": False})
    meta = {"title": first_meta(book, "title", path.stem), "author": first_meta(book, "creator", "Unknown")}
    chs = [(title or f"Chapter {i}", text) for i, (title, text) in enumerate(chapters(book, args.min_chars), 1)]
    if args.list_chapters:
        for i, (title, text) in enumerate(chs, 1):
            print(f"  {i:3d}. {title}  ({len(text):,} chars)")
        return
    if args.chapters:
        chs = [chs[i - 1] for i in parse_range(args.chapters, len(chs))]
    if args.sample:
        chs = [("Sample", chs[0][1][:args.sample])] if chs else []
    if not chs:
        raise RuntimeError("no readable text found")

    suffix = f".sample-{args.voice}" if args.sample else ""
    dest = path.with_name(path.stem + suffix + ".m4b")
    work = WORK / (path.stem + suffix) / f"{args.voice}-{args.speed}"
    work.mkdir(parents=True, exist_ok=True)

    total = sum(len(t) for _, t in chs)
    done_chars, t0 = 0, time.time()
    wavs = []
    for i, (title, text) in enumerate(chs, 1):
        wav = work / f"{i:03d}.wav"
        if not wav.exists():
            synthesize(pipeline, text, args.voice, args.speed, wav)
        wavs.append(wav)
        done_chars += len(text)
        elapsed = time.time() - t0
        print(f"  [{i}/{len(chs)}] {title[:50]:<50} {100 * done_chars / total:5.1f}%  {elapsed / 60:5.1f} min", flush=True)

    assemble(wavs, [t for t, _ in chs], meta, cover_image(book, work), dest, work)
    hours = sum(sf.info(w).duration for w in wavs) / 3600
    print(f"  OK -> {dest.relative_to(REPO) if dest.is_relative_to(REPO) else dest}  ({hours:.1f} h audio)")


def pick_device(choice):
    """Kokoro needs ~1.5 GB of VRAM; other GPU tenants (e.g. a resident LLM server) can leave less."""
    import torch
    if choice != "auto":
        return choice
    if torch.cuda.is_available() and torch.cuda.mem_get_info()[0] > 1.5 * 2**30:
        return "cuda"
    print("  (GPU busy or unavailable; using CPU, which is several times slower)")
    return "cpu"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--voice", default="af_heart",
                    help="Kokoro voice: af_heart, af_bella, am_michael, am_fenrir, bf_emma, bm_george, ... (default af_heart)")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto",
                    help="auto = GPU if it has room, else CPU")
    ap.add_argument("--min-chars", type=int, default=200, help="skip spine documents shorter than this")
    ap.add_argument("--chapters", metavar="RANGE", help="only read these chapters, e.g. 1-2 or 3-,7 (see --list-chapters)")
    ap.add_argument("--list-chapters", action="store_true", help="show what would be read, then stop")
    ap.add_argument("--sample", type=int, nargs="?", const=1500, metavar="CHARS",
                    help="render just the first CHARS characters (default 1500) to audition a voice")
    args = ap.parse_args()

    files = args.files or sorted(p for p in OUT.glob("*.epub") if not p.with_suffix(".m4b").exists())
    if not files:
        print(f"No EPUBs needing audio in {OUT}")
        return 0

    pipeline = None
    if not args.list_chapters:
        from kokoro import KPipeline  # slow import; skip it for --list-chapters
        # Voice prefix picks the accent: a=American, b=British, etc.
        pipeline = KPipeline(lang_code=args.voice[0], repo_id="hexgrad/Kokoro-82M", device=pick_device(args.device))

    failed = 0
    for path in files:
        print(f"==> {path.name}")
        try:
            convert(path.resolve(), args, pipeline)
        except Exception as e:
            failed += 1
            print(f"    FAILED: {e}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
