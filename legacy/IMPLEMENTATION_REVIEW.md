# İnceleme ve uygulama kaydı — 18 Eylül 2026

## 20 Eylül — dosya / fonksiyon adı karışıklığı

- `observed_symbols` ile modele her okunmuş Python parçasındaki gerçek tanım
  başlıkları ve kullanılan adlar ayrı verilir. Yorum/string içindeki sahte
  tanımlar sayılmaz; docstring ortasında kesilen parçadan önceki tamamlanmış
  başlıklar korunur. Tanım ile import/kullanım aynı şey değildir.
- Identifier eşleşmesi alt-dize yerine tam ada göre yapılır. Ayrı dosyalara
  ilişkin fonksiyon cümleleri ayrıştırılarak yalnız bağlı kaynakta adı geçen
  sembollerin o dosyayla ilişkilendirilmesi istenir/kontrol edilir. Benchmark
  string'indeki kullanım bir tanım olarak gösterilmez.
- Güvenlik açıklamasında kaynağın kapsamının ve belirsizliğinin korunması
  istenir; risk azaltma evrensel güvenlik garantisine çevrilmemelidir. Bu
  doğal dil talimatı tek başına semantik doğrulama değildir.
- Altı regresyon eklendi. **308 test / 1.081 sn / OK; diff kontrolü temiz.**

Aynı MarkupSafe sorusu Qwen 2.5 Coder 7B ile tekrar çalıştırıldı: 3 model
çağrısı, 4 okuma bloğu. Önceki yanlış `_native.py`/`escape` eşleştirmesi
sonuçta tekrarlanmadı. Model fonksiyon adını vermek yerine genel dosya görevi
açıklamasına döndü; bu, doğru isimleri eksiksiz anlattığı iddiası değildir.
Amaç metninde “saldırıları önlemek için kullanılır” gibi genel bir paraphrase
kaldı. Kaynağın daha dar risk azaltma anlamıyla birebir eşdeğer sayılmadı;
insan incelemesi uyarısı korunur. Patch uygulanmadı, hedef kod çalıştırılmadı.

---

## MarkupSafe örnek üretimi düzeltmesi

Kullanıcının MarkupSafe özetinde model, okunmuş README örneğindeki dönüşümü
yeniden yazarken yanlış çıktı üretti. Düzeltme bir HTML/replace yorumlayıcısı
veya bu repository'ye özel doğru cevap eklemek değildir:

- Amaç ve dosya özetinde istenmeyen giriş–çıkış örnekleri üretilmemesi istenir.
- Örnek gerekiyorsa `source_quotes` ile gerçek okuma bloğundan en fazla 12
  satır seçilir; model alıntının içeriğini yazamaz. Controller metni kopyalar.
- Tırnaklı/kod biçimli parçalar yalnız bağlanan kaynakta veya gerçek kaynak
  konumunda bulunuyorsa kabul edilir. Bu, alıntı doğrulamasıdır; dönüşümün
  anlamını yürütmez ve her doğal dil hatasını engellediği iddia edilmez.
- Dokuz regresyon testi eklendi: farklı örnek değerleri, yanlış kaynak kimliği,
  uydurma çıktı, Unicode/escape korunması, geçersiz aralıklar ve gerçek alıntı
  çıktısı. **Son tam koşu: 302 test, OK (1.412 sn); diff kontrolü temiz.**

Qwen 2.5 Coder 7B / thinking kapalı ile aynı MarkupSafe sorusu yeniden denendi.
Commit: `b2e4d9c7687be25695fffbe93a37622302b24fb1`. README, bench.py,
src/markupsafe/__init__.py ve _native.py okundu; 2 model çağrısı, 4 okuma bloğu.
Özet dosya görevlerini anlattı ve hatalı dönüştürme örneğini tekrarlamadı.
Güvenlik amacı açıklaması hâlâ geniş bir model paraphrase'idir; tüm girdilerde
güvenlik garantisi veya uygulama güvenlik denetimi sayılmaz. Hedef kod/test
çalıştırılmadı, dosya değiştirilmedi. `review_required` durumu korunur.

---

## 19 Eylül ek kontrolü — özetleme

Kullanıcının samplemod çıktısında proje amacı uygulama örneğinden tahmin
ediliyor, gerçek sabit metin değiştiriliyor ve seçilmemiş dosyalar “okunamadı”
diye raporlanıyordu. Özetleme akışında şu değişiklikler yapıldı:

- Varsa proje seviyesindeki README/giriş ile uygulama kaynağı birlikte seçilir.
  Amaç türündeki iddia, okunmuş giriş/manifest kanıtına bağlanır. README yoksa
  kod özeti engellenmez; kaynak eksikliği controller tarafından belirtilir.
- Modelin `limitations` alanı kaldırıldı. Okunan parçalar, seçilmeyen adaylar,
  başarısız/reddedilen okuma denemeleri controller kayıtlarından üretilir.
- `summary_facts.py`, yalnız okunan basit doğrudan sabit dönüşleri çıkarır.
  Model değer üretmek yerine gözlem kimliğini seçebilir; kaynak ifadesi aynen
  gösterilir. Açıkça adlandırılmış/atıf yapılmış fonksiyon için değiştirilmiş
  tırnaklı değer dar bir kontrolle reddedilir. Bu, genel semantik ispat değildir.
- README olmayan repo, Türkçe/İngilizce yanlış literal, Unicode, docstring,
  koşullu/dekoratörlü/async fonksiyonlar, gerçek okuma hatası ve JSON çıktısı
  için farklı isim/değerlerle 15 yeni regresyon testi eklendi.

**Son koşu: 293 test, OK; git diff --check temiz.** Qwen 2.5 Coder 7B ile
kullanıcının aynı sorusu mevcut samplemod checkout'unda tekrar çalıştırıldı:
README + üç uygulama dosyası okundu, Python proje örneği amacı doğru belirtildi,
`get_hmm` dönüşü `'hmmm...'`, `get_answer` dönüşü `True` olarak doğru verildi.
Seçilmeyen dosyalar erişim hatası sayılmadı. Sonuç 3 model çağrısı / 4 okuma
bloğuyla `review_required` durumunda üretildi; yeni bir denetçi aşaması eklenmedi.
İndirilen kod çalıştırılmadı. Bu başarılı örnek, eski Faz 2 başarısızlıklarının
tamamının çözüldüğü veya rastgele her özetin doğru olduğu anlamına gelmez.

Kullanıcının ayrıca gönderdiği docstring patch'i yalnız önizlemedir. Sıralama
uygulaması `sorted(entry.name ...)` kullanır: kesin ifade Python'ın varsayılan,
büyük/küçük harfe duyarlı Unicode leksikografik sırasıdır; doğal sayısal veya
Türkçe yerel alfabe sıralaması değildir. Önerideki “alfabede sıralı” ifadesi
bu ayrımı belirtmediği için uygulama öncesi insan incelemesi gerekir.

---

## Kapsam ve yöntem

Atanan PDF'nin Faz 1–3 görevleri ve kabul kriterleri esas alındı. Eski hata
örnekleri, mevcut kod, git farkları ve testler incelendi. Mevcut kullanıcı
değişiklikleri korunarak ekleme yapıldı; git reset veya toplu silme yapılmadı.
Eski README kaybolmaması için README_HISTORY.md olarak saklandı.

Bu çalışma üç farklı başarı türünü ayırır:

1. **Controller güvenliği:** dosya sınırı, okuma bütçesi, gerçek atıf, onaylı yazma.
2. **Model araştırma başarısı:** doğru kaynağı bulma ve doğru yorumlama.
3. **Proje kabul ölçümü:** sabit easy issue setinde en az 4/5 diagnosis ve
   üç kolay issue için geçerli küçük patch. Birim testler bu ölçümün yerine geçmez.

## Bulunan ve giderilen somut sorunlar

| Sorun | Düzeltme | Test/kontrol |
| --- | --- | --- |
| Bağlam bütçesi aşan okuma “okundu” olarak kaydediliyordu | Kanıt kaydı tüm kontrollerden sonra işlenir | `test_failed_read_is_not_committed` |
| Aynı adlı sabit başka, ilişkisiz modülden alınabiliyordu | Yalnız aynı modül veya gerçek statik import bağımlılığı izlenir | İlişkisiz sabit + alias import testleri |
| Nitelikli referans adı şemada kabul edilip aramada kaçıyordu | AST attribute referansı aranır | `text.strip` referans testi |
| Değersiz tür açıklamalı atamada AST yürüyüşü patlayabiliyordu | `AnnAssign.value is None` guard'ı | Regresyon testi |
| Doğru paraphrase, koşulu birebir yazmadığı için reddediliyordu | Sözcüksel mekanizma kontrolü yalnız reviewer ipucu olur | Negatif API iddiası gerçek VERIFY'a ulaşır |
| API adının yokluğu, olumsuz bir cümleyi de yanlış sayıyordu | Yokluk/alias belirsizliği semantik incelemeye aktarılır | `test_negative_api_claim_reaches_semantic_review_not_research` |
| Router açık kod adı yerine yorum metnini arayabiliyordu | Açık identifier için sınırlı tanım araması önce gelir; bulunan gerçek scope önceliklidir | Açık identifier yönlendirme testi + canlı tekrar |
| Büyük/özel dosyalar kontrolsüz okunabiliyordu | Boyut ve normal dosya kontrolü, kademeli satır okuma | Mevcut araç testleri |
| Metadata/sırlar farklı harflerle hedeflenebiliyordu | Path parçalarında casefold, özel anahtar/credential engeli | `.GiT`, `.ENV`, `.key` testleri |
| Klasör çıktısı ve taraması sınırsızdı | 200 çıktı, 5000 giriş tarama sınırı; kesilme açıkça bildirilir | Araç testleri |
| Gerçek satır numarası sabitin değeri sanılıp reddediliyordu | Atıftaki gerçek konum maskelenir; davranış değeri ayrı kontrol edilir | Konum 14 / değer 50 / uydurma konum 999 regresyonu |
| Yanlış diagnosis metni değişiklik planına istenen davranış olarak taşınıyordu | Plan yalnız özgün değişiklik isteğini ve okunmuş kodu alır | Ters bildirim tercihi canlı tekrar + yanlış diagnosis bağlam testi |
| Özetleyici tarama politikasını hedef projenin özelliği sanıyordu | Controller envanter politikası model bağlamından ayrıldı; kullanıcı raporunda kaldı | Bağlam ayrımı regresyonu |

Bu kontroller program davranışının tüm doğal dil yorumlarını ispatlamaz.
Özellikle aynı LLM hem yazar hem hakem olduğunda ortak yanlış yorum mümkündür.
Sayının alıntıda bulunması da tek başına doğru akıl yürütme demek değildir.

## Eklenen özellikler

- Public GitHub checkout + sınırlı repository özetleme; gerçek satır atıfları,
  açık kısmi envanter, bilinmeyen kimliklerin reddi. İndirilen kod çalıştırılmaz.
- Plan ve patch üretimi ayrı protokoller. Model dosya yolunu seçip doğrudan yazamaz;
  hedef dosya okunan kanıttan, uygulama yetkisi insandan gelir.
- Diff'e bağlı onay token'ı, bir dosyalık küçük edit, hash/izin kontrolü,
  symlink/hardlink engeli, Python sözdizimi kontrolü, atomik uygulama.
- Kalıcı olmayan private rollback kaydı; ters diff + ayrı insan onayı.
  Araya giren kullanıcı değişikliği geri alma tarafından silinmez.
- Komut satırı ve insan onayı `cli.py` içinde ayrıldı. Araştırma controller'ına
  yazma aracı verilmedi. Otomatik hedef test çalıştırma Faz 4'e bırakıldı.

## Doğrulama

Başlangıçta 227 birim testi geçiyordu. Yeni güvenlik ve entegrasyon testleri
eklendi. Son toplam ve canlı model sonuçları aşağıda kaydedilir.

```bash
./venv/bin/python -B -m unittest discover -p 'test_*.py'
```

GitHub indirme doğrulandı: `navdeep-G/samplemod`, commit
`d469f2f5e0a472be2c7d95ff90ed46e975810dc8`; hook/submodule/dependency/target test
çalıştırılmadı. Model tek seferde çalıştırılır; yerel RAM üzerinde paralel
LLM yükü oluşturulmaz.

## Bilinen sınırlar

- Rastgele her soruda, her yazım hatasında veya her dilde başarı garantisi yoktur.
- AST çözümleme dinamik import/reflection/veri akışının tümünü kapsamaz.
- İndirmede toplam byte kotası yoktur; tarama, kaynak okuma ve context sınırlıdır.
- Güvenli patch motoru OS sandbox'ı değildir; kötü niyetli eşzamanlı filesystem
  manipülasyonlarına karşı tam izolasyon iddiası yoktur.
- Sözdizimi geçerli patch davranışsal olarak yanlış olabilir. Onaydan önce diff
  incelenir; otomatik güvenilen test yürütme henüz yoktur.
- `review_required` model taslağıdır, “doğru” etiketi değildir.

## Canlı model ölçümü

Sonuçlar test sırasında kaydediliyor; aşağıdaki tamamlanan kayıtlar esas alınır.
Araştırma devam ederken kaynak değiştirilmiş bir çalışma başarı/başarısızlık
oranına katılmaz: hash kontrolü bu koşulda doğru biçimde durmalıdır.

### Son birim test koşusu

**278 test / 1.000 saniye / OK.** Başlangıçtaki 227 teste göre 51 yeni test
vardır. `git diff --check` temizdir. Mock model kullanan testler gerçek Qwen'in
doğal dil doğruluğunu ölçmez. Güvenlik kontrolleri tam OS izolasyonu değildir.

### Araştırma smoke testi — qwen2.5-coder:7b, thinking kapalı

| Soru/konu | Son gözlem | Süre | Değerlendirme |
| --- | --- | --- | --- |
| list_files, os.walk ve gizli dosyalar | Doğru fonksiyon okundu; `iterdir` görülmesine rağmen `os.walk` iddiası onaylandı | 168.3 sn | Yanlış |
| read_file için 10–5 aralığı | Geçerli dosya varsayımıyla ters aralığın hata döndürdüğü açıklandı | 121.2 sn | Doğru |
| tool_call_signature anahtar sırası | `sort_keys=True` nedeniyle aynı imza | 109.5 sn | Doğru |
| _resolve_safe_path dış yol | `None` bulundu; kök kontrolünün açıklaması eksik/karışıktı | 198.8 sn | Kısmi |
| MAX_SEARCH_RESULTS değeri/konumu | Satır numarası kontrolü düzeltildikten sonra gerçek tanım ve 50 bulundu | 71.4 sn | Doğru |

Son tablo **3 doğru, 1 kısmi, 1 yanlış** içerir. Bu, önceden sabitlenmiş beş
bug içeren formal kabul seti değil, kendi kodumuz üzerinde bir smoke testidir.
Faz 2 için 4/5 doğru diagnosis kabulü kazanılmış olarak yazılmaz. Aynı modelin
cevap ve VERIFY aşamalarında aynı yanlış yorumu paylaşması hâlâ mümkündür.
Yanlışlıkları yalnız modele yüklemek de doğru değildir: prompt, kapsam ve
denetim tasarımının birlikte ölçülmesi gerekir.

### Canlı patch denemeleri — izole, üç fonksiyonlu fixture

| Hata | Üretilen değişiklik | Süre | Sonuç |
| --- | --- | --- | --- |
| Toplamanın çıkarma yapması | `a - b` → `a + b` | 141.2 sn | Geçerli küçük önizleme |
| Kapasite eşitliğinin atlanması | `count > capacity` → `count >= capacity` | 165.4 sn | Geçerli küçük önizleme |
| Bildirim tercihinin ters çevrilmesi | `not preference` → `preference` | 77.9 sn, son tekrar | Geçerli küçük önizleme |

Üç diff de Python sözdizimi kontrolünden geçti. **Canlı patchler uygulanmadı**;
onaylı uygulama/geri alma ayrıca geçici dosyalarda birim/entegrasyon testleriyle
kontrol edildi. İkinci planın beklenen-sonuç açıklaması eksikti; üçüncü örneğin
ilk denemesi değişiklik içermiyordu ve motor tarafından reddedildi. Planı yanlış
diagnosis metninden ayırdıktan sonra üçüncü diff doğru üretildi; buna rağmen
öncesindeki doğal dil diagnosis hâlâ yanlıştı. Doğru diff bütün açıklamanın
doğru olduğu anlamına gelmez.

Bu ölçüm Faz 3 mekanizmalarının ve üç küçük patch üretiminin çalıştığını
gösterir; büyük gerçek bir backend üzerinde tam uçtan uca kabul değildir.

### GitHub özetleme

Public `samplemod` checkout'u okundu; hedef kod/test/kurulum yürütülmedi.
İlk özet yalnız dokümantasyon/config seçtiği için uygulama kaynağı okuma
gerekliliği eklendi. Sonraki koşu gerçek `core.py`/`helpers.py` dosyalarını okudu
fakat controller'ın dışladığı klasörleri hedef projenin özelliği sandı. Tarama
politikası model bağlamından ayrıldı. Son tekrar Türkçe çıktı verdi ve bu
politika iddiasını tekrarlamadı; ancak fonksiyon docstring'i `Contemplation...`
metnini olası ekran çıktısı sandı. Gerçekte kod `hmmm...` yazdırır. Bu yüzden
son özet tamamen doğru kabul edilmedi. `__init__.py` içindeki
`from .core import hmm` aktarımı gerçek kaynakta vardır, hata değildir.
Atıfların gerçek olması, cümlelerin doğru olduğu garantisi değildir; özetler
de `review_required` olarak sunulur ve terminalde insan incelemesi uyarılır.

### Teslim durumu

- Faz 1/2 araştırma altyapısı korundu ve somut controller hataları giderildi.
- Faz 3 plan/diff/onay/uygulama/rollback mekanizmaları eklendi.
- GitHub kaynak seçimi ve sınırlı özetleme mevcut.
- Modelin yanlış pozitif yorumları açık sorun olarak duruyor; bütün ilk üç
  fazın formal kabulünün tamamlandığı iddia edilmiyor.
- Kullanıcı repository'sinde otomatik patch, commit veya push yapılmadı.
- Otomatik hedef test yürütme / test çıktısıyla onarım döngüsü Faz 4'tür.
