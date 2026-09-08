"""Conservative AST grounding of qualified names in proposed prose.

This verifies a direct syntactic reference, not runtime reachability, alias
resolution, or semantic correctness. Comments and string literals are not uses.
No repository code is executed. Absence in a partial block proves nothing about
the rest of a file; the agent must read the relevant source or narrow its claim.
"""
import ast
import re
import textwrap
from pathlib import PurePosixPath

from navigation import FILE_SUFFIXES


QUALIFIED_NAME = re.compile(r'(?<![\w.])[^\W\d]\w*(?:\.[^\W\d]\w*)+(?![\w.])')


def _attribute_name(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.insert(0, node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        return '.'.join([node.id, *parts])
    return None


def reference_index(source):
    """Index only actually supplied Python blocks, never another file's matches."""
    result = {}
    for block in source:
        if not block['file'].endswith('.py'):
            continue
        try:
            tree = ast.parse(textwrap.dedent(block['quote']))
        except SyntaxError:
            result[block['id']] = {'references': [], 'parsed': False}
            continue
        names = set()
        calls = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                name = _attribute_name(node)
                if name:
                    names.add(name)
            if isinstance(node, ast.Call):
                name = _attribute_name(node.func)
                if name:
                    calls.add(name)
        result[block['id']] = {'references': sorted(names), 'calls': sorted(calls), 'parsed': True}
    return result


def reference_issues(answers, source):
    """Unsupported names are not accepted even if another LLM approves them.

Deliberately no guess of Turkish/English negation: an unsupported negative name
also requests a narrower formulation, rather than treating absence as proof.
"""
    index = reference_index(source)
    issues = []
    for answer in answers:
        claimed = set(QUALIFIED_NAME.findall(answer.answer + '\n' + answer.mechanism))
        claimed = {name for name in claimed if PurePosixPath(name).suffix.casefold() not in FILE_SUFFIXES}
        if not claimed:
            continue
        ids = [a.evidence_id for a in answer.anchors]
        blocks = [index[key] for key in ids if key in index]
        if len(blocks) != len(ids) or not all(b['parsed'] for b in blocks):
            issues.append(f'{answer.requirement_id}: Kod referansları bu parçaların AST bağlamında doğrulanamadı; tam ilgili bölümü oku veya iddiayı daralt.')
            continue
        observed = {name for block in blocks for name in block['references']}
        for name in sorted(claimed - observed):
            issues.append(
                f'{answer.requirement_id}: {name} bağlı okunmuş kodda doğrudan referans olarak yok. '
                'Bu, tüm projede bulunmadığını kanıtlamaz. İlgili kullanım kanıtını oku veya '
                'cevabı yalnız gerçek işlemler üzerinden ifade et; olumsuz cevapta da bu desteklenmeyen adı tekrarlama. '
                f'Görülen referanslar: {", ".join(sorted(observed)) or "yok"}.')
    return issues
