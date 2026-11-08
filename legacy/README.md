# Local Coding Agent

Ollama üzerinden yerel bir modelle çalışan, repository içinde araştırma yapan,
cevabını gerçek dosya/satır alıntılarına bağlayan ve **insan onayıyla küçük patch**
uygulayabilen eğitim projesi. Public GitHub repository'lerini izole bir yerel
kopyaya indirip inceleyebilir; sınırlı kaynak okumasıyla özet çıkarabilir.

Hedef ortam: Apple Silicon / 16 GB; mevcut baseline `qwen2.5-coder:7b`.
Bu bir genel sohbet uygulaması veya doğruluğu garanti edilen otonom geliştirici değildir.
Modelin arama/yorum hataları ölçülür; yalnız birim testlerin geçmesi model başarısı sayılmaz.

## Başlangıç

Python 3.10+ ve çalışan yerel Ollama gerekir. Kurulumu güvenilen bu agent
repository'sinde yapın; incelenen başka repository'nin bağımlılıkları çalıştırılmaz.

```bash
python3 -m venv venv
./venv/bin/python -m pip install -r requirements.txt
ollama pull qwen2.5-coder:7b
./venv/bin/python agent.py "read_file tek okumada kaç satır kabul eder? Sınır aşılırsa ne döndürür?"
```

## Araştırma ve özetleme

```bash
# Kendi projesinde kaynak araştırması
./venv/bin/python agent.py --model qwen2.5-coder:7b "tool_call_signature nasıl çalışır? Kodla açıkla."

# Yerel başka bir repository
./venv/bin/python agent.py --repo /tam/yol/proje "İncelenecek fonksiyon ve soru"

# Public GitHub repository: yeni, sığ, geçici checkout
./venv/bin/python agent.py --repo https://github.com/navdeep-G/samplemod --summary

# Özetin odağını kendin belirle
./venv/bin/python agent.py --repo /tam/yol/proje --summary "Projenin amacı, temel modülleri ve giriş noktalarını Türkçe özetle."

# Makine-okunabilir tek JSON sonucu
./venv/bin/python agent.py --json "MAX_SEARCH_RESULTS nerede tanımlanıyor?"
```

Özet en fazla 24 dosya adayı, 6 küçük okuma bloğu ve 10.000 kaynak karakteri
kullanır. Kısmi tarama/okuma açıkça belirtilir. README iddiaları uygulama kodu
kanıtıyla aynı şey değildir. `--summary` tüm repository'yi audit ettiğini iddia etmez.

Özet seçiminde, varsa proje seviyesindeki README/giriş kaynağı ve uygulama
kaynağı birlikte okunur. Proje amacı, giriş/manifest kanıtına bağlanır.
Okunan parçalar, seçilmeyen dosyalar ve tamamlanamayan okuma denemeleri
controller kayıtlarından raporlanır; okuma durumu modelden alınmaz.
Basit Python sabit dönüşlerinde model `R…` kaynak gözlemini seçer; `return`
ifadesini controller birebir gösterir. Bu, koşullu/dinamik fonksiyonları
çözümleyen bir yorumlayıcı değildir; genel açıklamalar insan incelemesi gerektirir.
Amaç/dosya özetinde modelden giriş–çıkış örneği hesaplaması istenmez. Örnek
gerekiyorsa `source_quotes` ile okunmuş kaynaktan en fazla 12 satırlık aralık
seçilir; alıntı metnini model değil controller üretir. Atıfta bulunmayan
tırnaklı/kod biçimli metinler reddedilir. Bu kaynak kontrolü, bütün doğal dil
çıkarımlarının doğruluğunu ispatlamaz.
Özet modeline okunmuş Python parçalarındaki tanım başlıkları ve kullanılan
adlar ayrı bir envanterde verilir. Bir adın import edilmesi/kullanılması tanım
sayılmaz; identifier eşleşmesi alt-dize eşleşmesi değildir. Dosya–fonksiyon
cümleleri kaynak konumuyla ayrı ayrı ilişkilendirilir. Bu kontrol tam çağrı
grafiği veya doğal dil doğrulayıcısı değildir.

GitHub desteği yalnız `https://github.com/SAHIP/REPO[.git]` adresleri içindir.
SSH, kimlik bilgileri, özel repo ve `tree/issue/blob` bağlantıları desteklenmez.
Checkout yolu ve commit gösterilir; sonraki soruda bu yerel yolu kullanın.
Hook, submodule, bağımlılık kurma ve hedef kod/test çalıştırma yoktur.
İndirme zaman sınırı vardır, toplam byte kotası yoktur; küçük depolarla başlayın.
Geçici checkout otomatik silinmez, işletim sistemi sonradan temizleyebilir.

## Faz 3: plan → diff → onay → uygulama → geri alma

```bash
# Yalnız plan; dosya değiştirmez
./venv/bin/python agent.py --plan "list_files sonuç sıralamasını incele ve bunu açıklayan kısa bir docstring öner."

# Plan ve diff; dosya değiştirmez
./venv/bin/python agent.py --patch "list_files docstring'ine sonuçların sıralandığını açıklayan tek cümle ekle."

# Diff gösterildikten sonra terminalden açık onay ister
./venv/bin/python agent.py --apply "list_files docstring'ine sonuçların sıralandığını açıklayan tek cümle ekle."

# Uygulama çıktısındaki gerçek kayıt yolunu kullan
./venv/bin/python agent.py --rollback /gercek/kayit/yolu.json
```

`--apply` **otomatik evet değildir**. Kullanıcı, gösterilen diff'e bağlı
`APPLY-…` kodunu terminale aynen yazar. Enter/yanlış kod/pipe ile onay verilmez.
Model yanıtı, README talimatı veya `confidence` dosya yazma yetkisi veremez.

- Tek mevcut UTF-8 dosyada benzersiz, okunmuş bir blok değiştirilir.
- En fazla 60 eklenen/silinen satır; bütün dosyayı yeniden yazmak reddedilir.
- Repository dışı yol, metadata/sır dosyası, symlink ve hardlink reddedilir.
- Kanıt hash'i ve uygulama öncesi dosya hash'i/izinleri eşleşmelidir.
- Python patch'inde `ast.parse` uygulanır; bu **davranış testi değildir**.
- Geri alma kaydı dosya yazılmadan önce private geçici dosyaya kaydedilir.
- `--rollback` ters diff'i gösterir, ayrı onay ister; araya giren kullanıcı
  değişikliklerinin üzerine yazmaz. Kaydı kalıcı saklamak kullanıcıya aittir.

Hedef kodu/testleri çalıştırma ve otomatik test-onarım döngüsü Faz 4 kapsamıdır.
Patch anlamının doğru olduğu garanti edilmez: diff'i inceleyin.

## Mimari ve sorumluluklar

```text
Repository seçimi → LIST → ROUTE → SEARCH → SELECT → READ → ASSESS
                                      ↑                     │ eksik kanıt
                                      └─────────────────────┘
                       DRAFT → kaynak kontrolü → VERIFY → sonuç
                                                    └→ sınırlı RECOVER
İsteğe bağlı: sonuç → PLAN → PATCH önizleme → İNSAN ONAYI → APPLY
Bağımsız özet: sınırlı envanter → model seçimi → READ → atıflı SUMMARY
```

| Modül | Sorumluluk |
| --- | --- |
| `cli.py` | Komutlar, repository seçimi, insan onayı, güvenli terminal diff'i |
| `agent.py` | Araştırma durum makinesi, aşama bütçesi, sonuç ve diagnosis |
| `protocol.py` | Pydantic sözleşmeleri, JSON doğrulaması, Ollama gateway ve süre sınırları |
| `tools.py` | Repository sınırı, dosya/desen/metin/tanım/referans/çağrı araması |
| `evidence.py` | AST konumları, küçük okumalar, kaynak hash'i, gerçek satır ve alıntılar |
| `navigation.py`, `research_routing.py` | Hedef türü ve açık kod adını önceleyen genel araştırma politikası |
| `reference_checks.py` | Okunan kodun referans/return/raise envanteri; semantik doğruluk ispatı değil |
| `citation_checks.py` | Gerçek satır konumlarını sayısal kod davranışı iddialarından ayırır |
| `repository_source.py` | Public GitHub checkout; hedef kodu yürütmez |
| `repository_summary.py` | Sınırlı, atıflı proje özeti |
| `summary_facts.py` | Okunan basit sabit dönüşlerini çıkarır; seçilen kaynak ifadesini değiştirmeden gösterir |
| `patch_protocol.py`, `patch_workflow.py` | Kanıta bağlı plan ve küçük edit önerisi |
| `patching.py`, `patch_journal.py` | Modelden bağımsız onaylı yazma, snapshot ve rollback |

Model arama hedefini, gerekli bağımlılığı ve açıklamayı seçer. Controller'ın
görevi bilinen sorulara cevap ezberletmek değil; yetki, kaynak, bütçe ve protokol
sınırlarını uygulamaktır. Kaynak metni model için güvenilmeyen veridir.

## Sınırlar ve doğrulama

Araştırmada tek okumada 80 satır, arama çıktısında 50 sonuç, AST dosyasında
1 MB, kanıt deposunda 16.000 karakter sınırı vardır. Gateway varsayılanı
300 saniye / 14 model çağrısı; en fazla 3 araştırma ve 2 onarım turudur.
`temperature=0`, `num_ctx=8192`; çıktı token bütçesi aşamaya göre değişir.

Türkçe/İngilizce ve olası yazım hataları desteklenmeye çalışılır; Python adları
case-sensitive kalır. Yakın isim eşleşmesi adaydır, doğru hedef olduğunun ispatı değildir.
Dinamik Python çağrıları ve import zincirleri tam çözümlenmez. AST öncelikle
Python içindir; diğer dillerde kod metni araması daha sınırlıdır.

`review_required` = kaynak bağlantıları doğrulanmış, insan incelemesi gereken
**model taslağı**. Aynı modelin VERIFY onayı yanlış olabilir; confidence doğruluk
olasılığı değildir. `insufficient_evidence`, `budget_exhausted`, `stopped`,
`patch_unavailable` tamamlanamayan işlem anlamına gelir, CLI çıkışı 1'dir.

```bash
./venv/bin/python -B -m unittest discover -p 'test_*.py'
```

Güncel değişiklikler, test kapsamı ve canlı model sonuçları:
[İnceleme raporu](IMPLEMENTATION_REVIEW.md), [Faz 3 durumu](PHASE3_STATUS.md).
[Adım adım mimari açıklaması](ARCHITECTURE_GUIDE.md) öğrenme ve mentor görüşmesi içindir.
Önceki metin kaybolmadı: [tarihsel README](README_HISTORY.md).

CV için savunulabilir tanım: “Yerel LLM ile kanıta bağlı repository araştırması,
sınırlı context yönetimi, GitHub inceleme/özetleme ve insan onaylı küçük patch
iş akışı geliştirdim.” Ölçülmemiş başarı veya sıfır halüsinasyon iddiası kullanılmaz.
