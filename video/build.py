"""Assemble the SAKSI video: one encoded file per scene, concat, narration, burnt-in captions."""
import json
import re
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

V = Path(__file__).parent
SC = V / "scenes"
SC.mkdir(exist_ok=True)
NARR = json.loads((V / "narration.json").read_text())
LEAD, TAIL = 0.45, 0.55
ENC = ["-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-r", "30"]


def dur(p):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)]))


def sentences(t):
    return [s.strip() for s in re.split(r"(?<=[.?!])\s+", t) if s.strip()]


# Sub-slides that share one narration clip: (scene, [(slide, n_sentences)])
SPLITS = {"s3": [("s3a", 3), ("s3b", 4), ("s3c", None)], "s6": [("s6a", 4), ("s6b", None)]}
ORDER = ["s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9"]
REC = {"s4": "rec/s4", "s5": "rec/s5"}


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[-2000:])
        raise SystemExit(1)


def still(png, seconds, out):
    tmp = out.with_suffix(".tmp.mp4")
    vf = f"format=yuv420p,loop=-1:1,trim=duration={seconds:.3f},fade=t=in:st=0:d=0.25"
    run(["ffmpeg", "-y", "-v", "error", "-framerate", "30", "-i", str(png), "-vf", vf, *ENC, str(tmp)])
    tmp.rename(out)


def recording(src, start, seconds, out):
    tmp = out.with_suffix(".tmp.mp4")
    vf = f"fps=30,scale=1920:1080,tpad=stop_mode=clone:stop_duration=30,trim=duration={seconds:.3f},setpts=PTS-STARTPTS,fade=t=in:st=0:d=0.25"
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-i", str(src), "-vf", vf, "-an", *ENC, str(tmp)])
    tmp.rename(out)


def main(only):
    plan = []  # (scene, seconds)
    caps = []  # (start, end, text) on the global timeline
    clock = 0.0
    for s in ORDER:
        nd = dur(V / "narr" / f"{s}.wav")
        total = LEAD + nd + TAIL
        sents = sentences(NARR[s])
        chars = [len(x) for x in sents]
        speech_per_char = nd / sum(chars)
        # captions: split sentences into chunks of <= 12 words, timed by characters
        t = clock + LEAD
        for sent in sents:
            words = sent.split()
            chunks = [" ".join(words[i:i + 12]) for i in range(0, len(words), 12)]
            for ch in chunks:
                d = len(ch) * speech_per_char * (len(sent) / sum(len(c) for c in chunks))
                caps.append((t, t + d, ch))
                t += d
        if s in SPLITS:
            parts, used, t_in = SPLITS[s], 0, 0.0
            for k, (slide, nsent) in enumerate(parts):
                take = sents[used:used + nsent] if nsent else sents[used:]
                used += len(take)
                seg = sum(len(x) for x in take) * speech_per_char
                secs = (LEAD + seg) if k == 0 else (seg + TAIL if k == len(parts) - 1 else seg)
                if k == len(parts) - 1:
                    secs = total - t_in
                plan.append((slide, secs, None))
                t_in += secs
        elif s in REC:
            src = next((V / REC[s]).glob("*.webm"))
            start = 1.0 if s == "s4" else float((V / REC[s] / "lead.txt").read_text()) + 0.4
            plan.append((s, total, (src, start)))
        else:
            plan.append((s, total, None))
        clock += total

    files = []
    for name, secs, rec in plan:
        out = SC / f"{name}.mp4"
        files.append(out)
        if only and name not in only and out.exists():
            continue
        if rec:
            recording(rec[0], rec[1], secs, out)
        else:
            still(V / "slides" / "html" / f"{name}.png", secs, out)
        print("scene", name, round(secs, 2))

    # narration track
    rate = 22050
    track = []
    for s in ORDER:
        with wave.open(str(V / "narr" / f"{s}.wav")) as w:
            rate = w.getframerate()
            a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        track += [np.zeros(int(LEAD * rate), np.int16), a, np.zeros(int(TAIL * rate), np.int16)]
    audio = np.concatenate(track)
    with wave.open(str(V / "narration_full.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(audio.tobytes())

    # captions (ASS)
    def ts(x):
        h, m = int(x // 3600), int(x % 3600 // 60)
        return f"{h}:{m:02d}:{x % 60:05.2f}"
    ass = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: 1920", "PlayResY: 1080", "",
           "[V4+ Styles]",
           "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
           "Style: Cap,Schibsted Grotesk,44,&H00F5F9F7,&H00F5F9F7,&H004A3014,&H284A3014,0,0,0,0,100,100,0,0,3,14,0,2,160,160,52,1",
           "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for a, b, txt in caps:
        ass.append(f"Dialogue: 0,{ts(a)},{ts(b)},Cap,,0,0,0,,{txt}")
    (V / "captions.ass").write_text("\n".join(ass))

    (V / "list.txt").write_text("".join(f"file '{f}'\n" for f in files))
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(V / "list.txt"), "-c", "copy", str(V / "silent.mp4")])
    fontsdir = Path.home() / ".fonts"
    tmp = V / "saksi_video.tmp.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(V / "silent.mp4"), "-i", str(V / "narration_full.wav"),
         "-vf", f"subtitles={V/'captions.ass'}:fontsdir={fontsdir}", "-map", "0:v", "-map", "1:a",
         *ENC, "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(tmp)])
    tmp.rename(V / "saksi_video.mp4")
    print("video", round(dur(V / "saksi_video.mp4"), 2), "s")


if __name__ == "__main__":
    main(set(sys.argv[1:]))
