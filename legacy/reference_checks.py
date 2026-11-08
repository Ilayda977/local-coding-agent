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


def callable_statement_index(source):
    """Bounded source locators by lexical owner, not inferred runtime outcomes.

    Nested functions do not contribute returns/raises to their callers.
    Only supplied, actually read blocks are indexed; partial syntax is skipped.
    """
    result = []
    for block in source:
        if not block['file'].endswith('.py'):
            continue
        text = textwrap.dedent(block['quote'])
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue

        def visit(node, scope=()):
            if len(result) >= 24:
                return
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                scope = (*scope, node.name)
                for statement in node.body:
                    visit(statement, scope)
                return
            if isinstance(node, ast.Lambda):
                return
            if scope and isinstance(node, (ast.Return, ast.Raise)):
                result.append({
                    'evidence_id': block.get('id', block.get('block_id')),
                    'file': block['file'], 'owner': '.'.join(scope),
                    'line': block['start_line'] + node.lineno - 1,
                    'kind': 'return' if isinstance(node, ast.Return) else 'raise',
                    'statement': (ast.get_source_segment(text, node) or '')[:400],
                })
                return
            for child in ast.iter_child_nodes(node):
                visit(child, scope)

        visit(tree)
    return result


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


def check_draft(draft_text, source):
    """
    Checks if any qualified names (e.g. sys.stdout.write) in the drafted text
    are actually present in the AST of the read source blocks.
    Returns a list of error messages, or an empty list if clean.
    """
    index = reference_index(source)
    issues = []
    
    claimed = set(QUALIFIED_NAME.findall(draft_text))
    claimed = {name for name in claimed if PurePosixPath(name).suffix.casefold() not in FILE_SUFFIXES}
    
    if not claimed:
        return issues
        
    blocks = [block for block in index.values() if block['parsed']]
    observed = {name for block in blocks for name in block['references']}
    
    for name in sorted(claimed):
        if name in observed:
            continue
        if '.' in name and name.split('.')[-1] in observed:
            continue
        issues.append(
            f"'{name}' bağlı okunmuş kodda doğrudan referans olarak doğrulanamadı. "
            "Bu kontrol alias, olumsuz cümle veya eksik bloktan yokluk ispatı yapmaz; "
            "tek başına iddianın yanlış olduğunu göstermez. "
            "İlgili kullanım kanıtını okuyun veya açıklamayı desteklenen işlemlerle sınırlayın. "
            f"Görülen referanslar: {', '.join(sorted(observed)) or 'yok'}."
        )
    return issues
