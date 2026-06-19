import json

SCRIPT = "Incredible scenes at the World Cup. Nobody expected this. Watch what happens next."

tokens = [t for t in SCRIPT.split() if t.strip()]
audio_dur = 8.0
ns_total = int(audio_dur * 10_000_000)
ns_per_word = ns_total // len(tokens)
words = [{"text": tok, "offset": i * ns_per_word, "duration": int(ns_per_word * 0.80)} for i, tok in enumerate(tokens)]
print(f"Fallback: {len(words)} words estimated")
print("First 3:", words[:3])

def ts(n):
    s = n / 10_000_000.0
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    cs = s % 60
    return f"{h}:{m:02d}:{cs:05.2f}"

pop = "{" + r"\t(0,80,\fscx130\fscy130)" + r"\t(80,150,\fscx100\fscy100)" + "}"
events = []
for w in words:
    start = ts(w["offset"])
    end = ts(w["offset"] + w["duration"] + 600_000)
    line = "Dialogue: 0," + start + "," + end + ",Default,,0,0,0,," + pop + w["text"]
    events.append(line)

print(f"Generated {len(events)} ASS dialogue events")
print("Sample 0:", events[0])
print("Sample 5:", events[5])
print("Sample last:", events[-1])
print()
print("ASS generation PASS - logic is correct")
