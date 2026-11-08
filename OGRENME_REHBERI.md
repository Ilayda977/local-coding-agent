# Öğrenme Rehberi: Local Coding Agent'ı satır satır anlamak

Bu belge, projeyi kendi başına anlayabilmen ve mentörüne anlatabilmen için
yazıldı. Her dosyanın **ne işe yaradığını**, içindeki önemli fonksiyonları,
**neden böyle yazıldığını** ve ödevdeki hangi kavramı öğrettiğini sırayla
anlatıyor. Okuma sırası önerisi: 1 → 2 → 3, sonra 4'teki modülleri
kodla yan yana açarak oku.

---

## 1. Büyük resim (5 dakikada)

Problem: 7B'lik küçük bir model, bütün repository'yi okuyup bug çözemez.
Hem context'e sığmaz hem de kafası karışır.

Çözüm: Büyük işi **küçük kararlara** bölüyoruz. Model her adımda yalnızca
şunu söylüyor: *"Şimdi hangi araçla neye bakayım?"* Aracı model değil,
**controller** (bizim Python kodumuz) çalıştırıyor ve sonucu kısa bir
**gözlem** (observation) olarak modele geri veriyor. Bu tekrar eden
karar → araç → gözlem döngüsüne **agent loop** denir.

```
Bug raporu
   │
   ▼
ARAŞTIRMA DÖNGÜSÜ (en fazla 12 adım)      lca/research.py
   model: "find_symbol('is_overdue')"
   controller: güvenle çalıştır → "tasks/service.py:96-101 def is_overdue"
   model: "read_file('tasks/service.py', 96, 101)"
   controller: satırları ver (+ ipuçları)
   model: "finish"
   │
   ▼
DIAGNOSIS (kanıtlı açıklama)               lca/diagnosis.py
   controller kontrol eder: kanıt satırları gerçekten okundu mu?
   │  hayır → modeli 4 adımlığına araştırmaya geri gönder
   ▼
PLAN + PATCH ÖNERİSİ (old_text → new_text) lca/patching.py
   controller kontrol eder: küçük mü, test dosyası mı, uydurma isim var mı?
   │
   ▼
İNSAN ONAYI ("yes" yazılmadan hiçbir dosya değişmez)   lca/cli.py
   │
   ▼
run_tests (yalnız pytest, shell yok)       lca/testing.py
   │ kaldı → hata satırlarını modele ver, en fazla 2 onarım
   │ hâlâ kaldı → dosyaları geri al (rollback), dürüstçe raporla
   ▼
RAPOR (JSON)                               lca/agent.py
```

**Altın kural:** Model *önerir*, controller *karar verir*. Dosya yolu,
satır numarası, yazma izni, döngü sınırı gibi güvenlik ve doğruluk
kuralları hiçbir zaman modelin "iyi niyetine" bırakılmaz.

---

## 2. Klasör yapısı

```
local-coding-agent/
├── lca/                 ← AGENT
│   ├── config.py        bütün limitler (adım sayısı, satır sınırı…)
│   ├── tools.py         4 okuma aracı + repo sınırı + repo haritası
│   ├── llm.py           Ollama ile konuşan tek yer (JSON şema, streaming, token sayımı)
│   ├── prompts.py       modele söylenen her şey
│   ├── research.py      agent loop
│   ├── context.py       modele her adımda ne gösterileceği (Faz 5)
│   ├── diagnosis.py     kanıtlı diagnosis + kontrolü
│   ├── patching.py      plan, patch doğrulama, onay sonrası yazma, rollback
│   ├── testing.py       run_tests (allowlist)
│   ├── agent.py         hepsini sırayla çağıran orkestra şefi
│   └── cli.py           terminal arayüzü (python -m lca)
├── tests/               ← agent'ın testleri (sahte model ile)
├── taskflow/            ← agent'ın üzerinde çalıştığı örnek backend
├── eval/
│   ├── issues/*.json    15 issue (metin + bug + doğru cevap)
│   ├── issues.py        bug'lı kopya hazırlama, veri seti kontrolü
│   ├── metrics.py       bir raporu metriklere çevirme
│   ├── run_eval.py      bütün issue'ları çalıştırıp tablo üretme
│   └── results/         ölçüm sonuçları
└── legacy/              eski mimari (arşiv)
```

---

## 3. Bir issue'nun yolculuğu (gerçek bir çalıştırma)

Issue `easy_05`: *"Bir bildirimi okundu işaretledikten sonra okunmamış
sayısı azalmıyor."* Aşağıdakiler gerçek 7B çalıştırmasının kaydı
(`eval/results/final_7b.json`):

1. `eval/issues.py prepare easy_05` temiz `taskflow/`'u `eval/workspace/easy_05`'e
   kopyalar ve `notifications/service.py` içindeki
   `return [n for n in self.for_user(user_id) if not n.read]` satırını
   `return self.for_user(user_id)` yapar (bug'ı enjekte eder).
2. Model ilk mesajda bug raporunu ve **repo haritasını** görür
   (`notifications/service.py: class NotificationService(notify, for_user, unread, unread_count, mark_read, …)`).
3. Araştırma (5 adım): `find_symbol('mark_read')` → `read_file(42-47)` →
   `search_code('unread')` → `read_file(35-47)` → aynı satırları tekrar okumak
   istedi; controller bunu "tekrar" saydı ve araştırma bitti.
4. Diagnosis: *"The `unread` method does not filter out read notifications,
   causing the `unread_count` method to include read notifications in the count."*
   Kanıt `notifications/service.py:35-37` ve `40-42`. Controller bu satırların
   gerçekten okunduğunu doğruladı ve satırların gerçek metnini diskten kopyaladı.
5. Patch önerisi: `return self.for_user(user_id)` →
   `return [n for n in self.for_user(user_id) if not n.read]`. Controller:
   dosya okunmuş ✓, test dosyası değil ✓, tek yerde geçiyor ✓, 1 satır ✓,
   `ast.parse` ✓, yeni adların hepsi repoda var ✓.
6. Onay (değerlendirmede otomatik, CLI'da sen `yes` yazarsın) → atomik yazma.
7. `run_tests` → `72 passed` → durum `fixed`. Onarım gerekmedi.

---

## 4. Modül modül açıklama

### 4.1 `lca/config.py`: bütün sayılar tek yerde

`Settings` adlı **dondurulmuş** (frozen) bir dataclass. İçinde model adı,
`num_ctx=8192`, `max_steps=12`, `max_read_lines=80`, `max_repairs=2`,
`max_model_calls=40` gibi değerler var.

- **Neden tek yer?** Eski projede limitler dosyalara dağılmıştı; neyin neden
  durduğunu bulmak zordu. Şimdi hepsi burada ve yorumlarıyla yazılı.
- **Neden frozen?** Çalışma sırasında biri yanlışlıkla bir limiti değiştiremesin.
- `load_settings()`: önce varsayılanlar, sonra `LCA_MODEL` gibi ortam
  değişkenleri, en son komut satırı. Böylece 3B/7B karşılaştırması kod
  değiştirmeden yapılabiliyor.
- **Kavram:** *deterministic guardrails*: sınırları kod koyar, model değil.

### 4.2 `lca/tools.py`: model ile dosya sistemi arasındaki kapı

`Repo` sınıfı tek bir repository'yi ve agent'ın orada **ne okuduğunu**
(`reads` listesi) tutar.

| Fonksiyon | Ne yapar | Neden önemli |
| --- | --- | --- |
| `resolve(path)` | Modelin verdiği yolu gerçek yola çevirir; repo dışına çıkıyorsa `ToolError` | Güvenliğin kalbi. `../`, `/etc/passwd`, dışarı giden symlink burada yakalanır. Reddedilenler `blocked` listesine yazılır (metrik). |
| `list_files` | Klasördeki kaynak dosyalarını sıralı listeler | `venv`, `.git` gibi klasörler atlanır |
| `search_code(query)` | Satır satır, büyük/küçük harf duyarsız arama | Her sonuçta **hangi fonksiyonun içinde** olduğu yazar: ilk canlı denemede model doğru satırı bulup ne okuyacağını bilemediği için eklendi |
| `find_symbol(name)` | Python AST ile tanım arar (`def`, `class`, sabitler, `Class.method`) | Metin aramasından daha isabetli; "yakın isimler" önerir |
| `read_file(path, start, end)` | Numaralı satırları verir, en fazla 80 | **Küçük okumayı genişletir:** model 5 satır isteyince fonksiyonun tamamını verir; altına "bu satırların kullandığı ama başka yerde tanımlı adlar" ipucunu ekler |
| `repo_map()` | Her dosya + içindeki sınıf/fonksiyon/SABİT adları | Ödevdeki "repo map" önerisi. ~500 token ile modelin nereye bakacağını bilmesini sağlar |
| `was_read(path, a, b)` | Bu satırların hepsi okundu mu? | Diagnosis ve patch kontrolünün temeli |
| `code_pack()` | Okunan her şeyi dosya başına birleştirir | Diagnosis'e temiz bağlam olarak verilir |
| `known_names()` | Repodaki koddaki bütün adlar (string ve yorumlar hariç) | Patch'in uydurduğu `task.completed` gibi adları yakalar |
| `run_tool(repo, tool, args)` | Modelin seçtiği aracı çağırır | `relevant_args` ile model "fazladan" argüman gönderse de doğru çalışır |

**Kavramlar:** filesystem boundaries, tool schema, context engineering,
observation. **Neden araçlar düz metin döndürüyor?** Küçük model JSON
içindeki kaçışlı kodu okumakta zorlanıyor; numaralı satırlar en okunur hali.

### 4.3 `lca/llm.py`: Ollama ile konuşan tek yer

- `chat_json(messages, schema, stage, model_cls)`: Ollama'ya
  `format=<JSON şeması>` ile istek atar. Bu **structured output** demek:
  model, şemaya uymayan çıktı üretemez (grammar ile kısıtlanır).
  Gelen cevap ayrıca **Pydantic** ile doğrulanır. Bozuksa model, hatasıyla
  birlikte **bir kez daha** denenir (ödevdeki "schema validation + retry").
- **Neden Ollama'nın yerleşik tool calling'i değil?** Denedik:
  `qwen2.5-coder:7b` aracı `tool_calls` alanına değil, düz metin olarak
  yazdı. Şemalı çıktı daha güvenilir çıktı.
- `stream=True`: cevap parça parça gelir, CLI bunu canlı gösterir (ödevdeki
  "boş ekran görmesin" kuralı).
- Her çağrı için `CallRecord` tutulur: aşama, prompt token, çıktı token, süre.
  `usage()` bunları toplar (Faz 5'in ölçümü).
- `max_model_calls`: bir çalıştırma ne olursa olsun 40 model çağrısını
  geçemez. **Sonsuz döngüye karşı son fren.**
- `warm_up()`: değerlendirmeden önce modeli belleğe yükler, böylece ilk issue
  haksız yere yavaş ölçülmez.

### 4.4 `lca/prompts.py`: modele söylenen her şey

Bütün talimatlar tek dosyada, böylece "modele ne söyledin?" sorusunun cevabı
burada. Önemli kararlar:

- Talimatlar **kısa** ve madde madde. 7B, 30 kuraldan çok 5 net kurala uyuyor.
- `RESEARCH_SYSTEM` içinde **başka bir projeden küçük bir örnek** gezinti var
  (few-shot): ara → fonksiyonu oku → bağlı olduğu değeri oku → bitir.
  Küçük modeller iyi bir örneği taklit etmekte başarılı.
- Örnekler bilinçli olarak **taskflow'dan alınmadı**. Bir ara yanlışlıkla
  bir bug'ın cevabını örneğe yazmıştım; fark edip değiştirdim. Aksi halde
  ölçüm hile olurdu.
- `DIAGNOSIS_SYSTEM`: tipik bug türlerini sayar (karşılaştırma operatörü,
  sıralama yönü, eksik koşul, tablodaki yanlış giriş…). Bu cevap değil,
  "nereye dikkat et" listesi.

### 4.5 `lca/research.py`: agent loop

`run_research()` ödevin Faz 1'idir. Her adımda:

1. Modelden bir `Action` ister: `{"thought", "tool", "args"}`.
   `ACTION_SCHEMA` araç adını `enum` ile sınırlar (model uydurma araç adı
   yazamaz) ve `thought`'u 200 karakterle sınırlar. Bu sınır, uzun yazınca
   JSON'un yarıda kesildiği bir hatadan sonra eklendi.
2. Controller kuralları:
   - **Okumadan `finish` yok** → "refused".
   - **Aynı çağrı ikinci kez çalışmaz**; zaten okunmuş satırları tekrar okumak
     da tekrar sayılır → "repeated" + ne yapması gerektiğini söyleyen mesaj.
   - **Üst üste 2 tekrar** = model takıldı → araştırma temiz biçimde biter.
   - **Adım limiti** (`max_steps`).
   - Araç hatası (repo dışı yol vb.) çökme değil, gözlem olur: `ERROR: ...`.
   - Uzun gözlem `max_observation_chars`'ta kesilir.
3. Her adım `Step` olarak kaydedilir (rapor + değerlendirme için).

`run_research` ikinci kez `research=` ve `feedback=` ile çağrılırsa aynı
araştırmaya **devam eder**. Diagnosis reddedildiğinde böyle kullanılır.

**Kavramlar:** agent loop, step budget, repeated-action detection.

### 4.6 `lca/context.py`: modele her adımda ne gösteriyoruz? (Faz 5)

İki mod var (`compact_history` ayarı):

- **chat**: bütün konuşma her seferinde gönderilir. Basit, ama 8. adımda model
  kendi eski tahminlerini ve aynı kodu tekrar tekrar okur.
- **state** (varsayılan): her adımda tek, taze bir mesaj gönderilir. İçinde
  bug raporu + repo haritası + yapılan adımların **tek satırlık özetleri** +
  okunan kodun birleşik hali + yalnızca **son** sonucun tamamı bulunur.

Ölçüm (bölüm 6) bu farkı sayılarla gösteriyor. **Kavram:** state
summarization, context budgeting.

### 4.7 `lca/diagnosis.py`: kanıtlı açıklama (Faz 2)

Şema: `analysis, issue_summary, root_cause, relevant_files, evidence[file,
start_line, end_line, why], confidence`.

- `analysis` **ilk alan**: model önce senaryoyu kod üzerinde adım adım izler,
  sonra kök nedeni yazar ("önce düşün" alanı).
- `confidence` bir **kelime** (low/medium/high), yüzde değil. Modelin "0.87"
  demesi olduğundan daha kesin görünürdü.
- `ask_diagnosis()` modele bütün sohbet geçmişini değil, **issue + okunan
  kodun birleşimini** verir. Sebebi: model önceki yanlış tahminlerini
  ("sıralama doğru görünüyor") son karara taşıyordu (anchoring).
- `check()` controller kontrolü, **halüsinasyon kontrolü**:
  - kanıt dosyası repoda var mı, satır aralığı geçerli mi,
  - aralık en fazla 30 satır mı (bütün dosyayı göstermek kanıt değildir),
  - **bu satırlar gerçekten okundu mu?** (`repo.was_read`),
  - kök nedende geçen `foo()`, `Foo.bar`, `` `x` `` gibi adlar repoda var mı?
  - Başarılıysa kanıt satırlarının **gerçek metni diskten kopyalanır**;
    kullanıcı hiçbir zaman modelin "hatırladığı" kodu görmez.

### 4.8 `lca/patching.py`: plan → diff → onay → yazma → geri alma (Faz 3)

Model yalnızca şunu döndürür: `{"plan": "...", "edits": [{"file", "old_text",
"new_text"}]}`. Diske dokunan her şey burada ve şu kontrollerden sonra:

| Kontrol | Neden |
| --- | --- |
| Dosya repo içinde, var, okunmuş | Görmediği kodu değiştiremez |
| **Test dosyası değil** | Testler şartnamedir; testi "düzeltmek" hiledir |
| `old_text` tam bir kez geçiyor | Belirsiz yere yazmayız |
| Girinti toleransı (`replace_once`) | Küçük modeller kodu doğru, boşlukları yanlış kopyalıyor |
| Değişen satır ≤ 40, tüm dosya yazımı yok | "Küçük diff tercih et" kuralı |
| `ast.parse` | Sözdizimi bozuk patch diske yazılmaz |
| `invented_names` | `task.completed` gibi repoda olmayan adlar reddedilir (canlı denemede yakalanan hata) |

`PatchSet`:
- `diff()` = ödevdeki **get_diff** aracı (unified diff).
- `apply()` = **apply_patch**: önce dosyanın okunduğundan beri değişmediğini
  kontrol eder, sonra **atomik** yazar (geçici dosya + `os.replace`). Yarım
  dosya kalmaz.
- `rollback()`: orijinal baytları geri yazar. Patch'ten sonra dosyayı biri
  elle değiştirmişse **geri almayı reddeder** (senin işini silmez).

**Kavramlar:** planning vs execution, patch/diff, human-in-the-loop,
permission design, rollback.

### 4.9 `lca/testing.py`: run_tests (Faz 4)

Komut sabit: `python -m pytest -q --tb=line -rf -p no:cacheprovider [hedefler]`.
- Liste olarak çalıştırılır (`subprocess.run([...])`), **shell yok**; enjekte
  edilecek bir komut satırı yok.
- Hedefler yalnızca repo içindeki test dosyaları olabilir; `--flag` reddedilir.
- `timeout`: asılı kalan test agent'ı asılı bırakamaz.
- `brief`: her hata için tek satır (`tasks/workflow.py:31: ValidationError: …`).
  Modele uzun traceback yerine bu verilir.

**Kavramlar:** environment feedback, allowlist, timeout.

### 4.10 `lca/agent.py`: orkestra şefi

`run()` aşamaları sırayla çağırır ve **rapor sözlüğü** üretir. Durumlar:
`diagnosed`, `insufficient_evidence`, `patch_unavailable`,
`patch_not_approved`, `fixed`, `tests_failed`, `model_error`.

Döngülerin hepsi sınırlı: araştırma ≤ 12 adım, diagnosis düzeltmesi ≤ 1,
patch denemesi ≤ 2, onarım turu ≤ 2, toplam model çağrısı ≤ 40. Yani agent
**matematiksel olarak sonsuz döngüye giremez**.

`_fix()` içindeki akış: patch → onay → uygula → test → (onarım → onay →
uygula → test)×2 → geçtiyse `fixed`, geçmediyse `rollback` + `tests_failed`.
`reproduce_first` ayarı açıksa araştırmadan **önce** testler çalıştırılır ve
kırılan testler modele gösterilir (bir geliştiricinin yaptığı gibi).

### 4.11 `lca/cli.py`: terminal arayüzü

`python -m lca --repo YOL [--fix] [--yes] [--model M] [--json] "issue"`.
- Model çıktısını canlı (soluk renkte) gösterir, her adımı numaralar.
- `approve()`: planı ve renkli diff'i gösterir, **`yes` yazmanı** bekler.
  Terminal yoksa (ör. pipe) asla uygulamaz.

### 4.12 `tests/`: modeli olmayan testler

`tests/fakes.py` içindeki `FakeClient` Ollama'nın yerine geçer: her test,
"modelin" vereceği cevapları sırayla yazar. Böylece **controller'ın**
davranışı (limitler, reddetmeler, onay, rollback) deterministik olarak test
edilir. Model kalitesi ise ayrı ölçülür (`eval/`). Bu ayrım önemli:
**birim testlerin geçmesi modelin başarılı olduğu anlamına gelmez.**

### 4.13 `taskflow/`: örnek backend

users / projects / tasks / comments / notifications / reports / activity
modülleri, olaylarla (`events.py`) birbirine bağlı. Bilerek modüller arası
ilişki kuruldu (görev atanınca bildirim, üye çıkarılınca görevler boşa
düşer…) ki orta/zor bug'lar birden fazla dosya gerektirsin.

### 4.14 `eval/`: ölçüm düzeneği

- `issues/*.json`: her issue'da agent'ın göreceği `issue` metni, temiz koda
  uygulanacak `bug` (bul → değiştir), `ground_truth` (dosyalar, kök neden,
  düzeltme, anahtar kavramlar) ve kırılması beklenen testler.
- `issues.py check`: temiz repo yeşil mi, her bug **yalnızca** kendi
  testlerini kırıyor mu? (Veri seti yanlışsa bütün ölçüm yanlıştır.)
- `metrics.py`: retrieval, diagnosis (kanıt bug satırına ±2 yakın **ve** kök
  neden anahtar kavramları içeriyor), valid_patch, tests_pass (**testleri
  değerlendirici kendisi çalıştırır**, agent'ın iddiasına güvenmez),
  autonomous, adım, token, süre, reddedilen aksiyonlar.
- `run_eval.py`: her issue için temiz kopya → agent → metrik → tablo.
  `--rescore` ile model çağırmadan yeniden puanlama.

---

## 5. Kavramlar sözlüğü (ödevin 12. bölümü)

| Kavram | Projede nerede |
| --- | --- |
| Local LLM inference, quantization | Ollama + `qwen2.5-coder:7b` (Q4_K_M, ~4.7 GB), `MODEL_BASELINE.md` |
| Unified memory, context length | `num_ctx=8192`; en büyük tek prompt rapora yazılır |
| Agent loop | `research.py` |
| Tool/function calling, tool schema | `ACTION_SCHEMA`, `TOOL_DOCS`, `run_tool` |
| Structured outputs | `llm.chat_json` + Pydantic |
| Filesystem safety | `Repo.resolve`, test dosyası yasağı, atomik yazma |
| Code search | `search_code`, `find_symbol`, `repo_map` |
| Evidence-grounded reasoning, hallucination control | `diagnosis.check`, `invented_names` |
| Human-in-the-loop | `cli.approve`, `agent._approved` |
| Patch/diff, rollback | `PatchSet.diff/apply/rollback` |
| Test feedback, repair loop | `testing.py`, `agent._fix` |
| State management, summarization | `context.py` |
| Latency/quality trade-off | 3B vs 7B, chat vs state ölçümleri |
| Agent evaluation, failure analysis | `eval/`, bölüm 6–7 |

---

## 6. Ölçümler

Bütün sayılar `eval/results/` altındaki JSON dosyalarından, `eval/summarize.py`
ile üretildi. Her issue temiz bir kopyada çalıştı; testleri **değerlendirici**
çalıştırdı. Bir uyarı: aynı ayarlarla bile 7B her çalıştırmada biraz farklı
yollar seçebiliyor. Bu yüzden 5 issue'luk ölçümlerde ±1 oynama normal.

### 6.1 Final: 15 issue, 7B (`final_7b`)

| zorluk | n | retrieval | diagnosis | geçerli patch | testler geçti | otonom | ort. toplam token | ort. en büyük prompt | ort. süre |
|---|---|---|---|---|---|---|---|---|---|
| easy | 5 | 5/5 | 4/5 | 4/5 | 2/5 | 2/5 | 13 001 | 2 042 | 127 sn |
| medium | 5 | 4/5 | 2/5 | 5/5 | 2/5 | 2/5 | 17 277 | 2 125 | 140 sn |
| hard | 5 | 4/5 | 2/5 | 3/5 | 1/5 | 1/5 | 15 267 | 2 147 | 156 sn |
| **hepsi** | 15 | **13/15** | **8/15** | **12/15** | **5/15** | **5/15** | 15 182 | 2 104 | 141 sn |

Çözülenler: easy_02, easy_05, medium_02, medium_05, hard_05.

### 6.2 Model boyutu: 3B (`final_3b`)

| zorluk | retrieval | diagnosis | geçerli patch | otonom | ort. süre |
|---|---|---|---|---|---|
| easy | 4/5 | 3/5 | 3/5 | 1/5 | 47 sn |
| medium | 2/5 | 0/5 | 2/5 | 0/5 | 53 sn |
| hard | 3/5 | 1/5 | 2/5 | 0/5 | 39 sn |
| **hepsi** | 9/15 | 4/15 | 7/15 | **1/15** | **46 sn** |

3B yaklaşık **3 kat hızlı**, ama 15 issue'nun 6'sında bug'lı dosyayı hiç
okumadı (7B'de bu 2). Yani 3B, controller ve araç geliştirirken hızlı deneme
için iyi; asıl iş için 7B gerekli. Bu, MODEL_BASELINE.md'deki "7B ana model"
kararını ölçümle doğruluyor.

### 6.3 Context optimizasyonu (Faz 5): aynı 5 kolay issue

| | tam sohbet (`step7_chat_7b`) | durum özeti (`final_7b`, kolaylar) |
|---|---|---|
| diagnosis | 1/5 | **4/5** |
| otonom çözüm | 1/5 | **2/5** |
| araştırmada en büyük tek prompt | 3 103 token | **2 456** (−21%) |
| çağrı başına ort. prompt | 1 786 | 1 697 |
| issue başına toplam token | 12 709 | 13 001 (≈ aynı) |
| çağrı başına süre | **6.2 sn** | 8.7 sn |

Durum özeti daha küçük bir pencereyle **daha doğru** çalışıyor. Bedeli
hızda: tam sohbet modunda Ollama bir önceki prompt'un önbelleğini (KV cache)
kullanabiliyor, durum özetinde her prompt yeni olduğu için kullanamıyor.
Kabul kriteri ("daha az context, başarı düşmeden") sağlandı; "hız hissi"
biraz kötüleşti. Bunu saklamıyoruz.

### 6.4 Adım adım ilerleme (aynı 5 kolay issue, 7B)

| Adım | Ne eklendi | Sonuç |
|---|---|---|
| 3 | agent loop + repo haritası | doğru dosyayı okuma 5/5 |
| 4 | diagnosis, tam sohbet | diagnosis 1/5 |
| 4 | + temiz bağlam + durum özeti + `analysis` alanı | diagnosis 3/5 |
| 5 | onaylı patch | geçerli patch 5/5, onarımsız testler 2/5 |
| 6 | test + 2 onarım | testler 3/5 ve 2/5 (iki ölçüm) |
| 8 | final ölçüm | diagnosis 4/5, otonom 2/5 |

### 6.5 Güvenlik ve sınırlar (final ölçümlerde ne engellendi?)

| | 7B | 3B |
|---|---|---|
| Repo dışı yol denemesi | 0 | 0 |
| Bozuk JSON cevap | 0 | 0 |
| Okunmamış satırı kanıt gösterme (reddedildi) | 0 | 2 |
| Reddedilen patch önerisi (toplam) | 16 | 26 |
|   ↳ repoda olmayan ad uydurma | 4 | 7 |
|   ↳ sözdizimi bozuk | 2 | 1 |
| Testler geçmeyince geri alınan (rollback) | 7 | 6 |
| Bir issue'daki en fazla model çağrısı | 17 (sınır 40) | 14 |

JSON şemalı çıktı sayesinde 297 model çağrısında **tek bir bozuk JSON**
yok. Reddedilen 42 patch'in hiçbiri diske yazılmadı. Testi geçmeyen her patch
geri alındı, yani başarısız bir çalıştırma repoyu bozuk bırakmadı.

---

## 7. Başarısızlık analizi

`eval/summarize.py` her başarısız issue'yu **ilk kırıldığı aşamaya** göre
sınıflandırıyor (yanlış diagnosis'ten sonra gelen yanlış patch, patch sorunu
değil diagnosis sorunudur):

| Sınıf | Anlamı | 7B | 3B |
|---|---|---|---|
| F0 | Model çıktısı kullanılamaz / bütçe bitti | 0 | 0 |
| F1 | Bug'lı dosyayı hiç okumadı (localization) | 2 | 6 |
| F2 | Okumadığı kodu kanıt gösterdi | 0 | 0 |
| F3 | Doğru kodu okudu, yanlış yorumladı (misdiagnosis) | 5 | 5 |
| F4 | Kontrolden geçen patch üretemedi | 2 | 2 |
| F5 | Patch uygulandı, onarımlara rağmen testler kaldı | 1 | 1 |

**En büyük sorun bulmak değil, anlamak:** 7B dosyayı %87 oranında buluyor,
ama doğru okuduğu kodu yanlış açıklıyor (F3).

### 7.1 easy_01: "Kullanılmayan şey" bug'ı (F3)

- **Bug:** `normalize_email`, `EMAIL_PATTERN.match(...)` yerine yalnızca
  `"@" in email` kontrol ediyor. Regex tanımlı ama hiç kullanılmıyor.
- **Agent ne yaptı:** `register` → `common/validation.py`'deki `EMAIL_PATTERN`
  satırını okudu, regex'i suçladı ve regex'i değiştiren bir patch yazdı. Testler
  kaldı. Onarım önerilerinin ikisi de controller'dan geçemedi: biri hiçbir şeyi
  değiştirmiyordu, diğeri repoda olmayan `IGNORECASE` adını kullanıyordu.
  Sonunda değişiklik geri alındı (rollback).
- **Neden:** Bug bir şeyin **eksikliği** (regex'in kullanılmaması). Model hep
  "yanlış yazılmış kodu" arıyor; regex doğru göründüğü halde onu "düzeltti".
  `read_file` ipucu "EMAIL_PATTERN başka yerde kullanılıyor mu?" sorusuna
  yalnızca kullanım varsa cevap veriyor; **hiç kullanılmadığını** söylemiyor.
- **Ders / sonraki adım:** Araç "bu sabit dosyada hiç kullanılmıyor" diye
  açıkça yazmalı. Yokluk sinyali küçük modeller için çok değerli.

### 7.2 easy_04: Uydurma alan (F4)

- **Bug:** `is_overdue` içinde `task.status != Status.DONE` koşulu silinmiş.
- **Agent ne yaptı:** Diagnosis **doğruydu** ("tamamlanmış görevi kontrol
  etmiyor"). Ama her patch'te `task.completed` yazdı. Böyle bir alan yok,
  gerçek alanlar `status` ve `completed_at`. Controller bunu her seferinde
  reddetti, bir keresinde "belki: completed_at" önerisiyle. Model önerileri
  görmezden geldi.
- **Neden:** Model `Task` dataclass'ını hiç okumadı; kendi kök neden cümlesindeki
  "completed" kelimesini koda çevirdi.
- **İyi taraf:** Uydurma kod **diske hiç ulaşmadı**; bu tam olarak
  halüsinasyon kontrolünün amacı.
- **Sonraki adım:** Patch bağlamına, kanıtta geçen nesnenin modelini
  (`Task` alanlarını) otomatik eklemek.

### 7.3 hard_04: Sıralama (ordering) hatası (F3 → zararlı patch → rollback)

- **Bug:** `TaskService.assign` olayı (`TASK_ASSIGNED`), `task.assignee_id`'yi
  güncellemeden **önce** yayınlıyor; bildirim eski atanana gidiyor.
- **Agent ne yaptı:** `assign` → `notify` → `dispatcher.on_task_assigned` zincirini
  doğru izledi (3 modül!), ama suçu dispatcher'daki koşula attı ve koşulu
  tersine çevirdi. Bu 4 testi daha kırdı. Onarım önerileri controller'dan
  geçemedi (biri hiçbir şeyi değiştirmiyordu, biri koddaki metni yanlış
  kopyalamıştı), bu yüzden değişiklik geri alındı.
- **Neden:** "Önce yayınla, sonra ata" gibi **zamana bağlı** bir ilişkiyi
  görmek, 7B için zor: iki satırın **sırası** hatalı, satırların kendisi değil.
- **İyi taraf:** Test geri bildirimi patch'in zararlı olduğunu gösterdi,
  rollback repoyu kurtardı.

### 7.4 medium_01 ve 3B'nin genel sorunu: yanlış yerde kalmak (F1)

- medium_01'de bug `users/service.py` içindeki `normalize_handle`'da
  (`.lower()` silinmiş). Agent belirtinin olduğu `comments/` modülünde kaldı,
  `mentioned.append(handle.lower())` gibi bir patch yazdı (kimlik yerine handle
  saklamak). Bu 6 testi kırdı, onarımlar da tutmadı, rollback yapıldı.
- 3B bu türden "belirti burada, sebep orada" issue'larının çoğunda doğru
  dosyaya hiç gitmedi (F1: 6/15).

### 7.5 Değişkenlik (variance)

Aynı issue farklı çalıştırmalarda farklı sonuç verebiliyor. easy_03 Adım 6
ölçümlerinde iki kez çözüldü, finalde çözülemedi. easy_02 ise tersine.
`temperature=0` olsa bile prompt'taki küçük farklar modelin yolunu
değiştiriyor. Bu yüzden tek bir çalıştırmaya bakıp "%40 başarılı" demek
yerine sonuçları her zaman küçük örneklem uyarısıyla okumak gerekiyor.

---

## 8. Kendin dene (öğrenme alıştırmaları)

1. `./venv/bin/python -m pytest tests/test_tools.py -v`: her testin adını oku;
   hangisi hangi güvenlik kuralını koruyor?
2. `eval/issues.py prepare easy_03` yap, sonra
   `./venv/bin/python -m lca --repo eval/workspace/easy_03 "<issue metni>"`
   ile agent'ı izle. Her adımda modelin `thought`'una bak.
3. `lca/config.py` içinde `max_steps`'i 4 yap, aynı issue'yu çalıştır. Ne değişti?
4. `compact_history` değerini `LCA_COMPACT_HISTORY=false` ile kapat; prompt
   token sayısını karşılaştır.
5. Kendi bug'ını yaz: `taskflow/` içinde bir satır seç, `eval/issues/` altına
   yeni bir JSON ekle, `eval/issues.py check` ile doğrula.

---

## 9. Mentör soruları ve kısa cevaplar

- **"Neden bütün repoyu prompt'a koymadın?"** 8K context'e sığmaz; sığsa
  bile 7B ilgisiz kodda kayboluyor. Repo haritası + arama + satır aralığı
  okuma ile issue başına ortalama ~15 bin token'lık **toplam** maliyetle,
  en büyük tek prompt ~2 bin token olacak şekilde çalışıyor.
- **"Model yanlış dosya yolu verirse?"** `Repo.resolve` reddeder, gözlem
  olarak hatayı geri verir, `blocked` metriğine yazılır.
- **"Model 'onaylandı' yazarsa dosya değişir mi?"** Hayır. Onay yalnız
  `approve()` callback'inden (terminalde senin `yes`'inden) gelir.
- **"Sonsuz döngü?"** Her döngünün sabit üst sınırı var + toplam 40 çağrı freni.
- **"Diagnosis'in doğru olduğunu nereden biliyorsun?"** Bilmiyorum. Kanıtın
  okunmuş kod olduğunu biliyorum; doğruluğu ground truth ile ayrıca ölçüyorum
  ve başarısız vakaları saklamıyorum.
