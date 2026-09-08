# Local Coding Agent

Küçük bir yerel dil modelini, tüm repository'yi context'e yüklemeden kod tabanında araştırma yapabilen güvenli bir **read-only coding agent**a dönüştürme projesi.

Bu çalışma, güçlü bir bulut modelini kopyalamayı hedeflemez. Amaç; Apple M3, 16 GB unified memory üzerinde çalışan küçük bir coding modelinin doğru tool tasarımı, context engineering ve controller guardrail'leri ile repository seviyesindeki kod görevlerinde ne kadar kullanılabilir hale getirilebileceğini ölçmektir.

## Güncel Durum: Faz 2 Devam Ediyor

**8 Eylül 2026:** Varsayılan giriş artık `repository_agent.py` içindeki sabit
istek sözleşmeli controller'dır. Hedef, girdiler/varsayımlar ve Q kimlikli sonuç
istekleri araştırma boyunca korunur. Eski aşamalı akış silinmedi;
`--legacy-staged` ile karşılaştırılabilir. Yeni mimari ve henüz doğrulanmamış
kabul durumu: [Faz 1–2 mimarisi](PHASE12_ARCHITECTURE.md).

**Aşağıdaki aşama şeması ve test sayıları önceki akışın tarihsel kaydıdır;
yeni controller'ın test veya canlı başarı sonucu değildir.**

Controller, araştırmayı açık aşamalarla yönetir. Model arama hedeflerini ve kaynak adaylarını seçer; controller gerçekten okunan koddan kanıt blokları, dosya yolları, satır aralıkları ve alıntılar üretir. Policy içinde örnek soruların cevapları veya belirli bir hedef dosyaya yönlendirme yoktur.

148 otomatik test geçmektedir; bunlar modelin görev başarısı değildir. Gerçek model denemeleri hâlâ araştırma kararı, zaman aşımı ve kod yorumlama hataları gösterebilir. Model kontrolünden geçen açıklamalar bile iç kayıtta `review_required` (insan incelemesi gereken taslak) durumunu taşır; kesin doğru cevap sayılmaz. **Faz 2 tamamlanmış değildir.** Güncel ölçümler ve sınırlamalar: [Faz 2 değerlendirme kaydı](PHASE2_STATUS.md).

Arama önce literal eşleşmeyi kullanır. Eşleşme yoksa çok sözcüklü sorgudaki
en fazla dört terimin gerçek sembol tanımları aday gösterilir; bu geri dönüş
gözlemde açıkça etiketlenir. Yine aday yoksa model listelenmiş dosyalardan seçim
yapabilir. Adayın bulunması cevap değildir; bounded okuma ve diagnosis denetimi korunur.

Güncel baseline `qwen2.5-coder:7b`; varsayılan hedef bu repository'dir.
VERIFY normal çağrıda yalnız `issues`, `supported`, `complete` üretir (512 token;
bir biçim onarımında en fazla 768). DRAFT 1024 token ile sınırlıdır. Her model
çağrısının süresi ve çıktı token sayısı terminalde gösterilir; görev toplam süre
sınırı 300 saniyedir. Kısalan çıktı henüz gerçek model hız/doğruluk ölçümü değildir.
Arama hedefleri model tarafından seçilir; soru sözcüklerinden üretilmiş zorunlu
liste yoktur. `find_symbol` Python `Class.method` tanımlarını AST ile bulabilir.

## Faz 1 Durumu: Tamamlandı

Faz 1'in hedefi, agent'ın bir issue için ilgili dosyayı kendi kararıyla bulabilmesiydi. Agent bu aşamada **dosya yazmaz**, patch uygulamaz veya test komutu çalıştırmaz; yalnızca repository'yi araştırır ve bulgularını raporlar.

Kabul kriterleri:

- Önceki Faz 1 sürümünde 5 basit issue'da ilgili kaynak dosyasını bulmak: **5/5 başarılı**; bu tarihsel sonuç güncel sürümün yeniden ölçümü değildir.
- Repository dışındaki path'leri reddetmek: **otomatik testlerle doğrulandı**
- Tüm repository'yi modele göndermemek: **satır aralıklı dosya okuma ve çıktı limitleriyle doğrulandı**

## Mimari

```text
LIST → ROUTE → SEARCH → SELECT → READ → ASSESS
                  ↑                       │
                  └── eksik bilgi ────────┘  (sınırlı araştırma)
                                          │ yeterli görülürse
                                          ↓
                              DRAFT → GROUNDING → VERIFY → RESULT
                                           │          │
                                           └─ RECOVER ┘
                                              │
                                     SEARCH veya REVISE
                                     (en fazla iki onarım)
```

| Dosya | Sorumluluk |
| --- | --- |
| `agent.py` | Route kararı, aşama sırası, araştırma/onarım bütçesi, sayısal kanıt bağlama ve sonuç durumu. |
| `protocol.py` | Her aşamanın Pydantic/JSON sözleşmesi, izinli kimlikler, okunabilir kaynak sunumu ve Ollama çağrısı. |
| `evidence.py` | Python AST ile sınırlı gövde okuma, kaynak türü politikası, sembol/çağrı zinciri, kanıt blokları ve dosya snapshot'ları. |
| `tools.py` | Dosya, tanım, referans, çağrı ve metin araması ile proje kökü sınırı. |

Her görev yeni kanıt kaydı ve yeni model mesajlarıyla başlar. Önceki soruların cevapları model oturumuna aktarılmaz. Her aşamada yalnız o karar için gerekli veri gönderilir. Dosya içerikleri talimat değil, güvenilmeyen kaynak verisi olarak işaretlenir.

## Kullanılan Araçlar

| Araç | Amaç |
| --- | --- |
| `list_files` | Proje içindeki bir klasörün dosya ve klasörlerini listeler. |
| `find_file` | Dosya içeriğini değil, açıkça istenen dosya adını veya göreli yolu arar. |
| `search_code` | Kod içinde bir kelime veya metin arar; kaynak kod sonuçlarını test sonuçlarından önce gösterir. |
| `find_symbol` | Python'da AST ile fonksiyon, sınıf ve atama tanımlarını bulur; diğer dosyalarda sınırlı regex desteği vardır. |
| `find_references` | Python AST ile bir sembolün tanımı dışındaki gerçek kullanımlarını arar. |
| `find_calls` | Python AST ile bir fonksiyon, sınıf veya metot çağrısının yapıldığı yerleri arar. |
| `find_tests` | Davranışı tartışmalı bir sembolü kullanan Python test fonksiyonlarını ikinci kanıt olarak bulur. |
| `read_file` | Bir metin dosyasından yalnızca istenen satır aralığını okur. |

## Güvenlik ve Context Guardrail'leri

- Tool'lar yalnızca `tools.py` dosyasının bulunduğu proje kökü içinde çalışır.
- Path çözümlemesi `Path.resolve()` ve `relative_to()` ile yapılır; `../` kaçışları ve benzer isimli kardeş klasörler reddedilir.
- `read_file` için başlangıç ve bitiş satırı zorunludur.
- Tek dosya okuması en fazla **80 satır** ile sınırlıdır (`MAX_READ_LINES`).
- Arama çıktısı en fazla **50 sonuç** ile sınırlıdır (`MAX_SEARCH_RESULTS`).
- `.git`, `venv` ve `__pycache__` agent discovery sürecinden çıkarılır.
- En fazla **3 araştırma turu**, **14 model çağrısı**, toplam model çağrısı bütçesi **420 saniye**; tek istek için en fazla **90 saniyelik ağ zaman aşımı** vardır. Bunlar aynı tür limitler değildir.
- Aynı arama yeniden çalıştırılmaz. Önceden okunmuş bir bloğun başka satırına denk gelen aday da tekrar okunmaz.
- AST incelemesi için dosya boyutu en fazla 1 MB; saklanan kaynak metni bütçesi 16.000 karakterdir. Karakter bütçesi, kesin token sayısı hesabı değildir.
- Tüm görevlerde aynı model ayarları kullanılır: `temperature=0`, `num_ctx=8192`, `num_predict=768`.
- Thinking varsayılan olarak kapalıdır. `LOCAL_CODING_AGENT_THINK=true` yalnız kontrollü deneyler için açar; model `LOCAL_CODING_AGENT_MODEL` ile seçilebilir.
- Model yalnız kayıtlı aday/kanıt kimliklerini seçebilir. Dosya yolu, satır aralığı ve alıntı controller tarafından oluşturulur.
- Bir iddiadaki sayı, aynı iddianın seçtiği kaynakta veya soruda yoksa taslak LLM hakeminden önce deterministik olarak reddedilir.
- VERIFY, orijinal sorunun kapsamını ve kaynakla tutarlılığı kısa sorun listesiyle denetler; aynı soruya ikinci uzun açıklama üretmez. Model onayı semantik doğruluk garantisi değildir.
- ROUTE aşaması dosya bulma, tanım bulma, referans bulma, çağrı izleme, davranış açıklama ve dokümantasyon sorularını ayırır; sorgular yalnız kullanıcı sorusu ve gerçek proje listesindeki hedeflerle sınırlandırılır.
- Proje listesi arama hedefi değildir: model soruda geçmeyen bir dosya adını tahmin edip `find_file` çalıştıramaz. Başlangıç araçları açık dosya adı, kod sembolü veya literal hedef türüne göre sınırlandırılır.
- Genel görev sözcüklerindeki tek-harf yazım hataları teknik varlıklara dokunmadan normalize edilir. Doğal dildeki `nerede`, `modeli`, `fonksiyonu` gibi sözcükler bağımsız repository sorgusuna çevrilmez; tırnak içindeki açık arama hedefleri korunur.
- Literal aramada gerçek kod satırları yorum satırlarından önce sıralanır; testler ve dokümantasyon daha düşük kaynak önceliğindedir.
- `code_only`, `code_first` ve `docs_first` kaynak politikaları README tekrarlarının runtime kodunun önüne geçmesini engeller.
- Başarısız taslakta ajan, okunmuş kod adlarından yeni bir hedef seçerek araştırmaya dönebilir. Tanım, referans ve çağrı aramaları ayrı araçlardır; araç ve hedef türü şemada birbirine bağlanır.
- Çağrı izleme rotası bir literal/ayar değerini atandığı sembole, oradan kullanıldığı constructor veya fonksiyona ve sınıf içindeki terminal çağrıya kadar sınırlı AST veri akışıyla takip eder.
- Okunmuş dosyada import edilen Python standart kütüphane modülleri repository bağımlılığı gibi aranmaz.
- Bir callable davranışı ASSESS aşamasında kesinleşmezse veya VERIFY tarafından reddedilirse ve repository'de ilgili test varsa, test fonksiyonu ikincil kanıt olarak okunur; uygulama kodu birincil kaynak kalır.
- Yeni kanıt geldikten sonra önceki hatalı model yorumu yeni taslağa gerçekmiş gibi taşınmaz; yapılmış aramalar da tekrar önerilmez.
- Tek bir geçici yerel-model zaman aşımı aynı aşamada bir kez yeniden denenir; ikinci hata güvenli biçimde görevi durdurur.
- Açık bir dosya `find_file` ile bulunup okunduğunda `locate_file` rotası dosyanın içindeki her ismi yeni bir repository aramasına dönüştürmez; mevcut blok veya sınırlı devam adayı değerlendirilir.
- Dosya değişirse farklı sürümlerin kanıtları karıştırılmaz; cevap öncesi hash kontrolü tekrar yapılır.
- Kaynak doğrulaması, açıklamanın anlamsal doğruluğunu ispatlamaz. İkinci model kontrolü de yanılabildiği için sonuç taslaktır.

Satır limiti, modele döndürülen aralığı sınırlar. `read_file` içinde dosya hâlen `readlines()` ile okunur; bu limit bütün dosyanın RAM'e yüklenmesini engelleyen bir mekanizma değildir.

## Yerel Model Uyumluluğu

Faz 1'de native tool calling ve metne yazılmış JSON çağrıları birlikte işleniyordu. Güncel controller bu serbest döngüyü kullanmaz: model her aşama için küçük bir JSON kararı üretir, controller izin verilen gerçek aracı çalıştırır.

Şema Ollama'ya `format` parametresiyle verilir ve gelen veri Python tarafında tekrar doğrulanır. Şema dışı çıktı için yalnız bir yeniden deneme vardır. Bu yaklaşımın API dayanağı: [Ollama structured outputs dokümantasyonu](https://docs.ollama.com/capabilities/structured-outputs). Şema uyumu, cevabın doğruluğu anlamına gelmez.

## Faz 1 Evaluation Özeti

| Issue | Retrieval sonucu | Not |
| --- | --- | --- |
| `PROJECT_ROOT` tanımını bul | `tools.py`, satır 7 | Başarılı |
| `find_symbol` tanımını bul | `tools.py`, satır 112 | Başarılı |
| `MAX_READ_LINES` limitini bul | `tools.py`, değer 80 | Kaynak dosya doğru bulundu; ilk açıklamada diagnosis hatası görüldü |
| `search_code` tanımını bul | `tools.py`, satır 112 | Başarılı |
| `MAX_SEARCH_RESULTS` değerini bul | `tools.py`, değer 50 | Başarılı |

Bu değerlendirme sonucu Faz 1'in retrieval kriteri 5/5 sağlandı. `MAX_READ_LINES` sorusundaki yanlış ara açıklama özellikle saklandı; Faz 2'deki evidence-grounded diagnosis ve failure analysis çalışmaları için bir örnektir.

Bu tablo tarihsel kayıttır; satır numaraları o sürüme aittir, güncel dosyalarda farklı olabilir. Retrieval başarısı ile doğru ve eksiksiz açıklama üretme başarısı ayrı ölçümlerdir.

## Otomatik Testler

Faz 1 sonunda 13 test vardı. Güncel test sayısı 129'dur. Model yanıtları otomatik controller testlerinde taklit edilir; gerçek model değerlendirmesi ayrı tutulur. Testler şunları kapsar:

- Proje kökünün doğru belirlenmesi
- Repository dışı path reddi
- Benzer isimli sibling-directory kaçışının engellenmesi
- Satır aralığı ve 80 satır limitinin zorlanması
- Arama sonuçlarında kaynak kodun test dosyalarından önce gelmesi
- Regex karakterleri içeren sembol aramalarının güvenliği
- Aşama şemaları, kayıt dışı kimlik reddi, bozuk/kesilmiş JSON ve zaman aşımı
- Dosya adı, tanım, referans ve çağrı araçlarının birbirinden ayrılması
- Router sorgularının soru/proje listesiyle sınırlandırılması ve kaynak türü politikaları
- Yazım hatalı görev sözcüklerinin normalize edilmesi, arama gürültüsünün ayıklanması ve tırnak içi hedeflerin korunması
- Çağrı zincirinde tanım, referans ve çağrı araçlarından hedefe uygun tek aracın seçilmesi
- Standart kütüphane importlarının dependency aramasından çıkarılması ve test fonksiyonlarının ikincil davranış kanıtı olarak bulunması
- Literal → değişken → constructor/fonksiyon → terminal çağrı kanıt zinciri
- Açık dosya incelemesinin gereksiz sembol aramalarına genişlememesi
- Tam fonksiyon gövdesi, sınırlı devam okuması, gerçek satır sınırları ve snapshot tutarlılığı
- Farklı dosya, sembol ve değerlerde gerçek kaynak alıntıları
- Modelin kaynak seçimini koruma; ilgisiz sabitleri zorunlu takip etmeme
- Okunmuş bloklara yeniden denk gelen arama sonuçlarında ek okuma yapmama
- Kaynak kodunu model mesajında gerçek girinti ve satırlarla sunma
- Sınırlı `VERIFY → RECOVER → SEARCH/REVISE` akışı; uydurma sayıları reddetme; soru-alt-istek checklist'i; model onayını kesin başarı saymama

Testleri çalıştırmak için:

```bash
PYTHONDONTWRITEBYTECODE=1 ./venv/bin/python -m unittest discover -v
```

## Geliştirme Ortamı

- Donanım: Apple M3 MacBook, 16 GB Unified Memory
- Local inference: Ollama
- Varsayılan/baseline model: `qwen2.5-coder:7b`
- Değerlendirilen yeni aday: `qwen3.5:9b` (`Q4_K_M`, thinking varsayılan kapalı)
- Hızlı baseline: `qwen2.5-coder:3b`
- Dil: Python

Model performansına dair başlangıç gözlemleri [MODEL_BASELINE.md](MODEL_BASELINE.md) dosyasında bulunur.

Yerel geliştirme ortamında Ollama açık olmalıdır. Uygulama zaten çalışıyorsa ayrıca ikinci bir `ollama serve` başlatmak gerekmez:

```bash
./venv/bin/python agent.py "search_code fonksiyonunun nerede tanımlandığını bul."
```

Modeli kodu değiştirmeden seçmek için:

```bash
env LOCAL_CODING_AGENT_MODEL=qwen3.5:9b ./venv/bin/python agent.py "soru"
```

Thinking normalde kapalıdır. Yalnız kontrollü bir deneyde açmak için
`LOCAL_CODING_AGENT_THINK=true` kullanılabilir.

## Faz 2 Hedefi ve Mevcut Sınır

Faz 2'de agent yalnızca doğru dosyayı bulmakla yetinmemeli. Güncel sonuç kaydı aşağıdaki alanları taşır:

```text
status
question
findings[]: answer + evidence[] (block_id, file, start_line, end_line, quote)
reason
```

`review_required`: kaynak kaydı doğrulanmış, model kontrolünden geçmiş fakat insan incelemesi gereken taslak. Cevap üretildiği için CLI çıkış kodu **0**'dır; ekrandaki not insan incelemesini hatırlatır ve kesin doğruluk iddiası taşımaz.

`insufficient_evidence`, `budget_exhausted`, `stopped`: tamamlanamayan araştırma; başarılı cevap sunulmaz. CLI çıkış kodu **1**'dir. Python API sonucunda aşama/araç/model izleri de tutulur.

Varsayılan terminal çıktısı kaynak kodunun tamamını dökmez; sonuç, kısa kanıt konumları ve çalışma özeti gösterilir. Alıntılar dahil makine-okunur ayrıntı gerektiğinde `--json` kullanılabilir:

```bash
./venv/bin/python agent.py --json "MODEL_NAME nerede tanımlı?"
```

Modelin kendi söylediği `confidence` artık güvenilirlik ölçüsü olarak kullanılmaz. Araştırma kalitesi, protokole uyum, kaynak doğruluğu ve anlamsal doğruluk farklı sorularda ayrı ölçülmelidir. Faz 3'te kullanıcı onayıyla safe patch, Faz 4'te allowlist tabanlı test feedback loop planlanmaktadır.
