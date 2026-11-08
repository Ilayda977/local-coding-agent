# Faz 3 — Plan ve güvenli patch

## Güncel uygulama — 18 Eylül 2026

Plan-only sürümün üzerine güvenli patch akışı eklendi. `--plan` plan, `--patch`
plan ve diff üretir. `--apply` diff'e bağlı açık terminal onayından sonra tek
mevcut dosyayı atomik değiştirir. `--rollback` ayrı onay ve yeni hash kontrolüyle
geri alır. Hedef repository'nin kodu veya testleri otomatik çalıştırılmaz.

`patching.py` modelden bağımsızdır. `patch_workflow.py` yalnız gerçekten okunan
alıntıdan edit üretir. `cli.py` insan onayının sınırıdır. Snapshot, symlink,
hardlink, dış yol, yanlış onay, Python sözdizimi ve kullanıcı değişikliği
koruması modelsiz testlerle kontrol edilir. Üç küçük hata için engine seviyesinde
patch uygulama ve geri alma testleri vardır; bunlar LLM'nin üç hatayı çözdüğü
anlamına gelmez. Canlı sonuçlar IMPLEMENTATION_REVIEW.md içinde ayrılır.

Faz 3 mekanizmaları uygulanmıştır; rapordaki kabul ölçümü ayrıca kanıtlanmalıdır.
Faz 2'deki doğal dil yorum hatalarının tümünün giderildiği iddia edilmez.

Son doğrulama: 278 birim testi geçti. İzole fixture'da gerçek Qwen ile üç küçük
Python diff'i üretildi (toplama, kapasite eşitliği, bildirim tercihi). Bunlar
önizlemedir; kullanıcı dosyalarına uygulanmadı. Plan/diagnosis açıklamalarında
hatalar görüldüğünden diff incelemesi ve insan onayı zorunlu kalır. Ayrıntılı
süreler, tekrarlar ve kalan hatalar [inceleme kaydındadır](IMPLEMENTATION_REVIEW.md).

---

## Tarihsel başlangıç notları (aşağıdaki “henüz” ifadeleri eski sürüme aittir)

## İlk adım: yalnız plan önerisi

13 Eylül 2026: mevcut read-only diagnosis akışı korunuyor. `--plan` ile
başarılı biçimde sonuç üreten (`review_required`) araştırmanın ardından bir
CHANGE_PLAN çağrısı yapılır. Aynı toplam süre/çağrı bütçesi kullanılır.

- Plan tek mevcut dosyayla sınırlı; dosya adı gerçek kanıt kimliğinden gelir.
- Öneri, beklenen sonuç, risk ve kontrol yöntemi sunulur.
- `no_change` veya `insufficient_evidence` ile öneriden kaçınılabilir.
- Planlama başarısız olursa diagnosis korunur, change_plan.status unavailable olur.
  CLI'nin sıfır çıkışı plan başarısı veya patch uygulanması anlamına gelmez.
- Plan doğruluğu garanti edilmez. Özellikle yanlış diagnosis yanlış plan üretebilir.
- Onay mekanizması, apply_patch, get_diff ve rollback henüz eklenmedi.
- Bu aşamada dosya, commit, shell veya test çalıştırma yetkisi yoktur.

```bash
./venv/bin/python agent.py --plan "list_files fonksiyonunda sonuçların nasıl sıralandığını incele; bu davranışı açıklayan küçük bir docstring değişikliği öner."
./venv/bin/python -B -m unittest test_patch_protocol test_agent test_protocol test_evidence
```

Yeni testler modelsizdir; canlı model kalitesini ölçmez. İlk adımın test/model
çalıştırması bu değişiklik sırasında yapılmadı; kullanıcı kontrolü bekleniyor.

## Faz 2'den taşınan bilinen başarısızlıklar

- Sabit ilk beş soruluk sette son gözlemler: 3 doğru, 1 kısmen doğru,
  1 yanlış. 4/5 kabul ölçütü sağlanmış olarak işaretlenmez.
- sort_keys davranışını ters açıklama ve aynı modelin yanlış onayı: açık.
- Göreli/mutlak girdi ile kök altında olma kontrolünün karıştırılması: açık.
- Yardımcıyı okumadan cevap verme: doğrudan aynı-modül çağrıları için kontrol
  eklendi; bütün dinamik bağımlılıkları kapsamaz.
- Son find_file denemesinde çağıran ve yardımcı okunmuş, kaynaklar birlikte
  sunulmuş; yardımcı bir dosya listesi değil listeyi içeren sözlük döndürür.

Faz 3'e öğrenme/geliştirme amacıyla ilerleniyor. Bu karar, assignment'taki
Faz 2 kabul kaydının yerine geçmez ve kalan hataların yalnız modele ait
olduğunu ispatlamaz.
