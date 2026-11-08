"""Dil bağımsız hedef doğrulaması ve küçük araştırma kararları; cevap içermez."""
from difflib import SequenceMatcher
from pathlib import PurePosixPath


FILE_SUFFIXES = {'.py', '.js', '.jsx', '.ts', '.tsx', '.java', '.go', '.rs',
                 '.c', '.h', '.cpp', '.md', '.json', '.yaml', '.yml', '.txt', '.toml', '.rst', '.ini', '.cfg'}


def validate_target(tool, query):
    query = query.strip()
    if not query:
        raise ValueError('Arama hedefi boş olamaz.')
    if tool in {'find_symbol', 'find_calls', 'find_references', 'find_tests'}:
        if PurePosixPath(query.replace('\\', '/')).suffix.casefold() in FILE_SUFFIXES:
            raise ValueError('Bu hedef dosya adıdır. Dosya için find_file, tanım için gerçek kod adı seç.')
        for suffix in [" fonksiyonu", " metodu", " sınıfı", " değişkeni", " sabiti", "()"]:
            if query.endswith(suffix):
                query = query[:-len(suffix)].strip()
        # Qualification identifies scope; dropping it can select a different method.
        parts = query.split('.')
        if not all(part.isidentifier() for part in parts):
            raise ValueError('Sembol aracı kod adı alır; cümle veya path almaz.')
    # Literal içerik her dilde olabilir. Sözcük kara listesi kullanma.
    return query


def search_key(tool, query):
    query = query.strip()
    return tool, query.casefold() if tool == 'search_code' else query


def reject_repeated_searches(requests, previous):
    seen = {search_key(item['tool'], item['query']) for item in previous if 'query' in item}
    current = set()
    for request in requests:
        key = search_key(request.tool, request.query)
        if key in seen or key in current:
            raise ValueError('Bu arama zaten denendi. Observation sonucunu kullan; farklı hedef seç, '
                             'okunmuş kodu yorumla veya dur. Aynı sorguyu tekrarlama.')
        current.add(key)


def symbol_match_rank(wanted, actual):
    """Python adları case-sensitive kalır; benzerlik yalnız arama adayıdır."""
    if wanted == actual:
        return 0
    if wanted.casefold() == actual.casefold():
        return 1
    if min(len(wanted), len(actual)) >= 5 and SequenceMatcher(
            None, wanted.casefold(), actual.casefold()).ratio() >= 0.9:
        return 2
    return None


ROUTE_INSTRUCTION = '''Understand the original question and distinguish its subject, assumptions and requested results.
Choose the function whose behavior is being asked about, not a quoted expected output or a helper mentioned in a hypothetical input.
Preserve code identifiers, qualified names and filenames. Prefer one focused definition/file search; use more only for independent subjects.
Use find_symbol for definitions (including Class.method or module.function), find_file for paths, find_references/find_calls for uses, and search_code for literal text.
A zero result is not proof of absence: reconsider the identifier, qualification or relevant file before changing topics.
For filename-only requests use intent list_files with relative glob patterns: * stays within a directory, ** spans zero or more directories.
Do not use list_files for behavior or configuration questions. Choose explain_behavior for results/conditions; trace_call for forwarding a value to its invocation.
Prefer application code for runtime behavior. Allow test sources (policy any) when the question is about tests.
Keep requirements as the user's requested facts, not proposed answers. Do not answer yet.
Use the user's language and return only the stage JSON.'''

ASSESS_INSTRUCTION = '''Compare the original question with the actually read source.
For each requested fact state the established result and evidence IDs, or the concrete missing dependency.
A caller mentioning a helper does not establish that helper's behavior. Read necessary repository dependencies; do not chase unrelated names or standard-library internals.
Keep assumptions distinct from actual repository values, and comments/docstrings distinct from executed statements.
Use ordinary language semantics: distinguish return values, printed output, branches and exceptions. Do not invent operations from function names.
Choose search/read for missing source, interpret when source is present but needs synthesis, answer when the requested facts are established, or stop when no justified route remains.
Use available search actions and unread candidates; do not repeat completed searches. Checks must cover only the original request.
Return concise stage JSON in the user's language.'''

DRAFT_INSTRUCTION = '''Derive the answer from the original question and read source. No earlier model conclusion is evidence.
Write one concrete claim per answer_requirements ID, including all parts of that requirement, with supporting evidence IDs.
Do not add unrequested error scenarios. Use callable_statements to distinguish each function's own return/raise from its caller's handling; these are source locators, not execution results.
For a claim that one function calls another, cite the caller block too, not just the helper definition.
Follow the relevant operations in execution order before stating the outcome. Distinguish the user's hypothetical inputs from repository facts.
Distinguish assumptions from actual values, comments from operations, and printed output from return values.
Explain the decisive operation/condition and its consequence. Use ordinary language semantics; acknowledge unknown dependency behavior.
Explain the relevant condition and its effect; exact code excerpts are attached by the controller from cited evidence.
Explain an exception mechanism only when it is relevant; not every mechanism is exception-based.
Do not invent author intent, source locations or examples. Locations are attached by the controller.
Use the user's language, backticks for identifiers and confidence as an uncertain self-assessment. Return only Draft JSON.'''

REPAIR_INSTRUCTION = DRAFT_INSTRUCTION + '''
Address review_feedback by re-evaluating the source. A rejected draft or reviewer opinion is not a fact to preserve.
Use existing evidence for wording repairs; do not pretend unread dependencies were checked.'''

VERIFY_INSTRUCTION = '''Check the original question against the proposed answer and cited source; the draft and earlier reviews are not authoritative.
First interpret the supplied source for the requested scenario, then compare the proposed conclusion with that interpretation. Matching identifiers alone do not establish matching behavior.
Check return/raise ownership against callable_statements and source. A caller's error message is not its helper's return value. Reject incorrect extra claims even if the main answer is correct.
Return question_checklist, issues, supported and complete, not a revised answer.
Check each supplied review_facts clause exactly once, preserving its wording. Use answer_ids to identify answers that cover it; otherwise covered=false and answer_ids=[].
The controller displays cited evidence quotes with the answer. Missing verbatim code in prose alone is not a failure.
Still require the prose to explain the relevant condition and result correctly: an attached code block does not fix a wrong or incomplete explanation.
A mention of a helper/value is not its concrete result. If required helper behavior is unread or an answer omits part of the request, complete=false.
Use programming-language semantics but do not invent executed operations, external behavior or author intent.
Distinguish assumptions, comments, outputs, returns and branch conditions. Reject unsupported claims, not a correctly refuted premise.
Resolve previous review_feedback against source. Accept only if supported and complete with issues=[].
Keep explanations short in the user's language.'''
