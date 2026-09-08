# Faz 1–2: sabit istek sözleşmeli controller

8 Eylül 2026. Uygulama eklendi; bu sürümün birim testleri ve canlı model
başarısı henüz çalıştırılıp doğrulanmadı. Faz 2 kabulü ilan edilmedi.

## Akış

```text
LIST → DISCOVER (gerçek tanım adayları) → CONTRACT → hedefi ara/oku
                     ↓
       RESEARCH: search / read / answer / stop
          ↑                    ↓
          └─ eksik/yanlış ─ bağımsız kaynak okuması → cevap denetimi → sonuç
```

1. LIST yalnız seçili repository isimlerini listeler.
2. DISCOVER en fazla 12 olası kod adını mevcut sembol/dosya aracıyla arar;
   kod biçimli isimler önceliklidir. Tanım konumları modele aday olarak gösterilir,
   tüm dosya içeriği yüklenmez. Sıfır eşleşmeler de gözlemdir. CONTRACT modeli
   bu gerçek adayları kullanarak hedefi, örnek girdileri/varsayımları ve istenen
   sonuçları ayırır. Kullanıcı alıntıları özgün soruda birebir bulunmalıdır.
   Controller Q kimliklerini atar. Hedef seçimi model kararıdır; aday toplama bir
   cevap veya routing kuralı değildir. Kanıtsız CONTRACT_CHECK döngüsü kaldırıldı.
3. Modelin belirlediği hedef daha önce aranmadıysa hedef türüne göre aranır.
   Keşifte aranan hedef tekrar çalıştırılmaz. Keşif sınırlı aday toplar; bir
   uygulama varsayımı yalnız soruda geçtiği için doğru kabul edilmez.
4. Model her araştırma turunda tek eylem seçer. Okunmamış aday kimliklerinden
   küçük bir bölüm okur veya gerekli bir bağımlılığı arar. Arama sonuçları kanıt
   değildir; actual read kaydı olmadan cevap üretilemez.
5. Cevap her Q kimliğini tam bir kez içerir: doğrudan sonuç, kısa kod açıklaması
   ve okunmuş blok kimliği. Model kaynak kodu yeniden yazmaz; birebir alıntıyı,
   dosya/satır metadata'sını model
   değil EvidenceStore üretir. Hedefin tanımının okunması yapısal olarak kontrol edilir.
6. Bağımsız okuma çağrısı taslağı, eski assessment'ı veya geri bildirimi görmez.
   Özgün soru ve aynı kaynak üzerinden sonuç üretir. Ayrı kısa denetim her Q
   maddesini kaynakla karşılaştırır. İki model yorumunun uyuşması tek başına ispat değildir.
7. Eksik kanıt/yanlış yorum araştırma döngüsüne somut geri bildirim olur. İki
   denetim denemesi, 10 araştırma adımı ve gateway'in toplam süre/çağrı sınırı
   korunur. Aynı kaynakla aynı reddedilmiş cevap yeniden denetlenmez.

## Dosya sorumlulukları

| Dosya | Görev |
| --- | --- |
| task_contract.py | Hedef/girdi/istek şemaları, sabit Q kapsamı, alıntı ve eylem doğrulama |
| repository_agent.py | Yeni read-only araştırma controller'ı ve kısa aşama talimatları |
| tools.py | Mevcut güvenli listeleme/arama/okuma araçları; değiştirilmedi |
| evidence.py | Mevcut AST bağlamı, okunmuş kaynak ve snapshot kayıtları; değiştirilmedi |
| protocol.py | Ollama, JSON/Pydantic, süre/token sınırı; yeni şemalar için context doğrulama |
| agent.py | CLI ve sonuç tipi; yeni varsayılan giriş, korunmuş run_staged_agent |

Eski akış silinmedi. `--legacy-staged` yalnız eski sürümle karşılaştırma içindir.
Eski controller testleri run_staged_agent'ı test eder; yeni controller'ın geçtiğine
kanıt değildir. Yeni testler test_repository_agent.py içindedir.

## Sınırlar ve kabul

- `reference_checks.py`, cevap ve mekanizmadaki nitelikli API adlarını yalnız
  atıf yapılan okunmuş Python bloklarının AST referanslarıyla karşılaştırır.
  Başka bloktaki kullanım, yorum veya string tek başına destek sayılmaz. Kontrol
  model denetiminden önce çalışır; aynı kontrol bağımsız yoruma da uygulanır.
  Alias/indirect call çözümü yapmaz; eşleşmeyen adlar için kanıt veya daha dar
  ifade ister. Olumsuz cümlelerdeki desteklenmeyen adları da temkinli biçimde
  reddeder; Türkçe/İngilizce olumsuzluk tahminiyle kullanım kararı vermez.
  Bu bir semantik doğruluk veya doğrudan çağrının gerçekten çalıştığı ispatı değildir.

- Alıntı doğrudan okuma kaydından gelir; modelin kodu boşluklarıyla yeniden
  yazması istenmez. Gerçek alıntı, yorumun doğru olduğunu tek başına kanıtlamaz.
- Soru maddeleri yalnız özgün kullanıcı alıntılarıdır. Girdi/varsayım alanı da
  kullanıcı metninde bulunmalıdır; keşifte bulunan repository iddiaları buraya yazılamaz.
- Başlangıç sözleşmesini de LLM çıkarır; sabit kimlikler yanlış başlangıç
  yorumunu otomatik düzeltmez. Terminalde kapsam görünür; bu hata ayrı ölçülmelidir.
- Ajan repository kodunu import/exec/eval etmez. Aritmetik ve davranış yorumlama
  model tarafından yapılır; bu aşamada güvenli execution aracı eklenmedi.
- Dosya sınırları ve küçük context korunur. Yazma/patch/test execution yetkisi
  yoktur. Faz 3'te plan ve kullanıcı onayı ayrı bir katman olarak eklenmelidir.
- Sonuç review_required durumundadır; confidence modelin öz değerlendirmesidir.
- Phase 1 için 4/5 retrieval, Phase 2 için 4/5 doğru diagnosis ayrıca ölçülmeli.
  Kendi repo soruları geliştirme kontrolüdür; rapordaki kontrollü easy bug
  değerlendirmesinin yerine sessizce geçirilmez.

## Kullanıcının çalıştıracağı kontroller

```bash
./venv/bin/python -B -m unittest test_reference_checks test_repository_agent test_protocol test_agent test_evidence test_navigation test_tools
./venv/bin/python agent.py "İncelemek istediğiniz repository sorusu"
```

Canlı değerlendirmede ilk deneme saklanır; kod, model ve sorular değiştirilmeden
retrieval, doğru diagnosis, yanlış onay, süre ve çağrı sayısı ayrı kaydedilir.
Bu dosyada örnek değerlendirme sorularının cevapları bulunmaz.
