"""Find @handles in comment text.

"Ping @Alice and @bob.smith!" -> ["Alice", "bob.smith"]
The handles are returned as written; UserService.find_by_handle normalizes them.
"""
import re

# Not preceded by a word character or '@' (so "a@b.com" is not a mention).
MENTION_PATTERN = re.compile(r"(?<![\w@])@([A-Za-z0-9_.]{2,30})")


def extract_mentions(text):
    seen, result = set(), []
    for raw in MENTION_PATTERN.findall(text or ""):
        handle = raw.rstrip(".")  # "@bob." at the end of a sentence
        if handle.lower() not in seen:
            seen.add(handle.lower())
            result.append(handle)
    return result
