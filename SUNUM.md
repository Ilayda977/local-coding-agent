# Teknik sunum (6 slayt)

Her slayt için: başlık, ekrana konacaklar, söylenecekler. Sayılar
`eval/results/` altındaki gerçek ölçümlerden alındı.

---

## Slayt 1: Problem

**Ekranda:** "16 GB M3 + 7B yerel model = repository seviyesinde bug düzelten agent?"

- Bulut modelini kopyalamak değil; küçük bir modeli **araçlar, küçük context
  ve sıkı bir controller** ile işe yarar hale getirmek.
- Araştırma sorusu: bütün repoyu prompt'a koymadan, arayıp okuyarak, onaylı
  patch ve test geri bildirimiyle ne kadar ilerleyebilir?

## Slayt 2: Mimari

**Ekranda:** README'deki akış diyagramı.

- Model **önerir** (sıradaki araç, diagnosis, patch), controller **karar verir**
  (yol güvenliği, kanıt kontrolü, onay, limitler).
- 4 okuma aracı + `run_tests`; shell yok, test dosyası değiştirmek yok,
  onaysız yazma yok, her döngü sınırlı (toplam ≤ 40 model çağrısı).

## Slayt 3: Yerel model kısıtı

**Ekranda:** MODEL_BASELINE.md özeti + tek prompt büyüklüğü.

- `qwen2.5-coder:7b` Q4_K_M ≈ 4.7 GB, `num_ctx=8192`; bellek yeşil bölgede.
- Native tool calling bu modelde güvenilir değildi → **JSON şemalı çıktı +
  Pydantic doğrulama + 1 düzeltme hakkı**.
- En büyük tek prompt ortalama ~2.1 bin token; issue başına toplam ~15 bin token
  (15 issue ortalaması). 297 çağrıda tek bir bozuk JSON yok.

## Slayt 4: Araçlar ve context mühendisliği

**Ekranda:** önce/sonra tablosu (Adım 4 ve 7).

- Ölçerek yapılan iyileştirmeler: repo haritası, aramada "hangi fonksiyonun
  içinde", küçük okumayı fonksiyona genişletme, okunan kodun birleştirilmesi,
  sohbet geçmişi yerine **durum özeti**.
- Örnek: diagnosis 1/5 (tam sohbet geçmişi) → 3/5 (durum özeti + temiz bağlam).

## Slayt 5: Değerlendirme

**Ekranda:** `eval/summarize.py final_7b final_3b` tablosu.

- 15 issue (5 kolay / 5 orta / 5 zor), her biri temiz kopyada, testleri
  değerlendirici çalıştırır.
- Metrikler: retrieval, diagnosis, geçerli patch, test, otonom başarı, adım,
  token, süre, engellenen aksiyon.
- 3B ve 7B aynı düzenekte.

| | retrieval | diagnosis | geçerli patch | otonom | ort. süre |
|---|---|---|---|---|---|
| 7B | 13/15 | 8/15 | 12/15 | **5/15** (kolay 2, orta 2, zor 1) | 141 sn |
| 3B | 9/15 | 4/15 | 7/15 | 1/15 | 46 sn |

## Slayt 6: Hatalar ve sonuç

**Ekranda:** failure taxonomy (F0–F5) ve 3 örnek.

- En sık kırılma yeri: dosyayı bulmak değil, **okuduğu kodu doğru yorumlamak**
  (7B'de 10 başarısızlığın 5'i F3 misdiagnosis).
- Örnekler: "kullanılmayan regex" (easy_01), uydurma `task.completed` (easy_04),
  olayın atamadan önce yayınlanması (hard_04).
- Controller'ın yakaladığı hatalar: uydurma `task.completed`, okunmamış kanıt,
  repo dışı yol. Hiçbiri diske ulaşmadı.
- Sonuç: küçük model + iyi sistem tasarımı, kolay bug'larda kullanılabilir;
  zorlarda insan gözetimi şart. Başarısız vakalar saklanmadı.
