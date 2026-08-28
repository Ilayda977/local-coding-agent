# Yerel Model Performans Testi (Baseline)

Bu belgenin amacı, kodlama ajanımızı geliştirmeye başlamadan önce modellerin (7B ve 3B) yerel bilgisayarımızdaki hızını, bellek (RAM) kullanımını ve cevap kalitesini ölçmektir. Eğer 7B modeli günlük kullanımda bilgisayarı kullanılamaz hale getirecek kadar yavaşlatıyorsa, proje mimarisinde strateji değişikliğine gideceğiz.

## Test Edilen Donanım
- Cihaz: Apple M3 MacBook
- RAM: 16 GB Unified Memory

## Test Soruları (Prompts)

### Soru 1: Kod Açıklama
**Aşağıdaki Python fonksiyonunun ne yaptığını kısaca açıklar mısın?**
```python
def reverse_string(s):
    return s[::-1]
```

### Soru 2: Küçük Bug (Hata) Bulma
**Aşağıdaki JavaScript kodunda bir hata var. Bu hatayı bulup nedenini söyler misin?**
```javascript
function greet(name) {
    if (name = "Ali") {
        console.log("Merhaba Ali");
    } else {
        console.log("Merhaba Yabancı");
    }
}
```

### Soru 3: Kısa Patch (Yama) Önerme
**Bir web sayfasında "Submit" (Gönder) butonuna tıklandıktan sonra butonun 2 saniyeliğine devre dışı (disabled) kalmasını sağlayan kısa bir React (veya JavaScript) kodu yazar mısın?**

---

## 1. Model: qwen2.5-coder:7b (Ana Model)

* **Soru 1 (Kod Açıklama):** 
  * Süre/Hız Hissi: Çok hızlı, bekleme yaşanmadı.
  * Kalite: Başarılı. Kodu doğru anladı ve net bir şekilde açıkladı.
* **Soru 2 (Hata Bulma):**
  * Süre/Hız Hissi: Çok hızlı.
  * Kalite: Başarılı. Atama operatörü (`=`) hatasını buldu ve `==` ile düzeltti.
* **Soru 3 (Patch Önerme):**
  * Süre/Hız Hissi: Çok hızlı.
  * Kalite: Başarılı. Class component kullanarak 2 saniye disable kalmasını sağlayan doğru bir React kodu yazdı.
* **Genel Gözlem ve RAM Kullanımı (Activity Monitor):** Bellek yoğunluğu grafiği yeşil seviyelerde seyretti (kısa bir süre sarıya çıksa da sistemi yavaşlatmadı). Günlük kullanım için oldukça akıcı.

---

## 2. Model: qwen2.5-coder:3b (Hızlı/Baseline Model)

* **Soru 1 (Kod Açıklama):** 
  * Süre/Hız Hissi: Çok hızlı.
  * Kalite: Başarılı. Detaylı ve doğru bir açıklama yaptı.
* **Soru 2 (Hata Bulma):**
  * Süre/Hız Hissi: Çok hızlı.
  * Kalite: Başarılı. Hatayı buldu, hatta `==` veya `===` kullanılabileceğini belirterek güzel bir detay verdi.
* **Soru 3 (Patch Önerme):**
  * Süre/Hız Hissi: Çok hızlı.
  * Kalite: Başarılı. Modern React (Functional Component ve Hooks - `useState`, `useEffect`) kullanarak temiz bir çözüm üretti.
* **Genel Gözlem ve RAM Kullanımı (Activity Monitor):** Bellek yoğunluğu yeşil seviyede. Sistemde hiçbir zorlanma yok. Çok hızlı ve pratik.

---

## Karar (GO / NO-GO)
* **Sonuç:** **GO!** 7B modeli M3 16GB makinede hem çok hızlı cevap veriyor hem de RAM'i kitlemiyor (sarı bölgeye geçişler olsa da takılma hissi yaratmıyor). İki modelin de kod kalitesi oldukça iyi (3B modeli React Hooks kullanarak biraz daha modern bir kod yazdı, ancak 7B'nin kapasitesi genel karmaşık görevler için daha uygun). **Projeye 7B ana model olarak devam edilebilir.**
