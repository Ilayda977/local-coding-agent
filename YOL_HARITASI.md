# Durum Raporu ve Yeni Yol Haritası (8 Kasım 2026)

Bu belge iki şey içerir:
1. **Mevcut kodun dürüst incelemesi:** ne var, ne çalışıyor, neden karıştı.
2. **Yeni yol haritası:** ödev PDF'ine (6 faz) sadık, adım adım ilerleyen bir plan.

---

## 1. Mevcut durum: ne var?

| Ölçüt | Durum |
| --- | --- |
| Kod | ~4.400 satır Python (16 modül) + ~3.000 satır test |
| Birim testler | 308 test, hepsi geçiyor (`python -B -m unittest discover -p 'test_*.py'`) |
| Model | `qwen2.5-coder:7b` ve `3b` kurulu, Faz 0 tamam (MODEL_BASELINE.md) |
| Faz 1 (read-only araçlar) | Var: list_files, search_code, read_file, find_symbol, repo sınırı |
| Faz 2 (diagnosis) | Altyapı var, **kabul kriteri sağlanmadı** (kendi kaydın: 5 sorudan 3 doğru) |
| Faz 3 (patch) | Mekanizma var (onay kodu, diff, rollback), ama **commit edilmemiş** |
| Faz 4–6 | Başlanmadı: `run_tests`, test-onarım döngüsü, context ölçümü, evaluation yok |
| Ek | GitHub repo özetleme (`--summary`), ödevde yok |

Testlerin geçmesi iyi haber, ama bu testler **controller kurallarını** sınıyor;
**agent'ın bir bug'ı bulup bulmadığını** ölçmüyor. Asıl sorun burada.

---

## 2. Bulunan sorunlar (önem sırasıyla)

### Sorun 1: Agent yanlış hedef üzerinde çalışıyor (en önemlisi)
Ödev: *"Agent, `taskflow` gibi küçük bir backend'deki 15 kontrollü issue'yu çözsün."*
Mevcut proje: agent **kendi kaynak kodu hakkında soru cevaplıyor**
(`"read_file kaç satır okur?"`, `"MODEL_NAME nerede?"`).

Sonuçları:
- Ölçülecek **issue seti yok**, ground truth yok → "5 issue'nun 4'ü" ölçülemiyor.
- Agent kendi kodunu okuyor; kodu her değiştirdiğinde test soruları da değişiyor.
- Sorular "bug düzelt" değil "kod açıkla" tipinde; bu, küçük model için daha
  zor ve ölçmesi daha belirsiz bir iş.

### Sorun 2: "Agent loop" değil, sabit 8 aşamalı boru hattı
PDF'teki mimari: *model → araç seç → küçük gözlem → model → ...* (serbest döngü).
Mevcut: `LIST → ROUTE → SEARCH → SELECT → READ → ASSESS → DRAFT → VERIFY → RECOVER`.
- Her aşama ayrı bir JSON şeması ister; şemalar çalışma anında değiştiriliyor
  (`protocol.py` → `ModelGateway.ask` içinde modele özel `if` blokları).
- Bir soru için **14'e kadar model çağrısı**, 300 sn bütçe. 7B için çok ağır.
- Küçük model, 9 farklı format öğrenmek zorunda kalıyor → format hataları artıyor.

### Sorun 3: "Yama üstüne yama" — her hataya özel kural
`PHASE2_STATUS.md`'deki "Bulunan hatalar" listesinde ~30 madde var. Her canlı
denemede model yanlış yapınca, controller'a yeni bir özel kural eklenmiş
(Türkçe yazım hatası normalizasyonu, `not` koşulu zorlama, sayısal atıf kontrolü,
standart kütüphane filtresi...). Bu, birkaç **belirli soruya aşırı uyum** (overfitting)
ve kodun anlaşılmaz hale gelmesinin ana nedeni.

### Sorun 4: Kod yapısı okunamaz
- `agent.py` içindeki `run_agent` fonksiyonu **~670 satır** tek fonksiyon.
- `tools.PROJECT_ROOT` global değişken; `cli.py` onu çalışma anında değiştiriyor.
  Aynı anda iki repo ile çalışmak veya test etmek zorlaşıyor.
- 9 adet `.md` belgesi birbiriyle çelişiyor ("Faz 2 tamamlandı" / "tamamlanmadı").

### Sorun 5: Kapsam kayması (scope creep)
GitHub özetleme (`repository_summary.py`, `summary_facts.py`, `repository_source.py`
≈ 800 satır) Faz 2 kabul edilmeden eklendi. Ödevde yok. Fikir kötü değil, ama
sırası yanlış: projeyi karıştıran ikinci büyük neden bu.

### Sorun 6: Commit edilmemiş çok iş var (veri kaybı riski)
7 değiştirilmiş + 17 yeni dosya git'te değil. Faz 3'ün tamamı yalnızca diskte.

### Sorun 7: Ödevin istediği bazı kurallar eksik
- **Streaming:** model çıktısı kullanıcıya akmıyor, yalnızca nokta (`.`) basılıyor.
- **Context ölçümü:** her çağrı için token/byte loglanmıyor (Faz 5 bunu istiyor).
- **Tekrarlanan aksiyon tespiti** var ama tek aşamaya özel, genel değil.

---

## 3. Karar: Baştan mı, düzelterek mi?

**Öneri: Çekirdeği sade bir şekilde baştan kur, iyi parçaları taşı.**

Neden düzeltmiyoruz? Sorun tek tek hatalar değil, yaklaşımın kendisi. 670 satırlık
durum makinesine kural eklemeye devam etmek seni yine aynı yere getirir.
Neden sıfırdan değil? Bazı parçalar gerçekten iyi ve test edilmiş:

| Taşınacak (iyi) | Bırakılacak (arşive) |
| --- | --- |
| `tools._resolve_safe_path` (repo sınırı) | 8 aşamalı `run_agent` durum makinesi |
| `patching.py` + `patch_journal.py` (onay, diff, rollback) | `navigation.py`, `research_routing.py` |
| `terminal_safety.py` | `reference_checks.py`, `citation_checks.py` |
| Pydantic ile yapılandırılmış çıktı fikri | VERIFY (aynı modelin kendini onaylaması) |
| AST ile `find_symbol` mantığı | Türkçe soru normalizasyonu, özel kurallar |
| `repository_source.py` (sonra, bonus) | `summary_facts.py` (şimdilik) |

Eski kod **silinmeyecek**: önce `legacy-v1` adlı bir git dalına kaydedilecek.
İstediğin an geri dönebilirsin.

---

## 4. Yeni mimari (PDF Bölüm 6'ya birebir)

```text
ISSUE (ör. "Görev tamamlanınca bildirim gitmiyor")
   ↓
AGENT LOOP  (en fazla 8 adım, aynı çağrı 2. kez → engelle)
   ↓  model bir araç seçer (Ollama native tool calling)
   ├─ list_files(dir)
   ├─ search_code(query)
   ├─ find_symbol(name)
   └─ read_file(path, start, end)   ← en fazla 80 satır
   ↓  küçük gözlem modele geri döner
MODEL "yeterli" der → DIAGNOSIS (JSON şema)
   ↓  controller kontrol: dosya var mı? satırlar okundu mu?
PLAN → kullanıcı onayı → PATCH → run_tests → (en fazla 2 onarım) → RAPOR
```

Hedef dosya yapısı:

```text
local-coding-agent/
├── lca/                 # agent'ın kendisi
│   ├── config.py        # model adı, limitler (tek yerde)
│   ├── tools.py         # 4 read-only araç + repo sınırı  (Repo nesnesi, global yok)
│   ├── llm.py           # Ollama çağrısı, streaming, şema + 1 retry
│   ├── loop.py          # agent döngüsü (~150 satır hedef)
│   ├── diagnosis.py     # Diagnosis şeması + kanıt doğrulama
│   ├── patch.py         # (Faz 3) eski patching.py'den
│   ├── testing.py       # (Faz 4) run_tests allowlist
│   └── cli.py
├── taskflow/            # üzerinde çalışılacak örnek backend (+ tests/)
├── eval/
│   ├── issues/          # 15 issue: easy_01.json ... (+ ground truth)
│   └── run_eval.py      # tüm issue'ları çalıştır, tablo üret
├── tests/               # agent'ın birim testleri
└── README.md, MODEL_BASELINE.md, ARCHITECTURE.md
```

---

## 5. Yol haritası (adım adım)

Her adımın sonunda: çalışan bir sürüm, geçen testler, bir commit ve
**senin kendi cümlelerinle açıklayabileceğin** bir kavram.

### Adım 0 — Temizlik ve güvenceye alma (½ gün) ✅ 8 Kasım 2026
- Mevcut her şeyi `legacy-v1` dalına commit et, `main`'i sadeleştir.
- Eski kodu ve `.md` belgelerini `legacy/` klasörüne taşı.
- **Öğrenilecek:** git dalı, neden önce yedek.

### Adım 1 — Örnek repo: `taskflow` + 5 easy issue (1 gün) ✅ 8 Kasım 2026
- Mentör repo vermediği için birlikte yazıldı: `taskflow/` — 20 kaynak dosya,
  ~790 satır, 49 test (parametreli testler dahil). Temiz kodda hepsi geçiyor.
- 5 kolay bug: `eval/issues/easy_01..05.json` (issue metni, bug, ground truth,
  kırılması beklenen testler). Bug'lar repoda **değil**, JSON'da durur;
  `eval/issues.py prepare <id>` temiz kopyaya enjekte eder.
- `python eval/issues.py check` → temiz repo yeşil, her bug yalnız kendi testini kırıyor.
- Not: PDF 2.000–4.000 satır hedefliyor. Repo, medium/hard issue'lar eklenirken
  (Adım 8 öncesi) büyütülecek; şimdilik easy issue'lar için yeterli.
- **Öğrenilecek:** benchmark tasarımı; "ölçemediğin şeyi geliştiremezsin".

### Adım 2 — Faz 1: Araçlar ve repo sınırı (1 gün)
- `lca/tools.py`: `Repo(root)` sınıfı; 4 araç; dışarı çıkan yol → hata.
- Birim testler: `../`, mutlak yol, symlink reddi; 80 satır sınırı.
- **Öğrenilecek:** filesystem boundary, tool schema.

### Adım 3 — Faz 1: Agent döngüsü (1–2 gün)
- `lca/loop.py`: Ollama `tools=` ile native tool calling, step limit 8,
  tekrar eden çağrı engeli, her adımı `trace.jsonl`'a yaz.
- Kabul: 5 easy issue'nun **en az 4'ünde** doğru dosyayı bulma (eval script ölçer).
- **Öğrenilecek:** agent loop, observation, mentor için diyagram (Checkpoint B).

### Adım 4 — Faz 2: Diagnosis (2 gün)
- Döngü sonunda `issue_summary, evidence[file, start, end], root_cause,
  relevant_files, confidence` şeması.
- Controller kontrolü: atıf yapılan dosya/satır **gerçekten okunmuş** olmalı;
  değilse modele "önce oku" gözlemi ver (en fazla 1 tur).
- Kabul: 5 easy issue'da **en az 4 doğru diagnosis**.
- **Öğrenilecek:** structured output, hallucination control.

### Adım 5 — Faz 3: Plan + güvenli patch (3 gün)
- Eski `patching.py`'yi `lca/patch.py`'ye taşı (zaten iyi ve test edilmiş).
- `old_text → new_text` küçük edit; diff göster; onaysız yazma yok.
- Kabul: en az 3 easy bug için sözdizimi geçerli patch.
- **Öğrenilecek:** human-in-the-loop, rollback (Checkpoint C).

### Adım 6 — Faz 4: Test geri bildirimi (3 gün)
- `run_tests(test_path)`: yalnız `pytest taskflow/tests/...` (allowlist, timeout).
- Fail çıktısı → modele gözlem → en fazla 2 onarım → temiz durma + rapor.
- Kabul: sonsuz döngü yok; 3 easy issue'da test ile çözüm denendi.
- **Öğrenilecek:** environment feedback, repair loop.

### Adım 7 — Faz 5: Context optimizasyonu (2 gün)
- Her çağrıda prompt token'ını logla; eski gözlemleri kısa özetle değiştir.
- Aynı 5 issue'yu önce/sonra çalıştır, tabloyu karşılaştır (Checkpoint D).

### Adım 8 — Faz 6: Final evaluation (1 hafta)
- 15 issue (5 easy / 5 medium / 5 hard), temiz repo state'ten, 3B vs 7B.
- Metrikler: retrieval, diagnosis, valid patch, test pass, autonomous success,
  adım sayısı, context maliyeti, engellenen aksiyon.
- 3 failure-case analizi, demo, 5–7 slayt.

### Bonus (v1.0 sonrası) — GitHub repo özetleme
Çekirdek bittikten sonra eski `repository_source.py`'yi kullanarak `--repo URL`
desteği ve aynı döngüyle "bu repoyu özetle" modu. Ayrı bir pipeline değil,
**aynı agent'ın farklı bir görevi** olarak.

---

## 6. Çalışma kuralları (tekrar karışmasın diye)

1. **Bir adım bitmeden diğerine geçme.** Kabul kriteri = eval scriptinin çıktısı.
2. **Model hata yapınca önce özel kural ekleme.** Önce şunlara bak: araç açıklaması
   mı belirsiz, gözlem mi çok büyük, issue metni mi muğlak? Başarısız issue bir
   veri noktasıdır, saklanmaz.
3. **Her adım sonunda commit.** Mesajda adım numarası: `Adım 3: agent loop`.
4. **Tek durum belgesi:** `README.md` + bu dosya. Faz başına ayrı belge yok.
5. **Her yeni kavramı kendi cümlelerinle** bu dosyanın sonuna bir paragraf yaz.

---

## 7. İlerleme günlüğü (ölçümler `eval/results/` altında)

| Adım | Sonuç | Kanıt |
| --- | --- | --- |
| 2 – Araçlar | 4 araç + repo sınırı, birim testlerle doğrulandı | `tests/test_tools.py` |
| 3 – Agent döngüsü | 7B: doğru dosyayı okuma **5/5** (kriter ≥4/5 ✅) | `step3_research_7b.md` |
| 4 – Diagnosis | 7B, tam sohbet geçmişiyle **1/5**; durum özetiyle (compact) **3/5**. Kriter ≥4/5 ❌ (dürüst kayıt) | `step4_diagnosis_7b.md`, `step4_state_7b.md` |
| 5 – Plan + patch | 7B: sözdizimi geçerli ve uygulanmış patch **5/5** (kriter ≥3 ✅); onarımsız testler 2/5 | `step5_patch_7b.md` |
| 6 – Test + onarım | Sonsuz döngü yok (tüm döngüler sınırlı + 40 çağrı freni) ✅; 3 issue'da test geri bildirimiyle onarım denendi ✅. İki ölçümde testler 3/5 ve 2/5 geçti (model değişkenliği). Uydurma ad koruması `task.completed`'ı 4 kez engelledi | `step6_repair_7b.md`, `step6_easy04_hint.md` |
| 7 – Context | 5 kolay issue, aynı kod: tam sohbet → durum özeti. Diagnosis 1/5 → 4/5, otonom 1/5 → 2/5, en büyük araştırma prompt'u 3103 → 2456 token (−21%), toplam token ≈ aynı (12.7k → 13.0k). Bedeli: çağrı başına 6.2 → 8.7 sn (KV cache yeniden kullanılamıyor). Kriter: daha az context + başarı düşmedi ✅; hız biraz kötüleşti (dürüst kayıt) | `step7_chat_7b.md`, `final_7b.md` |
