import ast
import os
import re
from pathlib import Path
from navigation import symbol_match_rank

# Güvenlik sınırı, komutun hangi klasörden çalıştırıldığına değil bu dosyanın
# bulunduğu proje klasörüne bağlıdır.
PROJECT_ROOT = Path(__file__).resolve().parent
MAX_READ_LINES = 80
MAX_SEARCH_RESULTS = 50
EXCLUDED_DIRECTORIES = {".git", "venv", "__pycache__"}
SOURCE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".c", ".h", ".cpp"}


def _resolve_safe_path(target_path):
    """Kullanıcı yolunu çöz ve yalnızca proje içindeyse Path olarak döndür."""
    try:
        candidate = Path(target_path)
        if not candidate.is_absolute():
            candidate = PROJECT_ROOT / candidate
        resolved_path = candidate.resolve()
        resolved_path.relative_to(PROJECT_ROOT)
        return resolved_path
    except (TypeError, ValueError, OSError):
        return None


def _is_safe_path(target_path):
    """
    Güvenlik Kontrolü (Filesystem Boundary):
    Ajanın verdiği yolun, bizim belirlediğimiz proje klasörünün içinde kalıp kalmadığını kontrol eder.
    Böylece ajan gidip Masaüstü'nü veya sistem dosyalarını okuyamaz.

    ``Path.relative_to`` kullanımı, ``/proje`` ile ``/proje-kopya`` gibi
    ortak önek taşıyan ama proje dışında kalan yolları güvenli biçimde reddeder.
    """
    return _resolve_safe_path(target_path) is not None


def _display_path(path):
    """Modelin gereksiz mutlak yol görmemesi için proje-içi yolu göster."""
    return str(path.relative_to(PROJECT_ROOT)) or "."


def _result_priority(file_path, line, query):
    """Tanımı/uygulamayı yorumlardan, testlerden ve dokümanlardan önce gösterir."""
    is_test_file = file_path.name.startswith("test_") or file_path.name.endswith("_test.py")
    is_inside_tests_directory = "tests" in file_path.parts
    if file_path.suffix.lower() == ".md":
        file_category = 2
    elif is_test_file or is_inside_tests_directory:
        file_category = 1
    else:
        file_category = 0
    stripped_line = line.strip()
    is_definition = (
        stripped_line.startswith(f"def {query}")
        or stripped_line.startswith(f"class {query}")
        or stripped_line.startswith(f"{query} =")
    )
    is_comment = stripped_line.startswith(("#", "//", "/*", "*"))
    return (file_category, 0 if is_definition else 1, 1 if is_comment else 0)


def _format_search_results(header, results):
    """Sonuçları kaynak kod önceliğiyle, sınırlı ve deterministik biçimde döndürür."""
    sorted_results = sorted(results, key=lambda item: (item[0], item[1]))
    selected_results = [text for _, text in sorted_results[:MAX_SEARCH_RESULTS]]
    limit_message = " (sonuç limiti uygulandı)" if len(results) > MAX_SEARCH_RESULTS else ""
    return f"{header}{limit_message}:\n" + "\n".join(selected_results)


def list_files(directory_path="."):
    """
    Belirtilen klasördeki dosya ve klasörlerin isimlerini listeler.
    Ajan projede nelerin olduğunu görmek için bunu kullanacak.
    """
    directory = _resolve_safe_path(directory_path)
    if directory is None:
        return "HATA: Güvenlik ihlali! Proje ana klasörü dışındaki bir dizini listeleyemezsiniz."
    if not directory.is_dir():
        return f"HATA: {_display_path(directory)} bir klasör değil veya bulunamadı."

    entries = sorted(
        entry.name
        for entry in directory.iterdir()
        if not entry.name.startswith(".") and entry.name not in EXCLUDED_DIRECTORIES
    )
    return f"{_display_path(directory)} içindeki dosya ve klasörler:\n" + "\n".join(entries)


def find_file(file_name, directory="."):
    """Dosya içeriğini değil, proje-içi dosya adını/yolunu arar."""
    search_directory = _resolve_safe_path(directory)
    if search_directory is None or not search_directory.is_dir():
        return "HATA: Proje içinde geçerli bir arama klasörü gerekli."
    if not isinstance(file_name, str) or not file_name.strip():
        return "HATA: Dosya adı boş olamaz."

    query = file_name.strip().replace("\\", "/")
    exact, fallback = [], []
    for root, directories, files in os.walk(search_directory):
        directories[:] = [
            name for name in directories
            if name not in EXCLUDED_DIRECTORIES and not name.startswith(".")
        ]
        for name in files:
            if name.startswith("."):
                continue
            path = Path(root) / name
            if _resolve_safe_path(path) is None:
                continue
            relative = _display_path(path)
            row = ((_result_priority(path, "", query), relative),
                   f"{relative} (Satır 1): [DOSYA] {relative}")
            if relative == query or name == query:
                exact.append(row)
            elif relative.casefold() == query.casefold() or name.casefold() == query.casefold():
                fallback.append(row)

    matches = exact or fallback
    if not matches:
        return f"Dosya bulunamadı: Projede '{query}' adlı dosya yok."
    results = [(priority, text) for (priority, _), text in matches]
    return _format_search_results("Bulunan dosyalar", results)


def read_file(file_path, start_line, end_line):
    """
    Belirtilen dosyanın içeriğini okur. 
    Eğer start_line ve end_line verilirse, sadece o satırlar arasını okur.
    Bu, Context Length (Hafıza) sınırını aşmamak için çok önemlidir.
    """
    path = _resolve_safe_path(file_path)
    if path is None:
        return "HATA: Güvenlik ihlali! Proje ana klasörü dışındaki bir dosyayı okuyamazsınız."
    if not path.is_file():
        return f"HATA: {_display_path(path)} bir dosya değil veya bulunamadı."
    if type(start_line) is not int or type(end_line) is not int:
        return "HATA: start_line ve end_line pozitif tam sayı olmalıdır."
    if start_line < 1 or end_line < start_line:
        return "HATA: Satır aralığı geçersiz. 1 <= start_line <= end_line olmalıdır."
    if end_line - start_line + 1 > MAX_READ_LINES:
        return f"HATA: Tek okumada en fazla {MAX_READ_LINES} satır istenebilir."

    try:
        with path.open("r", encoding="utf-8") as file:
            lines = file.readlines()
        selected_lines = lines[start_line - 1:end_line]
        return "".join(selected_lines)
    except UnicodeDecodeError:
        return f"HATA: {_display_path(path)} metin dosyası olarak okunamadı."
    except OSError as error:
        return f"HATA: Dosya okunurken sorun oluştu: {error}"

def search_code(query, directory="."):
    """
    Projedeki tüm Python, JS vb. kaynak kod dosyalarının içinde belirli bir kelimeyi/kodu arar.
    Örn: search_code('def reverse_string') -> Bu fonksiyonun hangi dosyada geçtiğini bulur.
    """
    search_directory = _resolve_safe_path(directory)
    if search_directory is None:
        return "HATA: Güvenlik ihlali! Proje ana klasörü dışında arama yapamazsınız."
    if not search_directory.is_dir():
        return f"HATA: {_display_path(search_directory)} bir klasör değil veya bulunamadı."
    if not isinstance(query, str) or not query.strip():
        return "HATA: Arama sorgusu boş olamaz."
    
    results = []
    folded_query = query.casefold()
    runtime_match = False
    
    # os.walk klasörlerin içine girerek tüm dosyaları sırayla gezmemizi sağlar
    for root, directories, files in os.walk(search_directory):
        # Eğer şu anki klasör gizli bir klasörse veya venv ise onu atla (hız için)
        directories[:] = [name for name in directories if name not in EXCLUDED_DIRECTORIES and not name.startswith(".")]
            
        for file_name in files:
            # Sadece uzantısı olan text/kod dosyalarında arama yapalım (resim dosyalarını falan atlamak için)
            if file_name.startswith('.'):
                continue
                
            file_path = Path(root) / file_name
            if _resolve_safe_path(file_path) is None:
                continue
            
            try:
                with file_path.open('r', encoding='utf-8') as f:
                    # Dosyadaki her bir satırı numarasıyla (enumerate) birlikte kontrol ediyoruz
                    for line_number, line in enumerate(f, 1):
                        if query in line or folded_query in line.casefold():
                            # Bulduğumuzda dosya yolu ve satır numarasını listeye ekliyoruz
                            base_priority = _result_priority(file_path, line, query)
                            if base_priority[0] == 0 and file_path.suffix.lower() in SOURCE_EXTENSIONS:
                                runtime_match = True
                            # Önce kaynak türü (runtime/test/docs), sonra aynı
                            # tür içinde tam yazım eşleşmesi gelir. Böylece bir
                            # testteki exact metin runtime'daki casing fallback'ini ezmez.
                            priority = (
                                base_priority[0], 0 if query in line else 1,
                                *base_priority[1:],
                            )
                            results.append(
                                (
                                    priority,
                                    f"{_display_path(file_path)} (Satır {line_number}): {line.strip()}",
                                )
                            )
            except (OSError, UnicodeDecodeError):
                # Eğer dosya okunamıyorsa (örn: resim dosyasıysa) hatayı yoksayıp diğer dosyaya geç
                continue
                
    if not runtime_match:
        # Cümledeki gerçek sembol tanımları yalnız adaydır; cevap tablosu yoktur.
        tokens = list(dict.fromkeys(re.findall(r'[^\W\d]\w*', query)))
        if len(tokens) > 1:
            definitions = []
            for token in sorted(tokens, key=len, reverse=True)[:4]:
                found = find_symbol(token, directory)
                definitions.extend(row for row in found.splitlines()
                                   if re.match(r'^.+? \(Satır \d+\): ', row))
            if definitions:
                header = ('Literal ifade bulunamadı' if not results else
                          'Literal eşleşme uygulama kodunda yok')
                for row in dict.fromkeys(definitions):
                    match = re.match(r'^(.+?) \(Satır \d+\): (.*)$', row)
                    file, preview = match.groups()
                    base = _result_priority(Path(file), preview, '')
                    results.append(((base[0], 1, *base[1:]), row))
                # Doküman eşleşmelerini sakla; gerçek kod tanımlarını öncelikle sun.
                return _format_search_results(
                    header + '; sorgudaki gerçek sembol tanımları da eklendi (yalnız aday)', results)
    if not results:
        return f"Arama sonucu: '{query}' projedeki hiçbir dosyada bulunamadı."
        
    return _format_search_results("Bulunan sonuçlar", results)

def find_symbol(symbol_name, directory="."):
    """
    Projede belirli bir fonksiyon, sınıf (class) veya değişkenin TANIMLANDIĞI (definition) yeri bulur.
    Örn: 'def my_function' veya 'class User' gibi tanımlamaları arar.
    Bu, search_code'dan farklı olarak kodun geçtiği her yeri değil, sadece asıl tanımlandığı yeri bulmak için kullanılır.
    Ajanın dosyalar arasında kaybolmadan direkt hedefe gitmesini sağlar.
    """
    search_directory = _resolve_safe_path(directory)
    if search_directory is None:
        return "HATA: Güvenlik ihlali! Proje ana klasörü dışında arama yapamazsınız."
    if not search_directory.is_dir():
        return f"HATA: {_display_path(search_directory)} bir klasör değil veya bulunamadı."
    if not isinstance(symbol_name, str) or not symbol_name.strip():
        return "HATA: Sembol adı boş olamaz."
        
    results = []
    suggestions = []
    
    # Sadece tanımlamaları yakalamak için (Python ve JS/TS uyumlu basit bir regex şablonu)
    # Örn: def kelime, class kelime, function kelime, const kelime
    pattern = re.compile(
        rf'^\s*(?:(?:export\s+)?(?:async\s+)?(?:def|class|function|const|let|var)\s+'
        rf'{re.escape(symbol_name)}\b|{re.escape(symbol_name)}\s*(?::[^=\n]+)?=(?!=))'
    )
    
    for root, directories, files in os.walk(search_directory):
        directories[:] = [name for name in directories if name not in EXCLUDED_DIRECTORIES and not name.startswith(".")]
            
        for file_name in files:
            if file_name.startswith('.'):
                continue
                
            file_path = Path(root) / file_name
            if _resolve_safe_path(file_path) is None:
                continue
            
            try:
                source = file_path.read_text(encoding='utf-8')
                definition_lines = None
                suggested_lines = {}
                if file_path.suffix == '.py':
                    try:
                        tree = ast.parse(source)
                        parents = {child: parent for parent in ast.walk(tree)
                                   for child in ast.iter_child_nodes(parent)}

                        def matches_definition(node, name):
                            # Qualified definitions are structural names, not contiguous text.
                            parts = [name]
                            parent = parents.get(node)
                            while parent is not None:
                                if isinstance(parent, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                                    parts.insert(0, parent.name)
                                parent = parents.get(parent)
                            wanted = symbol_name.strip().split('.')
                            actual = '.'.join(parts[-len(wanted):])
                            rank = symbol_match_rank('.'.join(wanted), actual)
                            if rank in (1, 2):
                                suggested_lines[node.lineno] = min(rank, suggested_lines.get(node.lineno, rank))
                            return rank == 0

                        definition_lines = set()
                        for node in ast.walk(tree):
                            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                                if matches_definition(node, node.name):
                                    definition_lines.add(node.lineno)
                            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                                if any(isinstance(part, ast.Name) and isinstance(part.ctx, ast.Store) and matches_definition(node, part.id)
                                       for target in targets for part in ast.walk(target)):
                                    definition_lines.add(node.lineno)
                    except SyntaxError:
                        pass
                for line_number, line in enumerate(source.split('\n'), 1):
                    if line_number in suggested_lines:
                        suggestions.append(((suggested_lines[line_number], *_result_priority(file_path, line, symbol_name)),
                                            f"{_display_path(file_path)} (Satır {line_number}): {line.strip()}"))
                    is_definition = (line_number in definition_lines if definition_lines is not None
                                     else pattern.search(line))
                    if is_definition:
                        results.append(
                            (
                                _result_priority(file_path, line, symbol_name),
                                f"{_display_path(file_path)} (Satır {line_number}): {line.strip()}",
                            )
                        )
            except (OSError, UnicodeDecodeError):
                continue
                
    if not results:
        if suggestions:
            return _format_search_results(
                'Tam sembol eşleşmesi yok; benzer yazımlı tanımlar (yalnız aday, kimlik eşitliği değil)',
                sorted(suggestions)[:5])
        return f"Sembol bulunamadı: Projede '{symbol_name}' adında bir fonksiyon, sınıf veya değişken tanımı bulunamadı."
        
    return _format_search_results("Bulunan sembol tanımları", results)


def find_references(symbol_name, directory="."):
    """Bir sembolün tanımı dışındaki kod kullanımlarını AST ile bulur."""
    search_directory = _resolve_safe_path(directory)
    if search_directory is None or not search_directory.is_dir():
        return "HATA: Proje içinde geçerli bir arama klasörü gerekli."
    if not isinstance(symbol_name, str) or not symbol_name.strip():
        return "HATA: Sembol adı boş olamaz."
    symbol_name = symbol_name.strip()
    results = []

    for root, directories, files in os.walk(search_directory):
        directories[:] = [
            name for name in directories
            if name not in EXCLUDED_DIRECTORIES and not name.startswith(".")
        ]
        for name in files:
            path = Path(root) / name
            if name.startswith(".") or path.suffix.lower() not in SOURCE_EXTENSIONS:
                continue
            if _resolve_safe_path(path) is None:
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            lines = source.split('\n')
            reference_lines = set()
            if path.suffix.lower() == ".py":
                try:
                    tree = ast.parse(source)
                except SyntaxError:
                    tree = None
                if tree is not None:
                    reference_lines.update(
                        node.lineno for node in ast.walk(tree)
                        if isinstance(node, ast.Name) and node.id == symbol_name
                        and isinstance(node.ctx, ast.Load)
                    )
                    reference_lines.update(
                        node.lineno for node in ast.walk(tree)
                        if isinstance(node, ast.Attribute) and node.attr == symbol_name
                        and isinstance(node.ctx, ast.Load)
                    )
            else:
                pattern = re.compile(rf"\b{re.escape(symbol_name)}\b")
                reference_lines.update(
                    number for number, line in enumerate(lines, 1) if pattern.search(line)
                )
            for number in sorted(reference_lines):
                line = lines[number - 1] if number <= len(lines) else ""
                results.append((_result_priority(path, line, symbol_name),
                                f"{_display_path(path)} (Satır {number}): {line.strip()}"))

    if not results:
        return f"Kullanım bulunamadı: '{symbol_name}' kod içinde referans edilmiyor."
    return _format_search_results("Bulunan sembol kullanımları", results)


def find_calls(call_name, directory="."):
    """Python AST içinde bir fonksiyon/metot çağrısının call-site'larını bulur."""
    search_directory = _resolve_safe_path(directory)
    if search_directory is None or not search_directory.is_dir():
        return "HATA: Proje içinde geçerli bir arama klasörü gerekli."
    if not isinstance(call_name, str) or not call_name.strip():
        return "HATA: Çağrı adı boş olamaz."
    call_name = call_name.strip()
    results = []

    def dotted_name(node):
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            prefix = dotted_name(node.value)
            return f"{prefix}.{node.attr}" if prefix else node.attr
        return ""

    for root, directories, files in os.walk(search_directory):
        directories[:] = [
            name for name in directories
            if name not in EXCLUDED_DIRECTORIES and not name.startswith(".")
        ]
        for name in files:
            path = Path(root) / name
            if name.startswith(".") or path.suffix.lower() != ".py":
                continue
            if _resolve_safe_path(path) is None:
                continue
            try:
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source)
            except (OSError, UnicodeDecodeError, SyntaxError):
                continue
            lines = source.split('\n')
            for number in sorted({
                node.lineno for node in ast.walk(tree) if isinstance(node, ast.Call)
                and (dotted_name(node.func) == call_name
                     or dotted_name(node.func).split(".")[-1] == call_name)
            }):
                line = lines[number - 1]
                results.append((_result_priority(path, line, call_name),
                                f"{_display_path(path)} (Satır {number}): {line.strip()}"))

    if not results:
        return f"Çağrı bulunamadı: '{call_name}' Python kodunda çağrılmıyor."
    return _format_search_results("Bulunan çağrı yerleri", results)


def find_tests(symbol_name, directory="."):
    """Bir sembolü kullanan Python test fonksiyonlarını AST ile bulur."""
    search_directory = _resolve_safe_path(directory)
    if search_directory is None or not search_directory.is_dir():
        return "HATA: Proje içinde geçerli bir arama klasörü gerekli."
    if not isinstance(symbol_name, str) or not symbol_name.strip():
        return "HATA: Test hedefi boş olamaz."

    query = symbol_name.strip().split(".")[-1]
    results = []
    for root, directories, files in os.walk(search_directory):
        directories[:] = [
            name for name in directories
            if name not in EXCLUDED_DIRECTORIES and not name.startswith(".")
        ]
        for file_name in files:
            path = Path(root) / file_name
            is_test = (
                file_name.startswith("test_")
                or file_name.endswith("_test.py")
                or "tests" in path.parts
            )
            if not is_test or path.suffix != ".py" or _resolve_safe_path(path) is None:
                continue
            try:
                text = path.read_text(encoding="utf-8")
                tree = ast.parse(text)
            except (OSError, UnicodeDecodeError, SyntaxError):
                continue
            lines = text.split('\n')
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if not node.name.startswith("test"):
                    continue
                used = any(
                    (isinstance(part, ast.Name) and part.id == query)
                    or (isinstance(part, ast.Attribute) and part.attr == query)
                    for part in ast.walk(node)
                )
                if not used:
                    continue
                preview = lines[node.lineno - 1].strip()
                results.append((
                    _result_priority(path, preview, query),
                    f"{_display_path(path)} (Satır {node.lineno}): {preview}",
                ))
    if not results:
        return f"Test bulunamadı: '{symbol_name}' hiçbir Python test fonksiyonunda kullanılmıyor."
    return _format_search_results("Bulunan davranış testleri", results)
