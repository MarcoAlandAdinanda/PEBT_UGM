# Pemetaan Paper ke Software PEBT

Dokumen ini menjelaskan asal setiap parameter dalam `configs/pebt_yamawaki_2023_draft.json`, cara parameter tersebut diterapkan, dan keputusan yang masih harus disetujui peneliti. Status konfigurasi sengaja dipertahankan sebagai `draft`.

## Sumber utama

- Yamawaki, M., et al. (2023), “Effects of virtual agent interactivity on pro-environmental behavior promotion,” *Journal of Environmental Psychology*, 88, 101999. [DOI 10.1016/j.jenvp.2023.101999](https://doi.org/10.1016/j.jenvp.2023.101999).
- Lange, F., & Iwasaki, S. (2020), “Validating the Pro-Environmental Behavior Task in a Japanese Sample,” *Sustainability*, 12(22), 9534. [DOI 10.3390/su12229534](https://doi.org/10.3390/su12229534).
- [Materi OpenSesame PEBT Jepang pada OSF](https://osf.io/vxpmq/) dipakai hanya sebagai referensi perilaku percabangan pilihan dan randomisasi. File/aset eksternal tersebut tidak disalin ke repository.

PDF contoh yang diberikan pengguna memiliki SHA-256 `8B6B5E91EB14EB94B0761139BCCE3E8D2FF14BBED588782F2D0BF1BACF4D5E61`. Hash dicatat pada konfigurasi agar versi sumber yang dipakai untuk pemetaan dapat diaudit. PDF tidak dibundel ulang ke repository.

## Matriks implementasi

| Parameter | Bukti paper | Implementasi software | Status |
|-----------|-------------|------------------------|--------|
| Pilihan PEBT | Metode, PDF hlm. 3: peserta memilih SEST atau DIFT dengan keyboard; layar tunggu mengikuti pilihan | Panah kiri = SEST; panah kanan = DIFT; fase pilihan berakhir saat tombol valid diterima | Langsung dari paper |
| Instruksi dan stimulus | Prosedur/hlm. 3 menyebut instruksi PEBT; Fig. 1 menampilkan dua opsi, waktu, lampu, emisi, tombol, dan observer | Tiga halaman instruksi dan runner Web dua kartu dengan 12 indikator lampu; durasi membaca dicatat | Teks Indonesia perlu persetujuan |
| Makna pilihan | PDF hlm. 3 dan Appendix D/hlm. 9: SEST lebih ramah lingkungan, tanpa lampu, tetapi dapat lebih lama; DIFT lebih singkat dengan lampu/emisi | SEST menjalankan cabang relay OFF; DIFT menjalankan cabang relay sesuai blok | Langsung dari paper |
| Jumlah pilihan | PDF hlm. 3: PEBT dilakukan 24 kali; prosedur menjalankan PEBT pada SET1 dan SET2 | 24 pilihan per SET, total 48 pilihan yang dianalisis | Langsung dari paper |
| Struktur blok | Fig. 1 menunjukkan 12 repetisi lalu “do the same with 4 lights”; Appendix D/hlm. 9 menyebut dua blok × 12 trial | Setiap SET berisi blok 12 lampu × 12 lalu 4 lampu × 12 | Langsung dari paper |
| Konfirmasi lampu | Appendix D/hlm. 9: 12 lampu menyala selama 10 detik sebelum PEBT | Satu trial hardware confirmation selama 10.000 ms sebelum SET1; tidak masuk analisis | Jumlah pengulangan perlu konfirmasi |
| Waktu tunggu DIFT | Appendix D/hlm. 9: 5 s × 8; 10 s × 4; 15 s × 4; 20 s × 4; 25 s × 4 dalam 24 trial | Multiset identik dibentuk untuk setiap SET | Langsung dari paper |
| Selisih SEST-DIFT | Appendix D/hlm. 9: 0 s × 2; 5 s × 8; 10 s × 10; 15 s × 4 | `SEST wait = DIFT wait + difference`; multiset identik dibentuk untuk setiap SET | Langsung dari paper |
| Pasangan faktor | Paper menyebut kedua distribusi dipilih acak, tetapi tidak menerbitkan pasangan trial-per-trial | Dua multiset diacak secara deterministik dan dipasangkan untuk setiap SET | Asumsi terdokumentasi |
| Emisi lampu | Appendix D/hlm. 9: 54 W/lampu, faktor 0,350 kg-CO₂/kWh, sekitar 10 L CO₂ per jam per lampu | Layar menampilkan 0 L/jam untuk SEST, 120 L/jam untuk 12 lampu, dan 40 L/jam untuk 4 lampu | Langsung dari paper |
| SET1 | Prosedur, PDF hlm. 3: PEBT dengan karakter kucing tanpa kontak agen | Label observer SET1 disimpan pada metadata dan layar; stimulus memakai badge teks karena aset tidak tersedia | Aset kucing belum tersedia |
| Kondisi antarpartisipan | PDF hlm. 2–3: agen interaktif atau non-interaktif | Operator memilih `interactive_agent` atau `non_interactive_agent`; nilai disimpan pada semua event dan summary | Assignment tidak diotomasi |
| Kontak SET2 | Prosedur, PDF hlm. 3: kontak agen sekitar 5 menit, lalu PEBT dengan Piyota ditampilkan | Gate sebelum SET2 meminta operator menyelesaikan prosedur eksternal; durasi gate dicatat sebagai `block_gate_complete` | Sistem agen eksternal belum tersedia |
| Ukuran PEB | PDF hlm. 3–4: jumlah SEST dan perubahan SET2 minus SET1 | Summary menyimpan `choice_counts_by_set` dan `pebt_improvement_set2_minus_set1` secara langsung | Langsung siap dianalisis |
| Relay | Foto/setup proyek dan manual RLY-P4-U | 12 lampu = Relay 1+2+3; Relay 4 selalu OFF | Mapping 12 lampu sesuai baseline lokal |
| Empat lampu | Paper tidak menyebut bank relay fisik yang harus digunakan pada setup UGM | Draft memakai deret depan/Relay 3 | Wajib dikonfirmasi |

## Alur yang dijalankan

```text
Konfirmasi 12 lampu (10 s)
  → SET1: 12 lampu × 12 pilihan
  → SET1: 4 lampu × 12 pilihan
  → kontak Piyota eksternal (~5 menit; durasi gate dicatat)
  → SET2: 12 lampu × 12 pilihan
  → SET2: 4 lampu × 12 pilihan
```

Setiap pilihan memiliki alur berikut:

```text
Layar pilihan
  ├─ panah kiri / SEST → semua relay OFF → tunggu DIFT + selisih
  └─ panah kanan / DIFT → relay blok ON → tunggu sesuai DIFT
→ semua relay OFF → pilihan berikutnya
```

Relay 4 selalu diminta OFF pada semua mapping. Pada setiap batas fase, setelah trial, saat selesai, saat abort, dan saat error, aplikasi mengirim OFF untuk keempat output lalu memeriksa readback. Jika perintah atau readback gagal, state dilaporkan tidak diketahui; operator harus memutus daya beban secara fisik dan tidak mengandalkan indikator software.

## Randomisasi dan audit data

- Frekuensi faktor tidak berubah akibat randomisasi.
- Pembentukan pasangan faktor menggunakan hash seed stabil dari `random_seed` dan SET.
- Urutan trial dalam blok menggunakan `random_seed`, ID partisipan, block ID, dan nomor repetisi.
- File summary merekam SHA-256 konfigurasi serta urutan trial hasil kompilasi.
- Event respons merekam pilihan, response time, jumlah lampu, waktu tunggu terpilih, emisi yang ditampilkan, SET, dan block.
- Event instruksi merekam halaman serta durasi membacanya; stimulus pilihan dirender sebagai dua kartu SEST/DIFT dengan 12 indikator lampu tanpa memakai aset eksternal.
- Layar jeda block menghasilkan pasangan event `block_start` dan `block_gate_complete`; selisih waktu tersebut mengaudit durasi kontak agen eksternal.

## Keputusan sebelum status `validated`

1. Tentukan apakah empat lampu benar-benar menggunakan deret depan/Relay 3.
2. Setujui cara memasangkan multiset waktu DIFT dan selisih waktu, atau berikan matriks trial asli.
3. Berikan detail sesi latihan yang disebut dalam prosedur paper; draft belum membuat trial latihan karena parameternya tidak diterbitkan.
4. Konfirmasi apakah demonstrasi 12 lampu dilakukan satu kali atau diulang sebelum SET2.
5. Setujui seluruh terjemahan teks layar dan istilah emisi.
6. Sediakan aset karakter kucing dan Piyota beserta izin penggunaannya, atau setujui badge teks sebagai stimulus pengganti.
7. Definisikan/provide sistem Wizard-of-Oz, dialog, suara, animasi, dan kriteria selesai untuk kondisi interaktif/non-interaktif.
8. Tentukan metode assignment partisipan dan aturan exclusion/missing data.
9. Lakukan pilot pada Windows dengan relay, `Ydci.dll`, lampu aktual, dan alat ukur timing bila onset cahaya merupakan variabel kritis.

Sebelum semua keputusan tersebut selesai, konfigurasi cocok untuk review software dan pilot terkontrol, tetapi tidak boleh disebut replikasi tervalidasi atau dipakai sebagai protokol final tanpa persetujuan peneliti.
