from __future__ import annotations

import argparse
from pathlib import Path

from engine.ingest import import_local_audio, import_youtube
from engine.jobs import analyze_pack
from engine.lyrics import WHISPER_MODELS, extract_lyrics, normalize_lang, normalize_whisper_model
from engine.melody import extract_melody, refine_melody_with_lyrics
from engine.lyrics_align import align_lyrics_from_text
from engine.pack import get_pack, list_packs
from engine.stems import split_stems


def main() -> None:
    parser = argparse.ArgumentParser(prog="karaok")
    sub = parser.add_subparsers(dest="cmd", required=True)

    ingest = sub.add_parser("ingest", help="Import audio/URL → stems → melody → lyrics")
    ingest.add_argument("source", help="Audio file path or YouTube URL")
    ingest.add_argument("--title", default=None)
    ingest.add_argument("--singer", default="")
    ingest.add_argument(
        "--lang",
        default="cantonese",
        choices=["cantonese", "chinese", "english"],
        help="Lyrics language preset",
    )
    ingest.add_argument("--stems-only", action="store_true")
    ingest.add_argument(
        "--model",
        default=None,
        choices=list(WHISPER_MODELS),
        help="Whisper model (default: medium)",
    )

    analyze = sub.add_parser("analyze", help="Run melody+lyrics on an existing pack id")
    analyze.add_argument("pack_id")
    analyze.add_argument(
        "--lang",
        default=None,
        choices=["cantonese", "chinese", "english"],
        help="Override lyrics language preset",
    )
    analyze.add_argument(
        "--model",
        default=None,
        choices=list(WHISPER_MODELS),
        help="Whisper model (default: medium)",
    )

    align = sub.add_parser("lyrics-align", help="Align a lyric .txt onto vocals → lyrics.json")
    align.add_argument("pack_id")
    align.add_argument("txt", help="Path to lyric txt (one phrase per line)")
    align.add_argument(
        "--lang",
        default=None,
        choices=["cantonese", "chinese", "english"],
    )
    align.add_argument("--model", default=None, choices=list(WHISPER_MODELS))
    align.add_argument(
        "--remap",
        action="store_true",
        help="Only remap onto existing lyrics.json timing (no GPU align)",
    )

    sub.add_parser("list", help="List song packs")

    args = parser.parse_args()
    if args.cmd == "list":
        packs = list_packs()
        if not packs:
            print("No song packs yet.")
            return
        for pack in packs:
            meta = pack.public_dict()
            flags = []
            if meta["has_vocals"]:
                flags.append("stems")
            if meta["has_melody"]:
                flags.append("melody")
            if meta["has_lyrics"]:
                flags.append("lyrics")
            print(
                f"{meta['id']}\t{meta['status']}\t{meta.get('lyrics_lang', '-')}\t"
                f"{meta['title']}\t{meta.get('singer') or '-'}\t{','.join(flags) or '-'}"
            )
        return

    if args.cmd == "lyrics-align":
        pack = get_pack(args.pack_id)
        text = Path(args.txt).read_text(encoding="utf-8-sig")
        payload = align_lyrics_from_text(
            pack,
            text,
            language=args.lang,
            model_name=normalize_whisper_model(args.model),
            prefer_remap=bool(args.remap),
        )
        print(
            f"aligned: {pack.lyrics} lines={len(payload.get('lines') or [])} "
            f"method={payload.get('method')}"
        )
        return

    if args.cmd == "analyze":
        pack = get_pack(args.pack_id)
        analyze_pack(
            pack,
            lyrics_lang=args.lang,
            whisper_model=normalize_whisper_model(args.model),
        )
        print(f"ready: {pack.root}")
        print(f"melody={pack.melody.exists()} lyrics={pack.lyrics.exists()}")
        return

    lang = normalize_lang(args.lang)
    model = normalize_whisper_model(args.model)
    source = args.source
    if source.startswith("http://") or source.startswith("https://"):
        pack = import_youtube(source, lyrics_lang=lang, singer=args.singer)
    else:
        pack = import_local_audio(
            Path(source), title=args.title, lyrics_lang=lang, singer=args.singer
        )
    print(f"imported {pack.root} lang={lang}")
    pack.update_status("splitting")
    split_stems(pack)
    pack.update_status("stems_ready")
    print(f"stems ready: {pack.vocals} {pack.instrumental}")
    if args.stems_only:
        return
    pack.update_status("analyzing")
    mel = extract_melody(pack)
    lyr = extract_lyrics(pack, language=lang, model_name=model)
    refined = refine_melody_with_lyrics(pack)
    if refined is not None:
        mel = refined
    pack.update_status("ready")
    print(
        f"melody notes={mel['note_count']} lyrics lines={len(lyr.get('lines') or [])} "
        f"lang={lyr.get('lang_preset')}"
    )


if __name__ == "__main__":
    main()
