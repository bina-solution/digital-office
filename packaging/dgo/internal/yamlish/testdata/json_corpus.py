"""Random JSON texts for LoadJSON's differential test, and what json.loads answers for each.

usage: json_corpus.py SEED COUNT
Prints a JSON list of {"doc": text, "ok": the value as sort-keyed compact JSON} or {"doc": text,
"err": str() of the exception, a RecursionError's with its name}: COUNT strings of JSON-ish tokens,
documents json.dumps writes in each of its spellings and each one mutated once, and hand-picked
corners. Built by the second reader of core-compiler-write (json_test.go runs it).
"""
import json
import random
import sys

random.seed(int(sys.argv[1]))
count = int(sys.argv[2])
TOK = ['{', '}', '[', ']', ',', ':', '"', '\\', 'u', '0', '1', '9', '-', '+', '.', 'e', 'E', ' ', '\n', '\t', '\r',
       'true', 'false', 'null', 'NaN', 'Infinity', '-Infinity', 'nul', 'tru', 'a', 'é', '\u0000', '\u001f', '\u007f',
       '"a"', '"\\u00e9"', '"\\ud83d\\ude00"', '"\\n"', '\\/', '\\b', '\\uD83D', '\\uDE00', '\ufeff', '\u2028',
       '0.5', '1e5', '1e', '1e+', '-0', '00', '01', '.5', '5.', '1.e3', '123456789012345678901234567890']


def rand_value(depth=0):
    r = random.random()
    if depth > 3 or r < 0.4:
        return random.choice([0, 1, -1, 1.5, -0.0, 1e300, 2**70, "", "a", "é\u2028", chr(0x1F600), None, True, False,
                              "\u0000\u001f", "\\", '"'])
    if r < 0.7:
        return [rand_value(depth + 1) for _ in range(random.randint(0, 3))]
    return {random.choice(["a", "b", "", "é", "a"]): rand_value(depth + 1) for _ in range(random.randint(0, 3))}


docs = ["".join(random.choice(TOK) for _ in range(random.randint(0, 14))) for _ in range(count)]
for _ in range(count // 7):
    text = json.dumps(rand_value(), ensure_ascii=random.random() < 0.5,
                      indent=random.choice([None, 1]), separators=random.choice([None, (",", ":")]))
    docs.append(text)
    if text:  # and once more, a character dropped, inserted or replaced
        i, tok = random.randrange(len(text)), random.choice(TOK)
        docs.append(random.choice([text[:i] + text[i + 1:], text[:i] + tok + text[i:], text[:i] + tok + text[i + 1:]]))
docs += ['{"a":1,"a":2,"b":3,"a":4}', '[1e400, -1e400, 1e-400, -0.0, 0e0]', '"\\ud800"', '"\\udc00\\ud800"',
         '"\\ud800\\u0041"', '"\\ud800\\udc0"', '"\\ud800\\', '[' * 999 + ']' * 999, '[' * 1001 + ']' * 1001,
         '{"a":' * 1001 + '1' + '}' * 1001, '1' * 4300, '1' * 4301, '-' + '1' * 4301, '1.' + '1' * 5000,
         '"\u007f"', '"\ufeff"', ' \ufeff{}', '\ufeff{}', '{}\n\n', '{} x', '[,]', '[1,]', '{"a":1,}', '{,}',
         '{"a" 1}', '{a:1}', "{'a':1}", '"\\x41"', '"\\U00000041"', '-', '-a', '--1', '[-]', '1.5e', '1.5e+',
         '2.', '[2.]', '0x10', '[NaN, Infinity, -Infinity]', 'nan', 'infinity', '-infinity', '[-NaN]', 'true1',
         'nulls', '"abc', '"a\nb"', '"a\tb"', '[1 2]', '{"a":1 "b":2}', '""', '"', '\u00a0[]', '[]\u00a0',
         '\u2028[]', '[1]\u0000', '\u000b[]', '\u000c[]']
out = []
for doc in docs:
    try:
        out.append({"doc": doc, "ok": json.dumps(json.loads(doc), sort_keys=True, ensure_ascii=False, separators=(",", ":"))})
    except RecursionError as e:
        out.append({"doc": doc, "err": "RecursionError: " + str(e)})
    except ValueError as e:
        out.append({"doc": doc, "err": str(e)})
sys.stdout.write(json.dumps(out))
