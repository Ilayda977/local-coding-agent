import ollama
import tools

# 1. KURAL: Tool schema & Tool açıklamaları
# PDF Diyor ki: "Search tool kalitesi, tool açıklamaları... projenin asıl mühendislik alanıdır."
# Neden Yaptık? Modelin bu araçları ne zaman ve nasıl kullanacağını anlaması için
# her aracın amacını JSON formatında (Schema) çok net bir şekilde yazdık.
AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "Belirtilen klasördeki dosya ve klasörleri listeler. Projede nelerin olduğunu görmek için kullanın.",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory_path": {
                        "type": "string",
                        "description": "Listelenecek klasörün yolu. Örn: '.'"
                    }
                },
                "required": ["directory_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Bir dosyanın içeriğini okur. Modelin hafızasını şişirmemek için start_line ve end_line kullanmalısınız.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Okunacak dosyanın yolu."
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "Okumaya başlanacak satır numarası (Opsiyonel ama önerilir)."
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Okumanın bitirileceği satır numarası (Opsiyonel ama önerilir)."
                    }
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Projedeki kod dosyalarında belirli bir kelimeyi veya metni arar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Aranacak kelime veya metin."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "find_symbol",
            "description": "Bir fonksiyonun (def) veya sınıfın (class) tanımlandığı asıl yeri bulur. Nokta atışı arama için bunu kullanın.",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol_name": {
                        "type": "string",
                        "description": "Aranacak fonksiyon veya sınıf adı. Örn: 'reverse_string'"
                    }
                },
                "required": ["symbol_name"]
            }
        }
    }
]

# 2. KURAL: Context engineering (Bağlam mühendisliği)
# PDF Diyor ki: "Her turda yalnızca ihtiyaç duyulan küçük dosya parçalarını modele gönder."
# Neden Yaptık? Ajanı sistemsel olarak uyarıyoruz. Ajanın hafızasını ve M3 bilgisayarının RAM'ini
# korumak için, modele "Bütün dosyayı okuma!" emrini veriyoruz.
SYSTEM_PROMPT = """
Sen uzman bir yazılım dedektifi ve kodlama ajanısın. 
Görevin, sana verilen sorunu (issue) çözmek için projeyi analiz etmektir.
Bunun için sana verilen araçları (tools) kullanmalısın.

KURALLAR (Context Engineering & Performans):
1. Bütün projeyi okumaya çalışma! Önce 'list_files' ile klasörlere bak.
2. Nereye bakacağını bilmiyorsan 'search_code' veya 'find_symbol' ile anahtar kelimeleri arat.
3. Dosyaları okurken 'read_file' aracına mutlaka start_line ve end_line vererek sadece küçük parçalar oku (örn: 10 ile 50 arası). Bütün dosyayı okumak hafızanı doldurur ve yasaktır!
4. Çözümü bulduğunda veya sorunun kaynağını anladığında arama yapmayı bırak ve bulgularını raporla.
"""

# 3. KURAL: Controller ve Agent Loop
# PDF Diyor ki: "Sistem, büyük problemi küçük kararlar dizisine dönüştürür. Uzun agent loop yok."
def run_agent(issue_text):
    print(f"\n[ISSUE ALINDI] {issue_text}\n")
    
    # Modelin hafızası (Başlangıçta sistem uyarımız ve kullanıcının görevi var)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Görev: {issue_text}\nLütfen araçlarını kullanarak bu sorunu araştır ve bulgularını paylaş."}
    ]
    
    # PDF KURALI: Uzun agent loop yok. 6-10 step gibi küçük limitlerle başlanır.
    MAX_STEPS = 8 
    
    for step in range(1, MAX_STEPS + 1):
        print(f"--- Adım {step}/{MAX_STEPS} ---")
        
        # Ollama ile Qwen 7B modeline soruyu ve kullanabileceği alet çantasını (Tools) yolluyoruz.
        response = ollama.chat(
            model='qwen2.5-coder:7b',
            messages=messages,
            tools=AGENT_TOOLS
        )
        
        message = response['message']
        messages.append(message)
        
        # 4. KURAL: Tool Calling (Araç Çağırma) ve Observation (Gözlem Geri Bildirimi)
        if message.get('tool_calls'):
            for tool_call in message['tool_calls']:
                tool_name = tool_call['function']['name']
                tool_args = tool_call['function']['arguments']
                
                print(f"[AJAN ARAÇ KULLANIYOR] -> {tool_name}({tool_args})")
                
                # Ajanın istediği aracı tools.py'den bulup çalıştırıyoruz
                if tool_name == 'list_files':
                    result = tools.list_files(**tool_args)
                elif tool_name == 'read_file':
                    result = tools.read_file(**tool_args)
                elif tool_name == 'search_code':
                    result = tools.search_code(**tool_args)
                elif tool_name == 'find_symbol':
                    result = tools.find_symbol(**tool_args)
                else:
                    result = f"HATA: {tool_name} adında bir araç bulunamadı."
                
                print(f"[ARAÇ SONUCU (Gözlem)] (100 karakter kesit): {str(result)[:100]}...\n")
                
                # OBSERVATION KURALI: Aracın sonucunu (örneğin dosya içeriğini) modele geri veriyoruz
                messages.append({
                    "role": "tool",
                    "content": result,
                    "name": tool_name
                })
                
        # Eğer ajan araç kullanmadıysa, demek ki aradığını buldu ve bize cevabı (raporu) yazıyor.
        else:
            print("[AJANIN CEVABI]:")
            print(message['content'])
            print("\n[GÖREV TAMAMLANDI]")
            break
            
    else:
        # Eğer döngü break olmadan biterse, ajan sınıra ulaşıp takılmıştır.
        print("\n[UYARI] Ajan adım sınırına ulaştı (Max Steps). İşlem otomatik durduruldu.")

if __name__ == "__main__":
    # Test için örnek bir "Issue" veriyoruz.
    ornek_gorev = "Projemizde qwen2.5-coder:7b kelimesinin hangi dosyalarda geçtiğini bulur musun? Lütfen arama yapıp sonucu söyle."
    run_agent(ornek_gorev)
