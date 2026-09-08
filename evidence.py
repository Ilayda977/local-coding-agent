"""Kaynak kimlikleri, AST tabanlı okuma bağlamı ve değişmez kanıt kaydı."""
import ast
import builtins
import hashlib
import io
import keyword
import os
import re
import sys
import tokenize
import textwrap
from dataclasses import asdict, dataclass
from pathlib import Path

import tools
from protocol import tool_call_signature


class EvidenceError(RuntimeError):
    pass


STANDARD_ATTRS = (
    set(dir(object))
    | set(dir(str))
    | set(dir(dict))
    | set(dir(list))
    | set(dir(set))
    | set(dir(tuple))
    | set(dir(int))
    | set(dir(float))
    | set(dir(bool))
    | set(dir(Exception))
)


@dataclass(frozen=True)
class Candidate:
    id: str
    file: str
    line: int
    preview: str
    source_kind: str
    scope: str


@dataclass(frozen=True)
class SourceLine:
    id: str
    file: str
    line: int
    text: str


def source_lines(text):
    """Python text-mode okumasındaki satır sınırlarını korur, Unicode ayraçlarını bölmez."""
    lines = text.split("\n")
    return lines[:-1] if lines and lines[-1] == "" else lines


def context_range(text, line, is_python=True, limit=None):
    """Seçilen tanımın gövdesi; atamalar için ilgili statement; diğer dillerde küçük pencere."""
    limit = limit or tools.MAX_READ_LINES
    lines = source_lines(text)
    if not 1 <= line <= len(lines):
        raise EvidenceError("Arama sonucu artık geçerli bir kaynak satırı değil.")
    start, end = max(1, line - 4), min(len(lines), line + 24)
    if is_python:
        try:
            tree = ast.parse(text)
            blocks = [node for node in ast.walk(tree)
                      if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                      and node.lineno <= line <= node.end_lineno]
            statements = [node for node in ast.walk(tree)
                          if isinstance(node, (ast.Assign, ast.AnnAssign, ast.Import, ast.ImportFrom))
                          and node.lineno <= line <= node.end_lineno]
            relevant = blocks or statements
            if relevant:
                node = min(relevant, key=lambda item: item.end_lineno - item.lineno)
                start, end = node.lineno, node.end_lineno
        except SyntaxError:
            pass
    if end - start + 1 > limit:
        start = max(start, line - 4)
        end = min(end, start + limit - 1)
    return start, end


class EvidenceStore:
    def __init__(self, max_chars=16000):
        self.candidates = {}
        self.lines = {}
        self.blocks = {}
        self.file_hashes = {}
        self.searches = set()
        self.read_candidates = set()
        self.max_chars = max_chars
        self.tool_calls = []

    def _path(self, file):
        path = tools._resolve_safe_path(file)
        if path is None or not path.is_file():
            raise EvidenceError(f"Proje içinde geçerli dosya değil: {file}")
        return path

    def _candidate(self, file, line, preview):
        for item in self.candidates.values():
            if (item.file, item.line) == (file, line):
                return item
        path = Path(file)
        is_test = path.name.startswith("test_") or path.name.endswith("_test.py") or "tests" in path.parts
        source_kind = (
            "docs" if path.suffix.lower() == ".md" else
            "test" if is_test else
            "source" if path.suffix.lower() in tools.SOURCE_EXTENSIONS else
            "other"
        )
        scope = ""
        if path.suffix.lower() == ".py":
            try:
                tree = ast.parse(self._path(file).read_text(encoding="utf-8"))
                enclosing = [
                    node for node in ast.walk(tree)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    and node.lineno <= line <= node.end_lineno
                ]
                if enclosing:
                    scope = min(
                        enclosing, key=lambda node: node.end_lineno - node.lineno,
                    ).name
            except (OSError, UnicodeDecodeError, SyntaxError):
                pass
        item = Candidate(
            f"C{len(self.candidates) + 1}", file, line, preview, source_kind, scope,
        )
        self.candidates[item.id] = item
        return item

    def is_read(self, candidate_id):
        candidate = self.candidates[candidate_id]
        return candidate_id in self.read_candidates or any(
            line.file == candidate.file and line.line == candidate.line for line in self.lines.values()
        )

    def search(self, request):
        signature = tool_call_signature(request.tool, {"query": request.query.strip()})
        if signature in self.searches:
            return []
        self.searches.add(signature)
        handler = {
            "find_file": tools.find_file,
            "find_symbol": tools.find_symbol,
            "find_references": tools.find_references,
            "find_calls": tools.find_calls,
            "find_tests": tools.find_tests,
            "search_code": tools.search_code,
        }[request.tool]
        result = handler(request.query.strip())
        call = {"tool": request.tool, "query": request.query.strip(), "candidate_count": 0,
                "matched_count": 0, "already_read_count": 0}
        call["observation"] = result.split('\n', 1)[0][:240]
        self.tool_calls.append(call)
        if result.startswith("HATA:"):
            raise EvidenceError(result)
        matches = []
        for row in result.splitlines():
            match = re.match(r"^(.+?) \(Satır (\d+)\): (.*)$", row)
            if not match:
                continue
            file, line, preview = match.groups()
            path = self._path(file)
            file = str(path.relative_to(tools.PROJECT_ROOT))
            item = self._candidate(file, int(line), preview)
            call["matched_count"] += 1
            if not self.is_read(item.id):
                matches.append(item.id)
            else:
                call["already_read_count"] += 1
            if len(matches) >= 12:
                break
        matches = list(dict.fromkeys(matches))
        call["candidate_count"] = len(matches)
        return matches

    def listed_file_candidates(self, listing, limit=12):
        """Arama boşsa listelenmiş dosyaları seçilebilir yap; içerikleri kanıt sayma."""
        ids = []
        for name in listing.splitlines()[1:]:
            path = tools._resolve_safe_path(name.strip())
            if path is None or not path.is_file():
                continue
            file = str(path.relative_to(tools.PROJECT_ROOT))
            item = self._candidate(file, 1, '[DOSYA] ' + file)
            if not self.is_read(item.id):
                ids.append(item.id)
            if len(ids) >= limit:
                break
        return ids

    def read(self, candidate_id):
        if candidate_id not in self.candidates:
            raise EvidenceError("Bilinmeyen kaynak adayı.")
        if self.is_read(candidate_id):
            return []
        candidate = self.candidates[candidate_id]
        path = self._path(candidate.file)
        # AST analizi yalnız controller'da; modele tüm dosya gönderilmez.
        if path.stat().st_size > 1_000_000:
            raise EvidenceError("Dosya AST/context inceleme boyut sınırını aşıyor.")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if candidate.file in self.file_hashes and self.file_hashes[candidate.file] != digest:
            raise EvidenceError("Araştırma sırasında dosya değişti; kanıt sürümleri karıştırılmadı.")
        text = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        start, end = context_range(text, candidate.line, path.suffix == ".py")
        if candidate.preview.startswith("[DOSYA]"):
            # Dosya seçimi ilk import'un tek satırına indirgenmez.
            start, end = 1, min(len(source_lines(text)), 25, tools.MAX_READ_LINES)
            if end == 0:
                raise EvidenceError("Seçilen dosya boş; kaynak kanıtı içermiyor.")
        content = tools.read_file(candidate.file, start, end)
        self.tool_calls.append({"tool": "read_file", "file_path": candidate.file,
                                "start_line": start, "end_line": end})
        if content.startswith("HATA:") or self._path(candidate.file).read_bytes() != raw:
            raise EvidenceError("Kaynak okunamadı veya okuma sırasında değişti.")
        self.file_hashes[candidate.file] = digest
        self.read_candidates.add(candidate_id)
        existing = {(line.file, line.line) for line in self.lines.values()}
        new_lines = [(start + offset, row) for offset, row in enumerate(source_lines(content))
                     if (candidate.file, start + offset) not in existing]
        if sum(len(item.text) for item in self.lines.values()) + sum(len(row) for _, row in new_lines) > self.max_chars:
            raise EvidenceError("Kaynak bağlam bütçesi doldu; sessizce veri kesilmedi.")
        added = []
        for number, row in new_lines:
            item = SourceLine(f"L{len(self.lines) + 1}", candidate.file, number, row)
            self.lines[item.id] = item
            added.append(item.id)
        # Kanıt birimi tek kopuk satır değil, fiilen okunan sınırlı kaynak bloğudur.
        # Satır aralığı/alıntı modelden gelmez; registry'deki gerçek satırlardan oluşur.
        if added:
            self.blocks[f"E{len(self.blocks) + 1}"] = [
                item.id for item in self.lines.values()
                if item.file == candidate.file and start <= item.line <= end
            ]
        # Uzun bloklar gerektiğinde başka bir seçimle, yine sınır içinde okunabilir.
        if end < len(source_lines(text)):
            self._candidate(candidate.file, end + 1, "Devamındaki bağlam (yalnız gerekliyse oku)")
        return added

    def unread_claim_values(self, checks):
        """Modelin iddiasında kullandığı, henüz tanımı okunmamış yerel değerler.

        AST yalnız konum bulur; bulunan tanım okunmadan kanıt olmaz. Bütün
        bağımlılıklar takip edilmez: isim hem iddiada hem atıf yapılan kodda
        bulunmalıdır. Bu kontrol anlamsal doğruluk garantisi değildir.
        """
        self.assert_unchanged()
        candidates = []
        observed = {(item.file, item.line) for item in self.lines.values()}
        for check in checks:
            if check.status != 'supported':
                continue
            mentioned = set(re.findall(r'\b[^\W\d]\w*\b', check.observed_answer))
            for citation in self.block_citations(check.evidence_ids):
                file = citation['file']
                if not file.endswith('.py'):
                    continue
                try:
                    tree = ast.parse(self._path(file).read_text(encoding='utf-8'))
                except (SyntaxError, UnicodeError):
                    continue
                try:
                    block = ast.parse(textwrap.dedent(citation['quote']))
                    loaded = {node.id for node in ast.walk(block)
                              if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
                    loaded.update(node.attr for node in ast.walk(block)
                                  if isinstance(node, ast.Attribute) and not node.attr.startswith('_')
                                  and node.attr not in STANDARD_ATTRS)
                    bound = {node.id for node in ast.walk(block)
                             if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)}
                    bound.update(node.arg for node in ast.walk(block) if isinstance(node, ast.arg))
                except SyntaxError:
                    loaded = set()
                    try:
                        for token in tokenize.generate_tokens(io.StringIO(citation['quote']).readline):
                            if token.type == tokenize.NAME and not keyword.iskeyword(token.string):
                                loaded.add(token.string)
                    except Exception:
                        pass
                    bound = set()
                # Yerel parametre/atama aynı adlı modül değişkeniyle karışmaz.
                needed = mentioned & (loaded - bound)
                found_names = set()
                for statement in tree.body:
                    if not isinstance(statement, (ast.Assign, ast.AnnAssign)) or statement.value is None:
                        continue
                    targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                    names = {node.id for target in targets for node in ast.walk(target)
                             if isinstance(node, ast.Name)}
                    if not names & needed:
                        continue
                    found_names.update(names & needed)
                    if all((file, number) in observed
                           for number in range(statement.lineno, statement.end_lineno + 1)):
                        continue
                    # Değer aktarılmaz; model gerçek adayı seçip read_file ile okur.
                    item = self._candidate(file, statement.lineno,
                                           'İddiada kullanılan değerin okunmamış tanımı: '
                                           + ', '.join(sorted(names & needed)))
                    candidates.append(item.id)
                remaining_needed = needed - found_names
                if remaining_needed:
                    for root, directories, files in os.walk(tools.PROJECT_ROOT):
                        directories[:] = [d for d in directories if d not in tools.EXCLUDED_DIRECTORIES and not d.startswith('.')]
                        for file_name in sorted(files):
                            if file_name.startswith("test_") or not file_name.endswith(".py") or file_name.endswith("_test.py"):
                                continue
                            other_path = Path(root) / file_name
                            rel_other = str(other_path.relative_to(tools.PROJECT_ROOT))
                            if rel_other == file:
                                continue
                            try:
                                other_tree = ast.parse(other_path.read_text(encoding='utf-8'))
                            except (SyntaxError, UnicodeError):
                                continue
                            for statement in other_tree.body:
                                if not isinstance(statement, (ast.Assign, ast.AnnAssign)) or statement.value is None:
                                    continue
                                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                                names = {node.id for target in targets for node in ast.walk(target)
                                         if isinstance(node, ast.Name)}
                                if not names & remaining_needed:
                                    continue
                                if all((rel_other, number) in observed
                                       for number in range(statement.lineno, statement.end_lineno + 1)):
                                    continue
                                item = self._candidate(rel_other, statement.lineno,
                                                       'İddiada kullanılan değerin okunmamış tanımı: '
                                                       + ', '.join(sorted(names & remaining_needed)))
                                candidates.append(item.id)
        return list(dict.fromkeys(candidates))

    def source_context(self):
        return [dict(id=key, **{k: v for k, v in self.citations(ids)[0].items()
                               if k != "evidence_ids"}) for key, ids in self.blocks.items()]

    def block_citations(self, ids):
        if not ids or any(key not in self.blocks for key in ids):
            raise EvidenceError("Okunmamış veya uydurma kanıt bloğu kimliği.")
        return [dict(block_id=key, **{k: v for k, v in self.citations(self.blocks[key])[0].items()
                                     if k != "evidence_ids"})
                for key in dict.fromkeys(ids)]

    def search_targets(self, include_definitions=False):
        """Yalnız okunmuş kodun isimleri; yorum/alıntıdaki talimatlar hedef oluşturmaz.

        Bu liste öncelik veya zorunlu bağımlılık takibi değildir. Gerekli ismi
        model seçer; controller hiçbir sabit adı ya da sorunun cevabını bilmez.
        Recovery aşaması, okunmuş bir tanımın kullanım yerlerini arayabilmek için
        ``include_definitions=True`` kullanabilir.
        """
        names = set()
        observed_definitions = set()
        for ids in self.blocks.values():
            lines = sorted((self.lines[key] for key in ids), key=lambda item: item.line)
            path = Path(lines[0].file)
            if path.name.startswith("test_") or path.name.endswith("_test.py") or "tests" in path.parts:
                continue
            text = textwrap.dedent("\n".join(line.text for line in lines))
            if lines[0].file.endswith(".py"):
                try:
                    tree = ast.parse(text)
                    for node in tree.body:
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            observed_definitions.add(node.name)
                        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                            observed_definitions.update(
                                part.id for target in targets for part in ast.walk(target)
                                if isinstance(part, ast.Name) and isinstance(part.ctx, ast.Store)
                            )
                    loaded = {node.id for node in ast.walk(tree)
                              if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
                    bound = {node.id for node in ast.walk(tree)
                             if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store)}
                    bound.update(node.arg for node in ast.walk(tree) if isinstance(node, ast.arg))
                    bound.update(node.name for node in ast.walk(tree)
                                 if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
                    bound.update(node.name for node in ast.walk(tree)
                                 if isinstance(node, ast.ExceptHandler) and node.name)
                    names.update(loaded - bound - set(dir(builtins)))
                    continue
                except SyntaxError:
                    pass
            try:
                for token in tokenize.generate_tokens(io.StringIO(text).readline):
                    if token.type == tokenize.NAME and not keyword.iskeyword(token.string):
                        names.add(token.string)
            except (tokenize.TokenError, IndentationError):
                # Kısmi blokta tokenizer'ın hata öncesinde gördüğü gerçek isimler korunur.
                pass
        imported_stdlib = set()
        imported_stdlib_bindings = set()
        for file in self.file_hashes:
            if not file.endswith(".py"):
                continue
            try:
                tree = ast.parse(self._path(file).read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, SyntaxError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root = alias.name.split(".")[0]
                        if root in sys.stdlib_module_names:
                            imported_stdlib.add(root)
                            imported_stdlib_bindings.add(alias.asname or root)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    root = node.module.split(".")[0]
                    if root in sys.stdlib_module_names:
                        imported_stdlib.add(root)
                        imported_stdlib_bindings.update(
                            alias.asname or alias.name for alias in node.names
                        )
        selected = names | observed_definitions if include_definitions else names - observed_definitions
        return sorted(selected - imported_stdlib - imported_stdlib_bindings)

    def observed_callable_names(self):
        """Gerçekten okunmuş bloklarda tanımlanan fonksiyon/sınıf adlarını döndürür."""
        names = set()
        for ids in self.blocks.values():
            lines = sorted((self.lines[key] for key in ids), key=lambda item: item.line)
            if not lines or not lines[0].file.endswith(".py"):
                continue
            path = Path(lines[0].file)
            if path.name.startswith("test_") or path.name.endswith("_test.py") or "tests" in path.parts:
                continue
            try:
                tree = ast.parse(textwrap.dedent("\n".join(line.text for line in lines)))
            except SyntaxError:
                continue
            names.update(
                node.name for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            )
        return sorted(names)

    def observed_assigned_names(self):
        """Gerçekten okunmuş bloklarda atanan değişken/sabit adlarını döndürür."""
        names = set()
        for ids in self.blocks.values():
            lines = sorted((self.lines[key] for key in ids), key=lambda item: item.line)
            if not lines or not lines[0].file.endswith(".py"):
                continue
            path = Path(lines[0].file)
            if path.name.startswith("test_") or path.name.endswith("_test.py") or "tests" in path.parts:
                continue
            try:
                tree = ast.parse(textwrap.dedent("\n".join(line.text for line in lines)))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    names.update(
                        part.id for target in targets for part in ast.walk(target)
                        if isinstance(part, ast.Name) and isinstance(part.ctx, ast.Store)
                    )
        return sorted(names)


    def search_actions(self, include_definitions=False):
        """Okunmuş AST'ye göre anlamlı araç-hedef çiftlerini üretir."""
        assignments, callables, loaded = set(), set(), set()
        for ids in self.blocks.values():
            lines = sorted((self.lines[key] for key in ids), key=lambda item: item.line)
            if not lines or not lines[0].file.endswith(".py"):
                continue
            path = Path(lines[0].file)
            if path.name.startswith("test_") or path.name.endswith("_test.py") or "tests" in path.parts:
                continue
            text = textwrap.dedent("\n".join(line.text for line in lines))
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    callables.add(node.name)
                elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    assignments.update(
                        part.id for target in targets for part in ast.walk(target)
                        if isinstance(part, ast.Name) and isinstance(part.ctx, ast.Store)
                    )
                elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    loaded.add(node.id)

        unresolved = set(self.search_targets())
        actions = []
        for name in sorted(unresolved):
            if (Path(tools.PROJECT_ROOT) / f"{name}.py").is_file():
                actions.append({"tool": "find_file", "query": f"{name}.py"})
            actions.extend(({"tool": "find_symbol", "query": name},
                            {"tool": "search_code", "query": name}))
        if include_definitions:
            for name in sorted(assignments):
                actions.extend(({"tool": "find_references", "query": name},
                                {"tool": "search_code", "query": name}))
            for name in sorted(callables):
                actions.extend(({"tool": "find_calls", "query": name},
                                {"tool": "find_tests", "query": name},
                                {"tool": "find_references", "query": name},
                                {"tool": "search_code", "query": name}))
        unique = {(item["tool"], item["query"]): item for item in actions}
        return [
            item for item in unique.values()
            if tool_call_signature(item["tool"], {"query": item["query"]}) not in self.searches
        ]

    def trace_frontier(self):
        """Daha önce aranan bir sembolün argüman olarak aktarıldığı sonraki çağrıyı bulur."""
        searched_values = {
            str(call["query"]) for call in self.tool_calls if call["tool"] != "read_file"
        }
        searched = {value for value in searched_values if value.isidentifier()}
        frontier = set()

        def dotted_name(node):
            if isinstance(node, ast.Name):
                return node.id
            if isinstance(node, ast.Attribute):
                prefix = dotted_name(node.value)
                return f"{prefix}.{node.attr}" if prefix else node.attr
            return ""

        for ids in self.blocks.values():
            lines = sorted((self.lines[key] for key in ids), key=lambda item: item.line)
            if not lines or not lines[0].file.endswith(".py"):
                continue
            text = textwrap.dedent("\n".join(line.text for line in lines))
            try:
                trees = [ast.parse(text)]
            except SyntaxError:
                # 80 satırlık blok açık bir try/if ortasında kesilmiş olabilir.
                # Yalnız gerçekten okunmuş satırları tek tek parse ederek basit
                # atama/call ifadelerindeki veri akışını yine koruruz.
                trees = []
                for line in text.splitlines():
                    try:
                        trees.append(ast.parse(textwrap.dedent(line)))
                    except SyntaxError:
                        continue
            for tree in trees:
                for node in ast.walk(tree):
                    if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                        continue
                    value = node.value
                    literal_values = {
                        str(part.value) for part in ast.walk(value)
                        if isinstance(part, ast.Constant) and isinstance(part.value, str)
                    }
                    if not any(
                        query.casefold() in literal.casefold()
                        for query in searched_values for literal in literal_values
                    ):
                        continue
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    frontier.update(
                        part.id for target in targets for part in ast.walk(target)
                        if isinstance(part, ast.Name) and isinstance(part.ctx, ast.Store)
                        and part.id not in searched
                    )
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    passed_names = {
                        part.id for value in [*node.args, *(item.value for item in node.keywords)]
                        for part in ast.walk(value) if isinstance(part, ast.Name)
                    }
                    if not (passed_names & searched):
                        continue
                    target = dotted_name(node.func).split(".")[-1]
                    if target and target.isidentifier() and target not in searched:
                        frontier.add(target)
        return sorted(frontier)

    def observed_calls(self):
        """Okunmuş kanıt bloklarındaki gerçek Python call ifadelerini kompaktlaştırır."""
        calls = {}
        for ids in self.blocks.values():
            lines = sorted((self.lines[key] for key in ids), key=lambda item: item.line)
            if not lines or not lines[0].file.endswith(".py"):
                continue
            raw_lines = [line.text for line in lines]
            text = textwrap.dedent("\n".join(raw_lines))
            try:
                trees = [(ast.parse(text), lines[0].line - 1, text.splitlines())]
            except SyntaxError:
                trees = []
                for source_line, item in zip(raw_lines, lines):
                    fragment = textwrap.dedent(source_line)
                    try:
                        trees.append((ast.parse(fragment), item.line - 1, [fragment]))
                    except SyntaxError:
                        continue
            for tree, offset, source_rows in trees:
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    number = offset + node.lineno
                    expression = ast.unparse(node)
                    key = (lines[0].file, number, expression)
                    calls[key] = {
                        "file": lines[0].file,
                        "line": number,
                        "call": expression,
                        "source": source_rows[node.lineno - 1].strip(),
                    }
        return list(calls.values())[:24]

    def observed_conditions(self):
        """Okunmuş Python bloklarındaki gerçek branch/comprehension koşullarını çıkarır."""
        conditions = []
        for ids in self.blocks.values():
            lines = sorted((self.lines[key] for key in ids), key=lambda item: item.line)
            if not lines or not lines[0].file.endswith(".py"):
                continue
            try:
                tree = ast.parse(textwrap.dedent("\n".join(line.text for line in lines)))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                tests = []
                if isinstance(node, (ast.If, ast.IfExp, ast.While, ast.Assert)):
                    tests = [node.test]
                elif isinstance(node, ast.comprehension):
                    tests = node.ifs
                elif isinstance(node, ast.BoolOp):
                    tests = [node]
                for test in tests:
                    expression = ast.unparse(test)
                    if expression not in conditions:
                        conditions.append(expression)
        return conditions[:24]

    def observed_exception_flows(self):
        """Okunmuş Python bloklarındaki try/except aktarımını AST'den özetler."""
        flows = []

        def exception_names(node):
            if node is None:
                return ["BaseException"]
            if isinstance(node, ast.Tuple):
                return [name for item in node.elts for name in exception_names(item)]
            if isinstance(node, ast.Name):
                return [node.id]
            if isinstance(node, ast.Attribute):
                return [ast.unparse(node)]
            return [ast.unparse(node)]

        for ids in self.blocks.values():
            lines = sorted((self.lines[key] for key in ids), key=lambda item: item.line)
            if not lines or not lines[0].file.endswith(".py"):
                continue
            text = textwrap.dedent("\n".join(line.text for line in lines))
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Try):
                    continue
                protected = [ast.unparse(statement) for statement in node.body]
                for handler in node.handlers:
                    flow = {
                        "file": lines[0].file,
                        "try_statements": protected,
                        "guard_statements": [
                            ast.unparse(statement) for statement in node.body
                            if isinstance(statement, ast.Expr)
                            and isinstance(statement.value, ast.Call)
                        ],
                        "caught_exceptions": exception_names(handler.type),
                        "handler_statements": [
                            ast.unparse(statement) for statement in handler.body
                        ],
                    }
                    if flow not in flows:
                        flows.append(flow)
        return flows[:12]

    def trace_terminal_calls(self):
        """Constructor parametresinden self alanına, oradan dış çağrı argümanına akışı çıkarır."""
        results = []
        for block_id, ids in self.blocks.items():
            lines = sorted((self.lines[key] for key in ids), key=lambda item: item.line)
            if not lines or not lines[0].file.endswith(".py"):
                continue
            text = textwrap.dedent("\n".join(line.text for line in lines))
            try:
                tree = ast.parse(text)
            except SyntaxError:
                # Bounded okuma sınıfın sonundaki çok satırlı bir ifadeyi
                # ortadan kesebilir. Son tamamlanmamış ifadeyi atıp yalnız
                # gerçekten okunmuş en uzun geçerli prefix'i çözümle.
                tree = None
                rows = text.splitlines()
                for end in range(len(rows) - 1, 0, -1):
                    try:
                        tree = ast.parse("\n".join(rows[:end]))
                        break
                    except SyntaxError:
                        continue
                if tree is None:
                    continue
            for class_node in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
                tracked_attributes = set()
                for method in class_node.body:
                    if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) or method.name != "__init__":
                        continue
                    parameters = {arg.arg for arg in method.args.args if arg.arg != "self"}
                    for node in ast.walk(method):
                        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                            continue
                        value = node.value
                        if not isinstance(value, ast.Name) or value.id not in parameters:
                            continue
                        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                        tracked_attributes.update(
                            target.attr for target in targets
                            if isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name) and target.value.id == "self"
                        )
                for method in class_node.body:
                    if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) or method.name == "__init__":
                        continue
                    for node in ast.walk(method):
                        if not isinstance(node, ast.Call):
                            continue
                        values = [*node.args, *(keyword.value for keyword in node.keywords)]
                        used_attributes = {
                            part.attr for value in values for part in ast.walk(value)
                            if isinstance(part, ast.Attribute)
                            and isinstance(part.value, ast.Name) and part.value.id == "self"
                        }
                        if not (used_attributes & tracked_attributes):
                            continue
                        results.append({
                            "block_id": block_id,
                            "file": lines[0].file,
                            "line": lines[0].line + node.lineno - 1,
                            "call": ast.unparse(node),
                        })
        for index, item in enumerate(results, 1):
            item["id"] = f"T{index}"
        return results

    def candidate_context(self, ids):
        return [asdict(self.candidates[key]) for key in ids if not self.is_read(key)]

    def candidates_for_policy(self, ids, policy):
        """Router'ın kaynak türü kararını aday seçiminden önce uygular."""
        available = [key for key in ids if key in self.candidates and not self.is_read(key)]
        by_kind = {
            kind: [key for key in available if self.candidates[key].source_kind == kind]
            for kind in ("source", "test", "docs", "other")
        }
        if policy == "code_only":
            return by_kind["source"]
        if policy == "code_first" and by_kind["source"]:
            return by_kind["source"]
        if policy == "docs_first" and by_kind["docs"]:
            return by_kind["docs"]
        return available

    def prioritize_question_scopes(self, ids, question):
        """Soru bir kod kapsamını açıkça adlandırıyorsa o kapsamdaki adayları öne alır."""
        available = [key for key in ids if key in self.candidates and not self.is_read(key)]
        matched = [
            key for key in available
            if self.candidates[key].scope
            and re.search(
                rf"(?<!\w){re.escape(self.candidates[key].scope)}(?!\w)",
                question,
            )
        ]
        return matched or available

    def citations(self, ids):
        if not ids or any(key not in self.lines for key in ids):
            raise EvidenceError("Okunmamış veya uydurma kanıt kimliği.")
        selected = sorted({key: self.lines[key] for key in ids}.values(),
                          key=lambda item: (item.file, item.line))
        groups = []
        for item in selected:
            if groups and groups[-1][-1].file == item.file and groups[-1][-1].line + 1 == item.line:
                groups[-1].append(item)
            else:
                groups.append([item])
        return [{"evidence_ids": [line.id for line in group], "file": group[0].file,
                 "start_line": group[0].line, "end_line": group[-1].line,
                 "quote": "\n".join(line.text for line in group)} for group in groups]

    def assert_unchanged(self):
        for file, digest in self.file_hashes.items():
            if hashlib.sha256(self._path(file).read_bytes()).hexdigest() != digest:
                raise EvidenceError("Kaynak son kontrolde değişmiş; eski kanıtla cevap yayımlanmadı.")
