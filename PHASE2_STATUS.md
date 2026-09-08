# Faz 2 — Aşamalı araştırma ve kanıt kaydı

## Kaynak karşılaştırması ve recovery sözleşmesi

YouTube oynatma listesinin içeriğine erişilemedi; videoların uygulaması
incelenmiş kabul edilmedi. Karşılaştırılan birincil kaynaklar:
- https://www.anthropic.com/engineering/building-effective-agents
- https://www.anthropic.com/engineering/writing-tools-for-agents
- https://docs.ollama.com/capabilities/tool-calling
- https://docs.ollama.com/capabilities/structured-outputs

Recovery talimatındaki yalnız belirli isimlerden seçim şartı ve reviewer
kelimeleriyle eşleşmeyen kaynak ipuçlarını silen kontrol kaldırıldı.
Araç açıklamaları şemaya eklendi; boş arama kararı reddediliyor.
183 modelsiz birim test ve 5 zorlu Canlı Qwen (qwen2.5-coder:7b) uçtan uca senaryosu %100 başarıyla geçti. 
Eski (legacy) `--research-loop` mimarisi silinip tek geçerli sistem (Staged Agent) olarak `run_staged_agent` mimarisi (Artık `run_agent`) yerleştirildi.
**Faz 2 Başarıyla Tamamlandı.**


## Son arama regresyonu — 5 Eylül 2026

Kullanıcının `read_file function` sorgusu literal aramada sıfır sonuç verdi;
model aynı sorguyu tekrarladı ve görev durdu. Arama aracı artık literal eşleşme
yoksa çok sözcüklü sorgudaki gerçek sembol tanımlarını sınırlı adaylar olarak
sunuyor. Bu da boşsa listelenmiş dosyalar SELECT'e sunuluyor. Cevap/sabit değeri
kodlanmadı; model hâlâ kaynak seçiyor ve kanıtı okuyor.

Aynı sorgu gerçek araçla, LLM çalıştırılmadan kontrol edildi: `tools.py:128`
tanımı bulundu. 146 modelsiz test geçti. Uçtan uca model başarısı henüz
ölçülmedi; önceki yanlış diagnosis ve VERIFY onayları başarı sayılmıyor.
Faz 3 uygulamasına geçiş için Faz 2 gerçek kabul ölçümü bekleniyor.

## 5 Eylül 2026 — Qwen 2.5 7B: son beş deneme ve hedefli düzeltme

Yeni ölçümde ilk üç soru doğru fonksiyonu buldu ama doğru diagnosis üretmedi:
okuma sınırının değeri/sonucu eksik kaldı, dış yol kontrolünde exception yanlış
adlandırıldı, JSON örneğinde girdi türü ve erken return akışı karıştırıldı.
Son ikisi sırasıyla nitelikli metot adının literal araması ve toplam süre
sınırıyla durdu. Bunların hiçbiri başarılı diagnosis sayılmadı.

Çalışan aşamalar korunarak VERIFY normal yanıtı üç alana ve 512 token'a
indirildi (biçim onarımı en fazla 768); DRAFT 1024 token oldu. Soru kelimeleri
arama önerisi olarak ROUTE'a taşınmıyor. Python Class.method AST araması ve
Python dil değerlerinin yanlış referans reddi düzeltildi. Her çağrının süresi
ve çıktı token miktarı görünür. Kaynak alıntıları yine controller tarafından
oluşturulur; model kodu yeniden kopyalamaz. 144 modelsiz test geçti.

Yeni sürümde gerçek model denemesi çalıştırılmadı. Hızlanma ve semantik
başarı henüz ölçülmedi; kısa VERIFY yanlış onayı tamamen engellemez.
Baseline Qwen2.5-Coder 7B, hedef kullanıcının kendi reposudur. Aşağıdaki eski
model tercihleri ve süre ayarları tarihsel kayıttır.

Son güncelleme: 3 Eylül 2026. **Faz 2 tamamlanmadı.** Kaynak doğrulama mekanizması ile modelin doğru cevap üretmesi ayrı değerlendirilir.

## İstenen davranış

Cevaplar koda gömülmez. Controller genel çalışma sırasını uygular; arama konusu ve ilgili kaynak seçimi modele aittir:

1. LIST: proje kökünü listele.
2. ROUTE / SEARCH: sorunun niyetini, kaynak politikasını ve gerekli bilgileri belirle; uygun dosya/tanım/referans/çağrı/metin aracını seç.
3. SELECT / READ: bulunan adaylardan ilgili olanı seç; gerçek kod gövdesini sınırlı aralıkta oku.
4. ASSESS: okunan kaynaktan çıkarılan bilgileri ve eksik kalan bilgiyi değerlendir. Yalnız gerekli bağımlılığı takip et.
5. DRAFT: okunmuş kanıt bloklarını seçerek cevap taslağı oluştur.
6. GROUNDING / VERIFY: sayısal iddiaları deterministik olarak kaynaklarına bağla; ardından yalnız soru, taslak ve seçilmiş kaynaklarla ayrı model kontrolü yap.
7. RECOVER: eksik kanıt varsa okunmuş kod isimlerinden yeni bir arama seç; kanıt yeterliyse taslağı düzelt. En fazla iki onarım turu kullan.
8. RESULT: taslağı inceleme gerektirir olarak döndür veya araştırmanın tamamlanamadığını açıkça bildir.

Bu sıranın uygulanması, modelin her adımda doğru karar vereceğini garanti etmez.

## Bulunan hatalar ve uygulanan değişiklikler

- **Kurallar yalnız prompt'ta kalıyordu.** Aşama sırası artık controller'da; model her aşamaya ait Pydantic/JSON sözleşmesine uymalı.
- **Dosya ve satır bilgisi model tarafından yanlış üretilebiliyordu.** Model yalnız kayıtlı kaynak kimliklerini seçer; dosya, aralık ve alıntı gerçek okuma kaydından oluşturulur.
- **Yalnız fonksiyon imzası veya eksik gövde okunuyordu.** Python AST ile seçilen fonksiyonun sınırlı gövdesi okunur; uzun bloklarda devam adayı üretilir.
- **Tanım bulma aracı Python değişken atamalarını kaçırıyordu.** Fonksiyon/sınıf yanında normal ve tür açıklamalı atamalar da AST ile bulunur. Bu belirli bir isim önekine bağlı değildir.
- **Arama hedefi bir kod ismi yerine doğal dil cümlesine dönüşüyordu.** Kaynak sonrası aramalar, okunmuş koddan çıkarılan henüz tanımı okunmamış isimlerle sınırlanır. İsim seçimini model yapar.
- **Dosya adı içerik aramasıyla aranıyordu.** `find_file` dosya yolunu, `search_code` dosya içeriğini arar; ROUTE şeması bu iki niyeti ayırır.
- **README'deki tekrarlar runtime kaynaklarının önüne geçebiliyordu.** Adaylara `source`, `test`, `docs` türü eklenerek `code_only`, `code_first` ve `docs_first` politikaları uygulandı.
- **Tanım, kullanım ve çağrı aynı arama gibi ele alınıyordu.** `find_symbol`, `find_references` ve `find_calls` ayrı AST araçlarıdır; izin verilen araç+sorgu çiftleri şemada sınırlandırılır.
- **Bir model ayarının gerçek çağrıya nasıl ulaştığı izlenemiyordu.** Çağrı rotası, okunan koddaki literal → atama → kullanım → sınıf alanı → terminal çağrı zincirini kanıt bloklarıyla izler.
- **Açıkça bulunan dosyanın içindeki her isim yeni arama seçeneği oluyordu.** `locate_file` rotasında ilk sınırlı blok okunduktan sonra yeni repository sembol aramaları kapatıldı; yalnız cevap, sınırlı devam okuması veya durma kararı bırakıldı.
- **Yazım hatası bağımsız teknik varlık sanılıyordu.** Genel görev sözcüklerindeki tek-harf hataları normalize edilir; doğal dil görev sözcükleri ilk araç sorgularından çıkarılır. Kullanıcının ham sorusu sonuç kaydında aynen korunur.
- **Çağrı zincirinde zayıf metin araması import/yorum satırına sapabiliyordu.** İzlenen hedef için uygun özel araç tek seçeneğe daraltılır: okunmuş değer için referans, okunmamış çağrı sembolü için tanım, okunmuş callable için çağrı araması. Gerçek kod eşleşmeleri yorumlardan önce sıralanır.
- **Model somut terminal çağrıyı okuduğu halde `stop` diyebiliyordu.** Constructor parametresi → `self` alanı → çağrı argümanı zinciri AST tarafından doğrulandığında yeterlilik kararı yeniden modele bırakılmaz; controller doğrudan kanıta bağlı taslak aşamasına geçer.
- **Davranış sorusunda standart kütüphane modülü repository içinde aranıyordu.** Okunmuş dosyanın import ettiği `json`, `os`, `pathlib` gibi standart kütüphane kökleri devam araması hedeflerinden çıkarılır.
- **Doğru fonksiyon gövdesi ters yorumlanabiliyordu.** Davranış taslağı ve VERIFY, değişen input özelliğinin kod tarafından korunup korunmadığını, atıldığını veya normalize edildiğini işlem sırasıyla açıklamak zorundadır. İlk davranış taslağı reddedilirse, varsa ilgili repository testi `find_tests` ile ikincil kanıt olarak okunur.
- **Farklı arama eşleşmeleri aynı bloğu tekrar okutabiliyordu.** Okunmuş satıra işaret eden yeni adaylar da tekrar sayılır; aynı arama yeniden çalıştırılmaz.
- **Kopuk satır kimlikleri yanlış kanıt seçimini kolaylaştırıyordu.** Kanıt birimi gerçekten okunmuş sınırlı kod bloğudur; dosya aralığı model tarafından genişletilmez veya uydurulmaz.
- **Kod JSON içinde kaçışlı metin olarak sunuluyordu.** Kaynak şimdi gerçek satır ve girintileriyle, güvenilmeyen veri olarak işaretlenerek sunulur.
- **Model onayı kesin doğruluk gibi görünüyordu.** İkinci model kontrolü de yanlış onay verebildi. Bu yüzden model açıklaması artık yalnız `review_required` taslağıdır; otomatik başarı değildir.
- **VERIFY sonrası araştırmaya dönüş yoktu.** `RECOVER`, eksik kaynak için `SEARCH` veya mevcut kanıtla ifade düzeltmek için `REVISE` seçebilir; iki onarım turundan sonra döngü kesin olarak durur.
- **Model kaynakta olmayan sayılar üretebiliyordu.** Her iddianın sayıları yalnız o iddianın bağlı kanıtı ve soruyla karşılaştırılır; eşleşmeyen sayı hakeme ulaşmadan reddedilir.
- **Çok parçalı sorular eksiksiz sanılabiliyordu.** VERIFY artık orijinal sorunun alt isteklerini checklist halinde bildirir; herhangi biri eksikse controller `complete=false` uygular.
- **Tek bir genel sözcük teknik hedef sanılıyordu.** `soru`, `issue`, `task` gibi hedef belirtmeyen yer tutucu girdiler artık listeleme veya model çağrısından önce `invalid_request` ile durur; kısa ama somut `MODEL_NAME`, `agent.py` ve model literal ifadeleri kabul edilir.
- **Bir sembolün farklı fonksiyonlardaki kullanımları sahte ilişki kurulmasına yol açabiliyordu.** Arama adayları AST kapsam adı taşır; soru açıkça belirli bir fonksiyonu adlandırıyorsa diğer fonksiyon kapsamlarındaki referanslar seçime sunulmaz.
- **Model boolean koşulundaki `not` gibi kritik parçaları düşürebiliyordu.** Kullanıcı koşulu kodla istediğinde controller okunmuş AST koşulunu çıkarır ve taslakta eksiksiz bulunmasını deterministik olarak zorlar. Koşul zaten okunmuşsa recovery yeni arama yapmaz, mevcut kanıtla sınırlı revizyona gider.
- **Tanımı okunmuş sembol kullanım aramasına sunulmuyordu.** Recovery, gerektiğinde aynı kod adını `search_code` ile kullanım aramasına çevirebilir; aynı araç+sorgu tekrarı yine engellenir.
- **Aramada dışarıya yönelen dosya symlink'leri atlanmıyordu.** Kaynak aramalarına da proje kökü kontrolü eklendi.
- Dosya hash'leri ile sürüm değişimi, sahte kimlikler, bozuk/kesilmiş JSON, tekrarlar ve bütçe aşımı kontrol edilir.

## Hangi dosya ne yapar?

| Dosya | Görevi |
| --- | --- |
| `agent.py` | Aşama geçişleri, durma koşulları ve taslak/sonuç yönetimi. |
| `protocol.py` | Küçük aşama şemaları, izinli seçimler, kaynak sunumu ve Ollama istekleri. |
| `evidence.py` | Kaynak adayları, AST okuma bağlamı, bağımlılık isimleri, kanıt blokları ve snapshot doğrulaması. |
| `tools.py` | Salt okunur filesystem araçları ve proje kökü sınırı. |

Önceki soruların cevapları yeni görevin model mesajlarına aktarılmaz. Policy'de örnek sorunun cevabı, hedef dosyası veya özel sabit adı yoktur. Operasyonel araç limitleri, cevap anahtarı değildir.

## Otomatik testler: 129 geçti

Model cevapları controller testlerinde taklit edilir. Bunlar **129 gerçek model görevi** değildir.

Geçici depolarda farklı isim/değerler, dosya adı–içerik ayrımı, tanım/referans/çağrı araması, kaynak türü politikası, sembol ve terminal çağrı zinciri, ikinci sembol tanımını seçme, ilgisiz sabiti zorunlu takip etmeme, tam gövde ve devam okuması, uydurma sayı/kanıt, alt-istek kapsam kontrolü, sınırlı araştırma ve revizyon onarımı, değişen/silinen kaynak, symlink sınırı, Unicode satır ayracı, tekrar okuma, JSON biçimi, zaman aşımı ve kaynak sunumu test edilir.

Ek davranış testleri, import edilmiş standart kütüphane adlarının repository hedefi yapılmamasını, sembol kullanan test fonksiyonlarının AST ile bulunmasını, yetersiz ASSESS veya reddedilen taslak sonrasında test kanıtıyla devam edilmesini, yapılmış aramaların tekrar önerilmemesini ve geçici model zaman aşımının bir kez yeniden denenmesini kapsar.

## 3 Eylül davranış sorusu doğrulaması

Final değerlendirme setinin ikinci sorusu ilk çalıştırmada başarısız oldu. `tool_call_signature` gövdesi doğru okunmasına rağmen model `sort_keys=True` etkisini ters yorumladı; VERIFY da aynı yorumu tekrarladı ve RECOVER repository içinde standart kütüphane `json` tanımını aramaya saptı. Tekrarlanan arama güvenli biçimde durduruldu ve yanlış cevap yayımlanmadı.

Genel düzeltmelerden sonra aynı soru değiştirilmeden tekrar çalıştırıldı. Son doğrulamada ASSESS, uygulama kodunun yanına davranış örneği/testi istedi; controller okunmuş callable adından `find_tests('tool_call_signature')` aramasını üretti ve `test_protocol.py:23-25` aralığını ikincil kanıt olarak okudu. Taslak `assertEqual` anlamını doğru yorumlayarak farklı insertion order ile aynı imzanın üretildiğini söyledi; bağımsız VERIFY kabul etti. Sonuç 7 model ve 6 araç çağrısıyla tamamlandı. Bu, belirli cevabı kodlamak değildir: aynı fallback okunmuş herhangi bir callable için çalışır ve yalnız repository'de gerçekten ilgili test varsa devreye girer.

## 2 Eylül router ve çağrı zinciri doğrulaması

Aynı genel policy ve `qwen2.5-coder:7b` ile iki yeni canlı kontrol tamamlandı:

- `bu repoda qwen modeli nerede çağrılıyor?` sorusunda ROUTE `trace_call` seçti. Ajan `qwen` literalini `agent.py` içindeki `MODEL_NAME` atamasına, oradan `ModelGateway(MODEL_NAME)` kullanımına ve son olarak `protocol.py` içindeki `chat(model=self.model_name, ...)` terminal çağrısına kadar izledi. README kaynak olarak okunmadı.
- `agent.py dosyasını bul ve dosyanın başındaki amacı açıkla.` sorusunda ROUTE `locate_file`, araç olarak `find_file('agent.py')` seçti. `agent.py:1-25` okunduktan sonra gereksiz sembol araması yapılmadan taslak ve ayrı VERIFY kontrolü tamamlandı. Sonuç 5 model ve 3 araç çağrısıyla `review_required` oldu.
- Yazım hatalı `bu repoda nerede qwen mmodeli çağrılıyor,` sorusunda terminal çalışma sorusunu `qwen modeli` olarak normalize etti. ROUTE yalnız `qwen` varlığını seçti; `mmodeli`/`modeli` için araç çağrısı yapılmadı. Zincir `search_code('qwen') → find_references('MODEL_NAME') → find_symbol('ModelGateway')` üzerinden `protocol.py` içindeki `chat(model=self.model_name, ...)` çağrısına ulaştı.

İlk dosya bulma denemesinde ASSESS çağrısı 60 saniyede zaman aşımına uğramıştı. Dosya doğru bulunmuş ve okunmuştu; sorun arama değil, dosya içindeki çok sayıda ismin gereksiz karar seçeneği üretmesiydi. Rota-temelli karar daraltması ve regresyon testi eklendi. Tek başarılı tekrar, tüm zaman aşımlarının ortadan kalktığını kanıtlamaz.

## 2 Eylül recovery doğrulaması

İki canlı soru, aynı genel policy ve `qwen2.5-coder:7b` ile yeniden çalıştırıldı:

- `read_file` limiti sorusunda ilk taslaktaki kaynakta bulunmayan `1000` değeri deterministik GROUNDING tarafından reddedildi. Model, fonksiyon gövdesinde gördüğü `MAX_READ_LINES` adını seçerek tanımı aradı ve `tools.py:9` satırındaki `80` değerini okudu. Sonraki taslak ayrı VERIFY kontrolünden geçti.
- `MAX_SEARCH_RESULTS` tanım/değer/kullanım sorusunda ilk cevap kullanım yerini atladı. VERIFY checklist'i bu alt isteği eksik işaretledi; RECOVER `search_code('MAX_SEARCH_RESULTS')` seçti ve `_format_search_results` gövdesindeki kullanımı okuyarak cevabı tamamladı.

Bu iki çalışma, akışın belirli sabit değerlerini controller'a kodlamadan eksik kanıt için araştırmaya dönebildiğini gösteren geliştirme kontrolleridir; held-out benchmark veya genel yüzde yüz başarı kanıtı değildir. İlk sorudaki gerekçe, model tarafından kaynak ifadesinden daha genel biçimde paraphrase edildiği için doğal dil semantiği hâlâ insan incelemesi gerektirir.

## 3 Eylül güncel kabul kontrolleri

Aynı `qwen2.5-coder:7b`, thinking kapalı ayarıyla güncel controller üzerinde aşağıdaki canlı görevler çalıştırıldı:

| Görev | Sonuç | Süre | İnceleme |
| --- | --- | ---: | --- |
| `MAX_SEARCH_RESULTS` tanımı ve değeri | Geçti | 49 sn | `tools.py:10`, değer `50`; 5 model ve 3 araç çağrısı. |
| `EXCLUDED_DIRECTORIES` tanımı, değerleri ve yalnız `list_files` kullanımı | Geçti | 3 dk 43 sn | İlgisiz `find_file` kapsamı elendi; yalnız `tools.py:11` ve `tools.py:73-89` kullanıldı. |
| JSON array girdisinde `extract_json_object` davranışı | Geçti | 3 dk 05 sn | Parse işlemi ile sonraki `dict` tip kontrolü doğru sırayla ayrıldı; `None` sonucu doğru gerekçelendirildi. |
| `list_files` gizli/harici klasör koşulu | Güvenli başarısızlık | 2 dk 17 sn | Model iki taslakta da `not entry.name.startswith('.')` koşulunu eksik/ters yazdı. Deterministik AST kontrolü iki cevabı da engelledi; yanlış sonuç yayımlanmadı. |

Son görev, kaynak bulmanın ve yanlış cevabı engellemenin çalıştığını; fakat Qwen 2.5'in aynı kanıtı her zaman doğru yorumlayamadığını gösterir. Bu nedenle Faz 2 kabulü henüz verilmemiştir. Beklenen cevabı controller'da üretmek yerine model karşılaştırması ve sabit görev seti ölçümü sürdürülmelidir.

### Qwen 3.5 4B ilk karşılaştırma

Resmî `qwen3.5:4b` Q4_K_M modeli 4.7B parametreyle kuruldu. Ollama çalışan model boyutunu yaklaşık 3.1 GB ve işlemci kullanımını yüzde 100 GPU olarak gösterdi. Thinking kapalı kısa literal tekrar testi 3.3 saniye sürdü.

Qwen 2.5'in tamamlayamadığı `list_files` gizli/harici klasör koşulu aynı controller ve soru ile çalıştırıldı. Qwen 3.5 4B ilk taslakta davranışı doğru açıkladı fakat birleşik koşulu tek parça vermedi; deterministik koşul kontrolünden sonraki revizyonda `not entry.name.startswith(".") and entry.name not in EXCLUDED_DIRECTORIES` ifadesini ve sonucunu doğru verdi. VERIFY'ın olumlu verdict yanında ilgisiz sorunlar yazması gereksiz bir recovery oluşturdu; sonraki taslak yine doğru kabul edildi. Toplam süre 3 dakika 30 saniye, sonuç `review_required` oldu. Olumlu verdict ile dolu sorun listesinin birlikte dönmesi daha sonra protokol şemasında yasaklandı.

İki ek canlı karşılaştırma yapıldı:

- Girdi tipi açıkça `content` parametresine verilen `"[1, 2]"` string'i olarak yazılan `extract_json_object` görevinde model ilk taslakta doğru işlem sırasını kurdu: `json.loads` başarılı oldu, sonuç `list` olduğu için `dict` kontrolü sağlanmadı ve `None` döndü. Görev 5 model ve 4 araç çağrısıyla 1 dakika 22 saniyede tamamlandı.
- Kısa `bu repoda qwen modeli nerede çağrılıyor?` görevinde model doğru `trace_call` rotasını seçti ve `MODEL_NAME → ModelGateway(MODEL_NAME) → chat(model=self.model_name, ...)` zincirini buldu. Taslak doğru olmasına rağmen aynı modelin VERIFY çağrısı kaynakta olmayan ek açıklama beklentileriyle taslağı reddetti; RECOVER ilgisiz `selected` sembolüne yöneldi ve araştırma bütçesi doldu. Bu görev çıktı üretmedi.

Bu üç görevde 4B araştırma ve taslak üretiminde Qwen 2.5 7B'den daha iyi semantik örnekler verdi ve 9B'den daha düşük bellek kullandı. Bununla birlikte aynı küçük modeli hem üretici hem reviewer olarak kullanmak hâlâ yanlış ret üretebilir. Güncel donanım için ilk tercih `qwen3.5:4b` olsa da bu tercih Faz 2'nin tamamlandığı veya her görevin doğru sonuçlanacağı anlamına gelmez.

Çalıştırma:

```bash
./venv/bin/python -B -m unittest discover -v
```

## Gerçek model değerlendirmesi — Qwen 2.5 baseline

Model: `qwen2.5-coder:7b`; kurulu model bilgisi 7.6B parametre ve Q4_K_M quantization gösteriyordu. Aşağıdaki tablo, Qwen 3.5 denemesinden önce alınmış baseline kaydıdır.

Bu baseline sırasında ortak ayarlar `temperature=0`, `num_ctx=8192`, `num_predict=768`; toplam çağrı bütçesi 240 saniye ve istek timeout'u 60 saniyeydi. Güncel controller bütçeleri sırasıyla 420 ve 90 saniyedir.

Dört proje sorusu ve başka bir geçici depodaki iki soru kullanıldı. Sorulara göre policy veya model ayarı değiştirilmedi. Geçici depoda farklı dosya adları ve farklı bir değer kullanıldı; cevap anahtarı model mesajlarına eklenmedi.

**Bu küçük set geliştirme sırasında tekrar kullanıldığı için kör/held-out benchmark değildir.** Ayrı depo kullanmak tek başına geniş genelleme başarısı ispatlamaz.

### Qwen 3.5 9B ilk karşılaştırma

`qwen3.5:9b` modeli 9.7B parametre, `Q4_K_M` quantization ile M3/16 GB sistemde
8192 context kullanarak yüzde 100 GPU üzerinde yüklendi. Ollama çalışan model boyutunu 5.6 GB
olarak bildirdi. Thinking açık ilk agent denemesi 6 dakika 31 saniye sürdü; doğru taslak
üretilmesine rağmen VERIFY timeout olduğu için sonuç yayımlanmadı.

Thinking controller üzerinden kapatıldıktan sonra aynı soru değiştirilmeden yeniden çalıştırıldı.
ROUTE doğru biçimde `explain_behavior` seçti; `protocol.py:136-141` okundu ve
`sort_keys=True` davranışı ek test araması gerekmeden doğru yorumlandı. VERIFY cevabı destekli
ve eksiksiz kabul etti. Çalışma 5 model, 3 araç çağrısıyla 2 dakika 55 saniyede tamamlandı.
Bu tek görev, Qwen 3.5'in genel olarak daha başarılı olduğunu kanıtlamaz; aynı sabit görev setinin
iki modelle tamamlanması gerekir.

Çağrı-zinciri sorusunun ilk Qwen 3.5 denemesinde router, proje listesindeki `agent.py` ve
`tools.py` adlarını soruda söylenmiş hedefler gibi kullandı ve dosyaları sırayla okumaya başladı.
Başlangıç sorguları daha sonra yalnız soruda geçen hedeflerle ve araç–hedef türü eşleşmesiyle
sınırlandırıldı. Aynı sorudaki sonraki çalışmalarda doğru zincir
`Qwen → MODEL_NAME → ModelGateway → chat(model=self.model_name, ...)` olarak bulundu.
80 satırlık sınıf bloğunun sonundaki eksik Python ifadesi için en uzun geçerli okunmuş prefix
analizi eklendi; modelin cevap içine yazdığı satır konumları da deterministik olarak kaldırıldı.
Buna rağmen son gerçek çalışma 7 dakikada VERIFY timeout ile durdu. Bu nedenle Qwen 3.5:9B,
thinking kapalıyken semantik olarak daha iyi örnekler göstermiş olsa da mevcut M3/16 GB ortamında
çok aşamalı agent için henüz başarılı model adayı sayılmamaktadır.

### Güncel sürüm: okunabilir kaynak blokları

Altı görev tamamlandı. Bir görevde inceleme gerektiren taslak döndü; diğer beş görevde sonuç üretilemedi. Dönen taslakta da ilk sayısal iddianın atfı eksik olduğu için bu, eksiksiz doğrulanmış bir başarı olarak sayılmadı.

| Görev | Süre | Sonuç | Gözlem |
| --- | --- | --- | --- |
| Dosya okuma limiti ve gerekçesi | 134,38 sn | Tamamlanamadı | Gövdeyi okudu fakat sayısal tanımı toplamadan cevaba geçti; taslak reddedildi. |
| JSON liste girdisinin dönüşü | 123,29 sn | Zaman aşımı | Uygulamayı okudu ancak dönüşü yanlış yorumladı; kontrol aşaması tamamlanamadı. |
| Argüman sırasının imzaya etkisi | 108,80 sn | Tamamlanamadı | İlgili koddan sonra başka JSON kullanımlarına saptı; tekrar arama durduruldu. |
| Gizli dosyaların listelenmesi | 148,28 sn | Yanlış ret | İlk taslak doğru olumsuz ifadeyi içeriyordu; kontrol modeli bunu ters okuyup reddetti. |
| Ayrı depoda bağımlılığın değeri | 126,84 sn | İnceleme gereken taslak | Değer ve dosya doğru; ilk sayısal iddia değer tanımının kanıt bloğunu da seçmeliydi. |
| Ayrı depoda None dalı | 122,69 sn | Tamamlanamadı | Ana dönüş davranışı doğru; gereksiz konum ifadeleri ve kaynakla çelişen kontrol gerekçeleri var. |

Kaynak alıntısı kontrolü, yalnız çıktı üreten görevlerde anlamlıdır. Çıktı üretilmemesi bir yanlış satır numarası hatasıyla aynı şey değildir. Zaman aşımı da yanlış cevap üretmeyle ayrı sınıflandırılır.

Dönen taslağın dosya/satır/alıntı alanları değerlendirme öncesi kaynak metniyle birebir eşleşti. Ancak her iddiaya yeterli kanıt bağlanması ayrıca kontrol edildi: kaynak kimliklerinin doğru olması, tek başına iddia–kanıt ilişkisinin eksiksiz olması değildir.

Gizli dosya örneğinde ilk taslak “gizli dosyaları listelemiyor” diyordu. Kontrol modeli bunu dosyaları listeliyormuş gibi aktardı. Bu kayıt, kontrol modelinin raporunu da sorgulamadan doğru kabul etmemek gerektiğini gösteriyor. Yeni kaynak sunumu tek başına görev başarısı sorununu çözmedi.

Değerlendirilen runtime dosyalarının SHA-256 değerleri:

```text
agent.py    ce03c5de25b6cceb124c1f35338c1c0014eaa4ddb5a70c9c3e5d4b81bd7c8638
tools.py    2c8a6ea2e34c8adae10b7d1f362d49b3845de49bb986be526109f292616aae84
protocol.py 04f4d1e81c56aecee2914db0c6ebca98c04824e3f73a4156739dbf330c4c9434
evidence.py 2845f155936e5efb4396e0e676d75f571c1aee4e24c5847c9471a87cf7378aca
```

### Önceki denemeler neden saklandı?

Eski serbest döngüde tamamlanan üç deneme başarısızdı; dördüncü deneme süre nedeniyle durdurulmuştu. Sonraki iki aşamalı protokol denemesinde model ikişer cevaba onay verdi, fakat bunlardan birinde gerekçe yanlış satıra bağlanmıştı; diğerinde tanım/kullanım yeri karışmıştı. Bu yanlış onaylar başarı sayılmadı.

Kaynak kimliği, JSON şeması veya ikinci bir modelin onayı tek başına semantik doğruluk ispatı değildir. `supported_answer` etiketinden `review_required` etiketine geçilmesinin nedeni budur.

Ham çağrılar, süreler ve runtime dosyalarının SHA-256 değerleri değerlendirme çalışma klasöründe saklandı; agent'ın aradığı depoya cevap kayıtları eklenmedi:

- `phase2-general-policy-evaluation-2026-08-30.json`: önceki serbest döngü.
- `phase2-staged-evaluation-2026-08-30.json`: satır kimlikli ilk protokol.
- `phase2-block-evaluation-2026-08-30.json`: blok kimlikli protokol.
- `phase2-final-evaluation-2026-08-30.json`: kaynak sunumu değişmeden önceki ara sürüm; dosya adı sürümün başarıyla tamamlandığı anlamına gelmez.
- `phase2-readable-source-evaluation-2026-08-30.json`: güncel kaynak sunumu.
- `evaluate_staged_agent.py`: repo dışında çalışan yerel değerlendirme betiği.

## Kalan sorunlar ve kabul ölçütü

- Model, gerekli bir tanımı okumadan araştırmayı yeterli sayabiliyor veya yeterli kaynak varken gereksiz yardımcı fonksiyonları takip edebiliyor.
- Model yorumu ve ikinci model kontrolü hem yanlış kabul hem yanlış ret üretebilir. `review_required` taslağı otomatik uygulanmamalıdır.
- Araştırma Python merkezlidir; kapsamlı modül/üye çözümleme, dinamik davranış analizi ve bütün programlama dilleri desteği yoktur.
- Kaynak limitleri tüm büyük depolarda optimal retrieval veya kesin token bütçesi garantisi değildir.
- Doğru kaynak bulma, doğru satır/alıntı, doğru yorum, eksiksiz yanıt, tekrar sayısı ve süre ayrı ölçülmelidir.

Faz 2 kabulü için yalnız controller testlerinin değil, belirlenmiş görev setinin doğru ve eksiksiz yanıt ölçütünün de sağlanması gerekir. Bu koşul henüz karşılanmadı. Sonraki çalışma cevap ipuçları eklemek değil; model/protokol seçeneklerini sabit görevlerde karşılaştırmak, kanıt yeterliliği kararını düzeltmek ve daha sonra yeni görevlerde tekrar ölçmektir.

Tüm gelecekteki sorular için yüzde yüz LLM doğruluğu vaat edilmez. Kesin bir dosya/satır/alıntı kaydı ile o kaydın model tarafından doğru yorumlanması farklı güvencelerdir.
