from functools import lru_cache

from fuzzywuzzy import fuzz

FUZZY_START_WITH_THRESHOLD = 85
FUZZY_COMPARE_THRESHOLD = 90



def compare_preprocess(s: str) -> str:
    return s.replace(" ", "").replace("''", '"').strip()


# PURE-FUNCTION MEMOIZATION — measured hotspot, zero semantic change. One slow
# extraction query (zlmn-shr-3 INVOICE_ID: 12 anchors x 977 tokens x repeated
# fallback attempts) profiled at 216,891 WRatio calls = 20.5s of a 55s query,
# and the SAME (token, anchor) pairs are re-scored across attempts. The scorers
# below are pure (str, str, int) -> bool, so caching cannot change any result —
# it only remembers it. maxsize bounds worker memory (a few MB at worst).
@lru_cache(maxsize=262144)
def fuzzy_compare(s1: str, s2: str, threshold=FUZZY_COMPARE_THRESHOLD) -> bool:
    return fuzz.ratio(s1, s2) >= threshold


@lru_cache(maxsize=262144)
def fuzzy_startswith(s1: str, s2: str, threshold=FUZZY_START_WITH_THRESHOLD) -> bool:
    if len(s2) > len(s1):
        return False
    if len(s2) == 1:
        return s1.startswith(s2)
    if len(s2) == 2:
        cuted_s1 = s1[:len(s2)]
        cuted_ratio = fuzz.WRatio(cuted_s1, s2)
        return cuted_ratio >= threshold
    
        
    extended_s2 = s2 + s1[len(s2):]
    extended_ratio = fuzz.WRatio(extended_s2, s1)
    return extended_ratio >= threshold
    




def compare_strings(s1: str, s2: str, fuzzy=True) -> bool:
    s1, s2 = compare_preprocess(s1), compare_preprocess(s2)
    if fuzzy:
        return fuzzy_compare(s1, s2)
    return s1 == s2


def string_startswith(s1: str, s2: str, fuzzy=True) -> bool:
    s1, s2 = compare_preprocess(s1), compare_preprocess(s2)
    if fuzzy:
        return fuzzy_startswith(s1, s2)
    return s1.startswith(s2)



if __name__ == "__main__":
    # Test the functions with some examples
    print(compare_strings("Hello World", "Hello", fuzzy=True))  # True
    print(string_startswith("Hello World", "Hello", fuzzy=True))  # True
    print(fuzzy_compare("Hello World", "Hello", threshold=80))  # False
    print(fuzzy_startswith("Hello World", "Hell", threshold=80))  # True

    print(fuzzy_startswith("חשבונית מס מספר", "44"))
    print(fuzzy_startswith("תעודת משלוח", "תעדת"))