import os
import re

# Ajanın dışarı çıkmasını engellemek için projenin ana klasörünün tam yolunu alıyoruz.
# os.path.abspath('.') komutu, kodun çalıştığı klasörün (local-coding-agent) tam yolunu verir.
PROJECT_ROOT = os.path.abspath('.')

def _is_safe_path(target_path):
    """
    Güvenlik Kontrolü (Filesystem Boundary):
    Ajanın verdiği yolun, bizim belirlediğimiz proje klasörünün içinde kalıp kalmadığını kontrol eder.
    Böylece ajan gidip Masaüstü'nü veya sistem dosyalarını okuyamaz.
    """
    # Gelen yolu tam ve mutlak (absolute) yola çevir
    absolute_target_path = os.path.abspath(target_path)
    
    # Eğer oluşturulan mutlak yol, bizim ana projemizin yolu ile başlıyorsa güvenlidir.
    return absolute_target_path.startswith(PROJECT_ROOT)


def list_files(directory_path="."):
    """
    Belirtilen klasördeki dosya ve klasörlerin isimlerini listeler.
    Ajan projede nelerin olduğunu görmek için bunu kullanacak.
    """
    if not _is_safe_path(directory_path):
        return "HATA: Güvenlik ihlali! Proje ana klasörü dışındaki bir dizini listeleyemezsiniz."
    
    try:
        # os.listdir klasördeki dosyaları liste halinde verir
        files = os.listdir(directory_path)
        
        # Git klasörü, sanal ortam gibi gereksiz veya gizli dosyaları gizleyelim ki ajanın kafası karışmasın
        safe_files = [f for f in files if not f.startswith('.') and f != "venv" and f != "__pycache__"]
        
        return f"{directory_path} içindeki dosyalar:\n" + "\n".join(safe_files)
    
    except FileNotFoundError:
        return f"HATA: {directory_path} adında bir klasör bulunamadı."
    except Exception as e:
        return f"HATA: Klasör listelenirken bir sorun oluştu: {str(e)}"


def read_file(file_path, start_line=None, end_line=None):
    """
    Belirtilen dosyanın içeriğini okur. 
    Eğer start_line ve end_line verilirse, sadece o satırlar arasını okur.
    Bu, Context Length (Hafıza) sınırını aşmamak için çok önemlidir.
    """
    if not _is_safe_path(file_path):
        return "HATA: Güvenlik ihlali! Proje ana klasörü dışındaki bir dosyayı okuyamazsınız."
    
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            lines = file.readlines()
            
        # Eğer ajan satır numarası vermediyse tüm dosyayı göster, verdiyse sadece o aralığı kes.
        # Python'da listeler 0'dan başladığı için satır numaralarından 1 çıkarıyoruz.
        if start_line is not None and end_line is not None:
            # Örn: start_line=5, end_line=10 ise -> lines[4:10] (5. satırdan 10. satıra kadar)
            lines = lines[start_line-1 : end_line]
            
        return "".join(lines)
        
    except FileNotFoundError:
        return f"HATA: {file_path} adında bir dosya bulunamadı."
    except Exception as e:
        return f"HATA: Dosya okunurken bir sorun oluştu: {str(e)}"

def search_code(query, directory="."):
    """
    Projedeki tüm Python, JS vb. kaynak kod dosyalarının içinde belirli bir kelimeyi/kodu arar.
    Örn: search_code('def reverse_string') -> Bu fonksiyonun hangi dosyada geçtiğini bulur.
    """
    if not _is_safe_path(directory):
        return "HATA: Güvenlik ihlali! Proje ana klasörü dışında arama yapamazsınız."
    
    results = []
    
    # os.walk klasörlerin içine girerek tüm dosyaları sırayla gezmemizi sağlar
    for root, _, files in os.walk(directory):
        # Eğer şu anki klasör gizli bir klasörse veya venv ise onu atla (hız için)
        if '.git' in root or 'venv' in root or '__pycache__' in root:
            continue
            
        for file_name in files:
            # Sadece uzantısı olan text/kod dosyalarında arama yapalım (resim dosyalarını falan atlamak için)
            if file_name.startswith('.'):
                continue
                
            file_path = os.path.join(root, file_name)
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    # Dosyadaki her bir satırı numarasıyla (enumerate) birlikte kontrol ediyoruz
                    for line_number, line in enumerate(f, 1):
                        if query in line:
                            # Bulduğumuzda dosya yolu ve satır numarasını listeye ekliyoruz
                            results.append(f"{file_path} (Satır {line_number}): {line.strip()}")
            except Exception:
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
    if not _is_safe_path(directory):
        return "HATA: Güvenlik ihlali! Proje ana klasörü dışında arama yapamazsınız."
        
    results = []
    
    # Sadece tanımlamaları yakalamak için (Python ve JS/TS uyumlu basit bir regex şablonu)
    # Örn: def kelime, class kelime, function kelime, const kelime
    pattern = re.compile(rf'\b(?:def|class|function|const|let|var)\s+{symbol_name}\b', re.IGNORECASE)
    
    for root, _, files in os.walk(directory):
        if '.git' in root or 'venv' in root or '__pycache__' in root:
            continue
            
        for file_name in files:
            if file_name.startswith('.'):
                continue
                
            file_path = os.path.join(root, file_name)
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    for line_number, line in enumerate(f, 1):
                        if pattern.search(line):
                            results.append(f"{file_path} (Satır {line_number}): {line.strip()}")
            except Exception:
                continue
                
    if not results:
        return f"Sembol bulunamadı: Projede '{symbol_name}' adında bir fonksiyon, sınıf veya değişken tanımı bulunamadı."
        
    return "Bulunan sembol tanımları:\n" + "\n".join(results)
