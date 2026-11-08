"""Small navigation policy: explicit code names before incidental text matches.

This selects a lookup, never an answer or a source file. Only actual search
results may become evidence. Natural-language interpretation stays with the LLM.
"""
import re
from protocol import SearchRequest


def initial_searches(question, route, requests):
    if route.intent in {'list_files', 'locate_file', 'documentation'}:
        return requests
    # Preserve Unicode and qualification. Do not transliterate/correct an exact
    # identifier. Typo alternatives, when necessary, remain labelled candidates.
    names = re.findall(r'(?<![\w./])(?:[^\W\d]\w*\.)*[^\W\d]\w*_\w+(?![\w./])', question)
    if not names:
        return requests
    name = names[0]
    if any(item.tool == 'find_symbol' and item.query == name for item in requests):
        return requests
    # One explicit identifier lookup is bounded and cheap. Existing intent
    # searches stay available; if it has no definition there is no forced read.
    return [SearchRequest(tool='find_symbol', query=name), *requests[:1]]
