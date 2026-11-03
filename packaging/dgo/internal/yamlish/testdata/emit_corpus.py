"""Random documents for the emitter's differential test, and what yaml.safe_dump writes for each.

usage: emit_corpus.py SEED COUNT
Prints a JSON list of {"doc": <JSON text>, "sk": sort_keys, "w": width (0: the default), "yaml": the
dump}: COUNT random scalars over every class the emitter decides by — indicators, quotes, spaces,
breaks, controls, the resolver's words — each as a value, as a key and inside the remote block's
shape; long ones, folded in each style; keys about the simple key's 128-character edge; numbers from
the edges of each type and floats from random bits; strings about the widths nested under long keys,
folded at widths 40 and 5 as well; short strings over the resolvers' characters. Built by the second
reader of core-compiler-write (encode_test.go runs it).
"""
import json
import math
import random
import struct
import sys

import yaml

random.seed(int(sys.argv[1]))
count = int(sys.argv[2])
ALPH = list(" \t\n\r:#-?,[]{}&*!|>'\"%@`~.\\_+=<0123456789abeEnNoOyYtTfFxXlu") + [
    "\u0085", "\u2028", "\u2029", "\ufeff", "\u00a0", "é", "ש", chr(0x1F600), "\u0000", "\u0007",
    "\u001b", "\u007f", "\u001c", "\u000b", "\u000c", "\ufffe", chr(0x10FFFF), "\ud7ff", "\ue000",
    "\u3000", "İ",
]
WORDS = ["true", "yes", "no", "on", "off", "null", "~", "Null", "NULL", "0", "07", "0x1F", "0b101", "1_000",
         "1:20", "1:20.5", "1.5", "1e5", "1.0e+5", ".5", ".inf", "-.inf", ".nan", ".NaN", "+1", "-1",
         "2026-10-09", "2026-1-9 1:02:03", "2026-10-09T10:00:00Z", "<<", "=", "!", "&", "*", "---", "...",
         "- x", "-x", "? x", "?x", ": x", ":x", "a: b", "a:b", "a #b", "a#b", "#a", "'a", '"a', "a'", "%a",
         "@a", "`a", "|", ">", "a,b", "[a]", "{a}", "Y", "y", "N", "n", "TRUE", "False", "0o7", "0_", "+0x",
         "0x", "0b", "-0", "+.5", "1.", "1_2.3_4", "190:20:30.15", "0.1e-5", "1e+05"]


def rand_str(n):
    return "".join(random.choice(WORDS) if random.random() < 0.15 else random.choice(ALPH) for _ in range(n))


def long_str(target, alphabet):
    words = []
    while len("".join(words)) < target:
        words.append("".join(random.choice(alphabet) for _ in range(random.randint(1, 12))))
        words.append(" " * random.choice([1, 1, 1, 2, 3]))
    return "".join(words)[:target]


values = list(WORDS) + [rand_str(random.randint(0, 10)) for _ in range(count)]
alphabets = [list("abcdefghij") + ["é", "ש"],                                 # plain
             list("abcdefg") + ["\u0007", "é", chr(0x1F600), "\\", '"', "\ufeff"],  # double-quoted
             list("abcdef") + ["'", ":", "#"],                                   # single-quoted
             list("abcdef") + ["\n", "\n\n", " \n", "\n ", " ", "\u0085"]]       # line breaks
for target in [70, 79, 80, 81, 99, 990, 999, 1000, 1001, 1014, 2100]:
    for alphabet in alphabets:
        s = long_str(target, alphabet)
        values += [s, " " + s, s + " "]
numbers = [0, 1, -1, 2**63 - 1, 2**63, -2**63, -2**63 - 1, 10**30, -10**30, 1.0, -0.0, 0.0, 0.1, 1e16, 1e15,
           123456789012345678.0, 1e-5, 1e-4, 0.0001, 1.5e300, 5e-324, 2.2250738585072014e-308, 1e22, 1e21,
           float("inf"), float("-inf"), 1 / 3, 100.0, 1e100, -1.25e-7, 9007199254740993.0, True, False, None]
cases = []


def add(doc, args=((False, 1000), (True, 0), (False, 0))):
    text = json.dumps(doc, allow_nan=True)
    for sort_keys, width in args:
        kw = dict(default_flow_style=False, allow_unicode=True, sort_keys=sort_keys)
        if width:
            kw["width"] = width
        cases.append({"doc": text, "sk": sort_keys, "w": width, "yaml": yaml.safe_dump(doc, **kw)})


for v in values:
    add({"k": v})
    add({"remote": [{"office": "x", "desc": v, "apps": [{"app": "a", "name": v}]}]})
    if v:
        add({v: 1})
        add({"a": {v: [v]}})
for n in numbers:
    add({"k": n, "l": [n]})
for k in ["a" * n for n in (120, 121, 122, 123, 124, 125, 127, 128)] + ["é" * 122, "é" * 123, "", "\n", "a\nb", "a\u0085b"]:
    add({k: "v"})
    add({"m": {k: {"x": [1]}}})
add({"a": [], "b": {}, "c": [[]], "d": [{}], "e": [[1, [2, []]], {"f": []}], "g": [{"h": {}, "i": []}]})
add([{"a": 1}, [1, 2], [], {}, "x", None])
# floats from random bit patterns, rounded decimals, powers of ten and big integers, fifty to a document
floats = []
for _ in range(count // 4):
    f = struct.unpack("<d", struct.pack("<Q", random.getrandbits(64)))[0]
    if math.isfinite(f):
        floats.append(f)
    floats += [round(random.uniform(-1e6, 1e6), random.randint(0, 8)),
               random.randint(1, 9) * 10.0 ** random.randint(-320, 307), float(random.randint(-2**60, 2**60))]
for i in range(0, len(floats), 50):
    add({"v": floats[i:i + 50]})
# strings about the widths — words, runs of spaces, escapes, quotes, breaks, wide characters — nested
# up to four deep under keys up to 125 characters long, folded at widths 40 and 5 too
PIECES = ["a", "bb", "ccc", "dddd", " ", "  ", "   ", "\n", "\n\n", " \n", "\n ", "'", '"', "\\", "\u0007",
          "\u0000", "\t", "\r", "\u0085", "\u2028", "\u2029", "é", "ש", chr(0x1F600), "\ufeff", "\u00a0",
          ":", "#", ": ", " #", "-", "?", "\u3000", "x" * 30, "y" * 75, "z" * 79, "w" * 81]
for _ in range(count // 10):
    target = random.choice([random.randint(60, 200), random.randint(950, 1100)])
    s = ""
    while len(s) < target:
        s += random.choice(PIECES)
    doc = s[:target] if random.random() < 0.5 else s
    for _ in range(random.randint(0, 4)):
        doc = random.choice([[doc], {"k": doc}, {"key-" + "q" * random.randint(0, 120): doc}])
    add({"root": doc}, ((False, 1000), (True, 0), (False, 0), (False, 40), (False, 5)))
# short strings over the characters the implicit resolvers read, as values and as keys
RESOLVED = list("0123456789_:.+-eExXbBoOinfINFaNTtYyluslLrR ~<=")
for _ in range(count):
    s = "".join(random.choice(RESOLVED) for _ in range(random.randint(1, 9)))
    add({"k": s}, ((False, 1000),))
    add({s: 1}, ((False, 1000),))
add({"nested": [[[["deep"]]]], "seq": [{"a": [{"b": [1]}]}]})
sys.stdout.write(json.dumps(cases))
