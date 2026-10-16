"""Build local bilingual MP3s using Edge TTS (network needed only at build time).

Install: python -m pip install edge-tts mutagen
Run: python tools/generate_edge_voice.py
All files are staged and validated before replacing the current audio pack.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from datetime import datetime, timezone

import edge_tts
from mutagen.mp3 import MP3

ROOT = Path(__file__).resolve().parents[1]
CAPS = {"ready": 2.2, "go": 2.4, "forfeit": 3.0}


async def generate(args):
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    voices = {"zh": args.chinese_voice, "en": args.english_voice}
    report = {"version": 2, "generator": "edge-tts", "generator_version": edge_tts.__version__,
              "generated_at": datetime.now(timezone.utc).isoformat(), "voices": voices,
              "network_at_playback": False, "critical_duration_caps_seconds": CAPS, "files": []}
    build_root = ROOT / ".voice-build"
    build_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=build_root) as temp:
        stage = Path(temp)
        semaphore = asyncio.Semaphore(3)

        async def build(prompt, lang):
            async with semaphore:
                relative = Path(lang) / f"{prompt['id']}.mp3"
                if prompt[lang]["file"] != f"/audio/{relative.as_posix()}":
                    raise ValueError(f"Unexpected audio path: {prompt['id']}")
                target = stage / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                cap = CAPS.get(prompt["id"], 5.0 if prompt["id"].startswith("service_") else 90)
                rate = 0
                for attempt in range(5):
                    try:
                        await edge_tts.Communicate(prompt[lang]["text"], voices[lang], rate=f"+{rate}%").save(str(target))
                        info = MP3(target).info
                        if info.length > cap:
                            rate += 15
                            if attempt == 4:
                                raise ValueError(f"Audio too long: {lang}/{prompt['id']}: {info.length:.2f}s > {cap}s")
                            continue
                        break
                    except (ValueError, KeyError):
                        raise
                    except Exception:
                        if attempt == 4:
                            raise
                        await asyncio.sleep(2 * (attempt + 1))
                if info.length <= 0 or target.stat().st_size < 1000:
                    raise ValueError(f"Invalid MP3: {target}")
                row = {"id": prompt["id"], "language": lang, "file": prompt[lang]["file"],
                       "duration_seconds": round(info.length, 3), "bytes": target.stat().st_size,
                       "channels": info.channels, "sample_rate": info.sample_rate, "rate": f"+{rate}%",
                       "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
                report["files"].append(row)
                print(f"{lang}/{prompt['id']}: {info.length:.2f}s", flush=True)

        await asyncio.gather(*(build(p, lang) for p in manifest["prompts"] for lang in ("zh", "en")))
        report["files"].sort(key=lambda row: (row["language"], row["id"]))
        report["count"] = len(report["files"])
        report["total_bytes"] = sum(row["bytes"] for row in report["files"])
        for lang in ("zh", "en"):
            (args.output / lang).mkdir(parents=True, exist_ok=True)
            for source in (stage / lang).glob("*.mp3"):
                shutil.copy2(source, args.output / lang / source.name)
        (args.output / "build-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Published {report['count']} MP3 files ({report['total_bytes']} bytes)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "hmi/audio/prompts.json")
    parser.add_argument("--output", type=Path, default=ROOT / "hmi/audio")
    parser.add_argument("--chinese-voice", default="zh-CN-XiaoxiaoNeural")
    parser.add_argument("--english-voice", default="en-US-JennyNeural")
    asyncio.run(generate(parser.parse_args()))
