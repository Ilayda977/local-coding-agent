"""Small source observations, not a Python interpreter or semantic verifier.

Only straight-line literal returns in actually read excerpts are extracted.
The model chooses observation IDs; the controller renders the exact expression.
No import, eval, execution, helper inference or repository-specific answer here.
"""
import ast
import io
import re
import textwrap
import tokenize
from pathlib import PurePosixPath


def symbol_inventory(blocks):
    """Names and declaration headers in read Python excerpts, never full files.

    Tokenization ignores comments/string contents. It retains complete headers
    before an excerpt cuts off in a docstring; no invented body is parsed.
    A used/imported name is not represented as a definition.
    """
    inventory = []
    for block in blocks:
        if not block['file'].endswith('.py'):
            continue
        tokens = []
        try:
            for token in tokenize.generate_tokens(io.StringIO(textwrap.dedent(block['quote'])).readline):
                tokens.append(token)
        except (tokenize.TokenError, IndentationError, SyntaxError):
            pass  # Only tokens observed before the incomplete tail are retained.
        names = sorted({token.string for token in tokens if token.type == tokenize.NAME})
        definitions = []
        for index, token in enumerate(tokens[:-1]):
            if token.type != tokenize.NAME or token.string not in {'def', 'class'}:
                continue
            name = tokens[index + 1]
            if name.type != tokenize.NAME:
                continue
            depth = 0
            for part in tokens[index + 2:]:
                if part.type == tokenize.NEWLINE:
                    break
                if part.type != tokenize.OP:
                    continue
                if part.string in '([{':
                    depth += 1
                elif part.string in ')]}':
                    depth -= 1
                elif part.string == ':' and depth == 0:
                    definitions.append({'name': name.string, 'kind': token.string,
                                        'line': block['start_line'] + token.start[0] - 1})
                    break
        inventory.append({'evidence_id': block['id'], 'file': block['file'],
                          'definitions': definitions, 'referenced_names': names,
                          'scope': 'read excerpt only; names may be imports, uses or definitions'})
    return inventory


def check_symbol_locations(answer, cited_blocks, inventory):
    """Check exact name presence for atomic file-scoped summary statements.

    This does not prove call graphs or interpret every natural-language claim.
    Multi-file statements naming definitions must be split for unambiguous
    provenance. The definition/reference inventory is separately given to LLM.
    """
    known = {definition['name'] for item in inventory for definition in item['definitions']}
    # Literal snippets (for example benchmark setup strings) can legitimately
    # mention an API too. Presence here is not proof of a declaration; only
    # the tokenized definition inventory establishes observed headers.
    by_file = {}
    python_files = {item['file'] for item in inventory}
    for block in cited_blocks:
        if block['file'] in python_files:
            by_file.setdefault(block['file'], []).append(block['quote'])
    cited_files = set(by_file)
    for sentence in re.split(r'(?<=[.!?])\s+|\n+', answer):
        mentioned = {name for name in known
                     if re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', sentence)}
        if not mentioned:
            continue
        explicit = {file for file in cited_files if re.search(
            r'(?<![\w/])(?:' + re.escape(file) + '|' + re.escape(PurePosixPath(file).name)
            + r')(?![\w/])', sentence)}
        if len(explicit) > 1:
            raise ValueError('Split file/symbol statements into one file per sentence; '
                             'do not merge definitions from different source files.')
        scoped = explicit or (cited_files if len(cited_files) == 1 else set())
        if len(scoped) == 1:
            file = next(iter(scoped))
            missing = {name for name in mentioned if not any(
                re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', text)
                for text in by_file[file])}
            if missing:
                raise ValueError('Names absent as exact identifier mentions from cited ' + file
                                 + ': ' + ', '.join(sorted(missing))
                                 + '. Use observed_symbols: distinguish a definition, import and use. '
                                 'Describe only what this excerpt supports.')


def check_source_tokens(answer, blocks):
    """Quoted/code-shaped text must be present in linked source, not inferred.

    This is a provenance check, not an emulator for replacements or escaping.
    Unquoted natural-language semantics remain the model's responsibility.
    Prefer selecting an exact source excerpt for any input/output example.
    """
    quoted = re.findall(r'`([^`\n]+)`|"([^"\n]+)"|“([^”\n]+)”|‘([^’\n]+)’|(?<!\w)\x27([^\x27\n]+)\x27(?!\w)', answer)
    spans = [next(part for part in match if part) for match in quoted]
    # Also check unquoted angle-delimited code tokens. This catches altered
    # markup/type examples without knowing the target language's transform.
    spans.extend(re.findall(r'<[^\s<]+', answer))
    texts = [block['quote'] for block in blocks]
    locations = {str(path) for block in blocks
                 for path in [PurePosixPath(block['file']), *PurePosixPath(block['file']).parents]
                 if str(path) != '.'}
    locations.update(PurePosixPath(block['file']).name for block in blocks)
    for span in spans:
        token = span.rstrip('.,:!?`\"\x27') if span.startswith('<') else span
        present = any((re.search(r'(?<!\w)' + re.escape(token) + r'(?!\w)', text)
                       if token.isidentifier() else token in text) for text in texts)
        if token not in locations and not present:
            raise ValueError('Quoted/code token is absent from its cited source: ' + repr(token)
                             + '. Do not invent input/output examples. Describe the purpose '
                             'without examples, or select source_quotes for a verbatim excerpt.')


def literal_returns(blocks):
    facts, seen = [], set()
    for block in blocks:
        if not block['file'].endswith('.py'):
            continue
        text = textwrap.dedent(block['quote'])
        try:
            tree = ast.parse(text)
        except SyntaxError:
            # Partial functions are not silently repaired into evidence.
            continue
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef) or node.decorator_list:
                continue
            body = list(node.body)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                body.pop(0)  # A docstring is never a returned/printed value.
            if len(body) != 1 or not isinstance(body[0], ast.Return):
                continue
            statement = body[0]
            if not isinstance(statement.value, ast.Constant):
                continue
            value = statement.value.value
            if type(value) not in (str, int, float, bool, type(None)):
                continue
            expression = ast.get_source_segment(text, statement.value)
            if expression is None or len(expression) > 240 or '\n' in expression:
                continue
            line = block['start_line'] + statement.lineno - 1
            key = (block['file'], line, node.name)
            if key in seen:
                continue
            seen.add(key)
            facts.append({'id': f'R{len(facts) + 1}', 'symbol': node.name,
                          'evidence_id': block['id'], 'file': block['file'],
                          'line': line, 'expression': expression,
                          'statement': ast.get_source_segment(text, statement)})
    return facts


def check_literal_prose(answer, evidence_ids, facts):
    """Reject visibly altered quoted values for an explicitly named function.

    This deliberately narrow lexical check is NOT natural-language proof. An
    unquoted or indirect claim can still be wrong and remains review_required.
    Ambiguous combined claims should be split or replaced by source fact IDs.
    """
    spans = re.findall(r'`([^`\n]*)`|\x27([^\x27\n]*)\x27|"([^"\n]*)"|“([^”\n]*)”|‘([^’\n]*)’', answer)
    quoted = [next((part for part in match if part), '') for match in spans]
    mentioned = [fact for fact in facts if fact['evidence_id'] in evidence_ids
                 and re.search(r'(?<!\w)' + re.escape(fact['symbol']) + r'(?!\w)', answer)]
    if not mentioned:
        return
    allowed = set()
    for fact in mentioned:
        # Parse only ast.Constant expressions, never evaluate executable code.
        value = ast.literal_eval(fact['expression'])
        allowed.update((str(value), fact['expression'], fact['statement'],
                        fact['symbol'], fact['symbol'] + '()', fact['file']))
    for text in quoted:
        if text not in allowed:
            raise ValueError('Quoted value does not match the cited literal return. '
                             'Do not rewrite values; select literal_return_ids from: '
                             + ', '.join(fact['id'] for fact in mentioned))


def render_literal(fact, citation):
    return {'answer': f"{fact['symbol']}: {fact['statement']}",
            'kind': 'source_literal_return', 'evidence': [citation]}
