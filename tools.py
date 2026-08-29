import os
import re
from pathlib import Path

# Güvenlik sınırı, komutun hangi klasörden çalıştırıldığına değil bu dosyanın
# bulunduğu proje klasörüne bağlıdır.
PROJECT_ROOT = Path(__file__).resolve().parent
MAX_READ_LINES = 80
MAX_SEARCH_RESULTS = 50
EXCLUDED_DIRECTORIES = {".git", "venv", "__pycache__"}


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
    if not isinstance(start_line, int) or not isinstance(end_line, int):
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
    
    # os.walk klasörlerin içine girerek tüm dosyaları sırayla gezmemizi sağlar
    for root, directories, files in os.walk(search_directory):
        # Eğer şu anki klasör gizli bir klasörse veya venv ise onu atla (hız için)
        directories[:] = [name for name in directories if name not in EXCLUDED_DIRECTORIES and not name.startswith(".")]
            
        for file_name in files:
            # Sadece uzantısı olan text/kod dosyalarında arama yapalım (resim dosyalarını falan atlamak için)
            if file_name.startswith('.'):
                continue
                
            file_path = Path(root) / file_name
            
            try:
                with file_path.open('r', encoding='utf-8') as f:
                    # Dosyadaki her bir satırı numarasıyla (enumerate) birlikte kontrol ediyoruz
                    for line_number, line in enumerate(f, 1):
                        if query in line:
                            # Bulduğumuzda dosya yolu ve satır numarasını listeye ekliyoruz
                            results.append(f"{_display_path(file_path)} (Satır {line_number}): {line.strip()}")
                            if len(results) >= MAX_SEARCH_RESULTS:
                                return "Bulunan sonuçlar (sonuç limiti uygulandı):\n" + "\n".join(results)
            except (OSError, UnicodeDecodeError):
                # Eğer dosya okunamıyorsa (örn: resim dosyasıysa) hatayı yoksayıp diğer dosyaya geç
                continue
                
    if not results:
        return f"Arama sonucu: '{query}' projedeki hiçbir dosyada bulunamadı."
        
    return "Bulunan sonuçlar:\n" + "\n".join(results)

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
    
    # Sadece tanımlamaları yakalamak için (Python ve JS/TS uyumlu basit bir regex şablonu)
    # Örn: def kelime, class kelime, function kelime, const kelime
    pattern = re.compile(
        rf'\b(?:def|class|function|const|let|var)\s+{re.escape(symbol_name)}\b',
        re.IGNORECASE,
    )
    
    for root, directories, files in os.walk(search_directory):
        directories[:] = [name for name in directories if name not in EXCLUDED_DIRECTORIES and not name.startswith(".")]
            
        for file_name in files:
            if file_name.startswith('.'):
                continue
                
            file_path = Path(root) / file_name
            
            try:
                with file_path.open('r', encoding='utf-8') as f:
                    for line_number, line in enumerate(f, 1):
                        if pattern.search(line):
                            results.append(f"{_display_path(file_path)} (Satır {line_number}): {line.strip()}")
                            if len(results) >= MAX_SEARCH_RESULTS:
                                return "Bulunan sembol tanımları (sonuç limiti uygulandı):\n" + "\n".join(results)
            except (OSError, UnicodeDecodeError):
                continue
                
    if not results:
        return f"Sembol bulunamadı: Projede '{symbol_name}' adında bir fonksiyon, sınıf veya değişken tanımı bulunamadı."
        
    return "Bulunan sembol tanımları:\n" + "\n".join(results)
