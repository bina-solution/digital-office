def calc(text: str) -> float:
    # print(text)
    for i, c in enumerate(text):
        if c in "+-":
            a = calc(text[:i])
            b = calc(text[i + 1:])
            if c == "+":
                print(text, ':', a + b)
                return a + b
            else:
                print(text, ':', a - b)
                return a - b
    for i, c in enumerate(text):
        if c in "*/":
            a = calc(text[:i])
            b = calc(text[i + 1:])
            if c == "*":
                print(text, ':', a * b)
                return a * b
            else:
                print(text, ':', a / b)
                return a / b
    return float(text)


def calc1(text: str) -> float:
    parts = []

    num = ''
    for c in text:
        if c in '+-*/':
            parts.append(num)
            parts.append(c)
            num = ''
        else:
            num += c
    parts.append(num)

    # print(parts)
    while ('*' in parts) or ('/' in parts):
        for i, c in enumerate(parts):
            if c not in ('*', '/'):
                continue
            a = float(parts[i - 1])
            b = float(parts[i + 1])
            if c == '*':
                parts[i - 1] = a * b
            else:
                parts[i - 1] = a / b
            parts.pop(i)
            parts.pop(i)
            break

    while ('+' in parts) or ('-' in parts):
        for i, c in enumerate(parts):
            if c not in ('+', '-'):
                continue
            a = float(parts[i - 1])
            b = float(parts[i + 1])
            if c == '+':
                parts[i - 1] = a + b
            else:
                parts[i - 1] = a - b
            parts.pop(i)
            parts.pop(i)
            break

    # print(parts)
    return parts[0]


import re


def calc2(text: str) -> float:
    priors = ['*/', '+-']
    for prior in priors:
        while True:
            m = re.search(r'(\d+)\s*([{}])\s*(\d+)'.format(prior), text)
            if not m:
                break
            a, op, b = m.groups()
            if op == '+':
                text = text.replace(m.group(), str(int(a) + int(b)))
            elif op == '-':
                text = text.replace(m.group(), str(int(a) - int(b)))
            elif op == '*':
                text = text.replace(m.group(), str(int(a) * int(b)))
            elif op == '/':
                text = text.replace(m.group(), str(int(a) / int(b)))

    while '*' in text or '/' in text:
        text = re.sub(r'(\d+)\s*\+*([*/])\s*(\d+)',
                      lambda m: str(int((int(m[1]) * int(m[3]), int(m[1]) / int(m[3]))[m[2] == '/'])), text)
    while '+' in text or '-' in text:
        text = re.sub(r'(\d+)\s*\+*([+-])\s*(\d+)',
                      lambda m: str(int((int(m[1]) + int(m[3]), int(m[1]) - int(m[3]))[m[2] == '-'])), text)

    return float(text)


def test(s):
    print(calc2(s), eval(s), s)


test('1+2*2+2/2-1*2/2+1')
# I want 10 test cases complicated in one line
test_cases = ['1+2*2', '1+2*2+2', '1+2*2+2/2', '1+2*2+2/2-1', '1+2*2+2/2-1*2', '1+2*2+2/2-1*2/2', '1+2*2+2/2-1*2/2+1',
              '1+2*2+2/2-1*2/2+1*2', '1+2*2+2/2-1*2/2+1*2/2', '1+2*2+2/2-1*2/2+1*2/2-1']
for t in test_cases:
    test(t)