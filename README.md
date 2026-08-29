# Local Coding Agent

Küçük bir yerel dil modelini, tüm repository'yi context'e yüklemeden kod tabanında araştırma yapabilen güvenli bir **read-only coding agent**a dönüştürme projesi.

Bu çalışma, güçlü bir bulut modelini kopyalamayı hedeflemez. Amaç; Apple M3, 16 GB unified memory üzerinde çalışan küçük bir coding modelinin doğru tool tasarımı, context engineering ve controller guardrail'leri ile repository seviyesindeki kod görevlerinde ne kadar kullanılabilir hale getirilebileceğini ölçmektir.

## Faz 1 Durumu: Tamamlandı

Faz 1'in hedefi, agent'ın bir issue için ilgili dosyayı kendi kararıyla bulabilmesiydi. Agent bu aşamada **dosya yazmaz**, patch uygulamaz veya test komutu çalıştırmaz; yalnızca repository'yi araştırır ve bulgularını raporlar.

Kabul kriterleri:

- 5 basit issue'da ilgili kaynak dosyasını bulmak: **5/5 başarılı**
- Repository dışındaki path'leri reddetmek: **otomatik testlerle doğrulandı**
- Tüm repository'yi modele göndermemek: **satır aralıklı dosya okuma ve çıktı limitleriyle doğrulandı**

## Mimari

```text
Issue
  ↓
Controller (agent.py)
  ↓
Yerel model: Qwen2.5-Coder 7B / Ollama
  ↓
list_files | search_code | find_symbol | read_file
  ↓
Küçük observation
  ↓
Model: sonraki tool çağrısı veya bulgu raporu
```

`agent.py` controller'dır: modelin mesaj geçmişini, tool çağrılarını ve maksimum agent adımını yönetir. `tools.py` ise modelin kullanabildiği read-only araçları ve güvenlik sınırlarını uygular.

## Kullanılan Araçlar

| Araç | Amaç |
| --- | --- |
| `list_files` | Proje içindeki bir klasörün dosya ve klasörlerini listeler. |
| `search_code` | Kod içinde bir kelime veya metin arar; kaynak kod sonuçlarını test sonuçlarından önce gösterir. |
| `find_symbol` | Fonksiyon, class veya değişken tanımının bulunduğu yeri arar. |
| `read_file` | Bir metin dosyasından yalnızca istenen satır aralığını okur. |

## Güvenlik ve Context Guardrail'leri

- Tool'lar yalnızca `tools.py` dosyasının bulunduğu proje kökü içinde çalışır.
- Path çözümlemesi `Path.resolve()` ve `relative_to()` ile yapılır; `../` kaçışları ve benzer isimli kardeş klasörler reddedilir.
- `read_file` için başlangıç ve bitiş satırı zorunludur.
- Tek dosya okuması en fazla **80 satır** ile sınırlıdır (`MAX_READ_LINES`).
- Arama çıktısı en fazla **50 sonuç** ile sınırlıdır (`MAX_SEARCH_RESULTS`).
- `.git`, `venv` ve `__pycache__` agent discovery sürecinden çıkarılır.
- Agent en fazla **8 adım** çalışır (`MAX_STEPS`).
- Aynı tool ve aynı parametrelerle yapılan tekrar çağrıları read-only modda engellenir.

## Yerel Model Uyumluluğu

Qwen2.5-Coder 7B bazı tool çağrılarını Ollama'nın native `tool_calls` alanı yerine JSON metni veya Markdown JSON kod bloğu olarak üretebildi. Controller bu üç biçimi de güvenli şekilde işler:

1. Native Ollama tool call
2. Düz JSON: `{"name": "search_code", "arguments": {...}}`
3. Markdown kod bloğu içindeki geçerli JSON

Bu fallback yalnızca `name` alanı string ve `arguments` alanı object olduğunda devreye girer. Diğer metinler final cevap olarak değerlendirilir.

## Faz 1 Evaluation Özeti

| Issue | Retrieval sonucu | Not |
| --- | --- | --- |
| `PROJECT_ROOT` tanımını bul | `tools.py`, satır 7 | Başarılı |
| `find_symbol` tanımını bul | `tools.py`, satır 112 | Başarılı |
| `MAX_READ_LINES` limitini bul | `tools.py`, değer 80 | Kaynak dosya doğru bulundu; ilk açıklamada diagnosis hatası görüldü |
| `search_code` tanımını bul | `tools.py`, satır 112 | Başarılı |
| `MAX_SEARCH_RESULTS` değerini bul | `tools.py`, değer 50 | Başarılı |

Bu değerlendirme sonucu Faz 1'in retrieval kriteri 5/5 sağlandı. `MAX_READ_LINES` sorusundaki yanlış ara açıklama özellikle saklandı; Faz 2'deki evidence-grounded diagnosis ve failure analysis çalışmaları için bir örnektir.

## Otomatik Testler

Faz 1 sonunda 13 test geçmektedir. Testler şunları kapsar:

- Proje kökünün doğru belirlenmesi
- Repository dışı path reddi
- Benzer isimli sibling-directory kaçışının engellenmesi
- Satır aralığı ve 80 satır limitinin zorlanması
- Arama sonuçlarında kaynak kodun test dosyalarından önce gelmesi
- Regex karakterleri içeren sembol aramalarının güvenliği
- Native, düz JSON ve Markdown JSON tool-call uyumluluğu

Testleri çalıştırmak için:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python -m unittest discover -v
```

## Geliştirme Ortamı

- Donanım: Apple M3 MacBook, 16 GB Unified Memory
- Local inference: Ollama
- Ana model: `qwen2.5-coder:7b`
- Hızlı baseline: `qwen2.5-coder:3b`
- Dil: Python

Model performansına dair başlangıç gözlemleri [MODEL_BASELINE.md](MODEL_BASELINE.md) dosyasında bulunur.

Yerel geliştirme ortamında agentı başlatmak için Ollama'nın açık olması gerekir:

```bash
ollama serve
./venv/bin/python agent.py "search_code fonksiyonunun nerede tanımlandığını bul."
```

## Faz 2'ye Geçiş

Bir sonraki aşamada agent yalnızca doğru dosyayı bulmakla yetinmeyecek. Her diagnosis şu yapı ile üretilecek:

```text
issue_summary
evidence
root_cause
relevant_files
confidence
```

Bu sayede agentın doğru görünen ama kanıtsız veya yanlış açıklamaları ölçülebilir hale gelecek. Faz 3'te kullanıcı onayıyla safe patch, Faz 4'te allowlist tabanlı test feedback loop eklenecek.
