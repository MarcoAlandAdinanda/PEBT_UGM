# Konfigurasi Eksperimen

Dokumen ini menjelaskan cara mengubah protokol penelitian menjadi konfigurasi JSON yang dapat dijalankan oleh Web UI lokal. Konfigurasi dibuat melalui mode **Build**, kemudian dijalankan dari **Execute**. **Manual / System Setup** hanya digunakan untuk diagnosis hardware. Jalankan interface dengan `python gui.py --demo` tanpa hardware atau `python gui.py` dalam mode hardware; keduanya membuka browser pada server Python loopback.

## Status sumber saat ini

Spesifikasi hardware dan API telah dicocokkan dengan sumber resmi berikut:

- [RLY-P4/2/0B-UBT Hardware Manual](https://cdn.y2c.co.jp/ub/pdf/rly-p4_2_0b-ubt.pdf), terutama halaman 4-7 untuk board ID, terminal, rating listrik, dan wiring.
- [UB Series Software Manual](https://cdn.y2c.co.jp/docs/softwaremanual/ub/ub_softwaremanual.pdf), terutama halaman 7-15 dan 28-32 untuk alur penggunaan, tipe data API, open mode, error code, output relay, readback, dan close.
- [Official Python Sample](https://www.y2c.co.jp/ub/ub_rlyp4/python/) untuk loader Windows/Linux dan contoh pemanggilan `ctypes`.

Contoh paper [Yamawaki et al. (2023)](https://doi.org/10.1016/j.jenvp.2023.101999) telah dianalisis dan diterjemahkan ke `configs/pebt_yamawaki_2023_draft.json`. Konfigurasi ini menjadi baseline PEBT untuk review dan pilot. Statusnya tetap `draft` karena beberapa detail lokal dan aset eksperimen tidak ditentukan atau tidak disertakan oleh paper. Lihat [pemetaan paper ke software](pebt-protocol-mapping.md) sebelum menggunakannya.

`configs/demo_experiment.json` tetap berstatus `demo` dan hanya menguji alur software. Timing 500/1200/500 ms dan tiga trial di dalam file demo bukan parameter penelitian.

## Pengganti komponen OpenSesame

| Konsep OpenSesame | Implementasi aplikasi |
|-------------------|-----------------------|
| Experiment properties | Metadata top-level JSON dan `display` |
| Sequence | Urutan `blocks`, `trials`, dan `phases` |
| Loop | `repetitions` serta `randomize_trials` |
| Variables | `condition`, `metadata`, dan properti fase |
| Sketchpad/Text display | Runner browser solid dengan `text`, `background`, `foreground`, `font_size` |
| Form/instruction pages | `instruction_pages` dengan event durasi per halaman |
| Keyboard response | `collect_response`, `allowed_keys`, `correct_key`, `end_on_response` |
| Conditional sequence | `run_if_response_key` untuk fase SEST atau DIFT |
| Logger | Event CSV yang di-flush per event + ringkasan JSON per sesi |

## Menggunakan visual Experiment Builder

Builder memungkinkan peneliti menyusun eksperimen tanpa menulis kode Python atau JSON secara manual:

1. Jalankan `python gui.py --demo` untuk desain tanpa hardware, atau `python gui.py` jika relay dan DLL tersedia. Browser membuka alamat lokal yang dicetak terminal, biasanya `http://127.0.0.1:8765/`.
2. Buka **Build**, lalu klik **Eksperimen baru** untuk konfigurasi kosong atau pilih konfigurasi dan klik **Buka**.
3. Susun hierarki **Experiment → Block → Trial → Phase**. Gunakan tombol tambah, duplikasi, hapus, naik, dan turun untuk mengatur urutan.
4. Pilih sebuah item, ubah propertinya, lalu klik **Terapkan properti**.
5. Klik **Validasi** untuk memeriksa seluruh schema, ID unik, timing, response key, lampu, dan sumber protokol.
6. Klik **Simpan** untuk menulis konfigurasi ke `configs/user/`, atau klik **Gunakan di Execute** untuk mengirim snapshot builder yang sudah divalidasi langsung ke mode **Execute**.

Perubahan struktural—termasuk menambah, menghapus, memindahkan, menduplikasi, atau mengedit block/trial/phase—secara otomatis mengubah status `validated` kembali menjadi `draft`. Validasi schema memastikan file dapat dieksekusi, tetapi persetujuan ilmiah tetap menjadi tanggung jawab peneliti.

Field umum diedit sebagai form. `instruction_pages`, `sources`, dan `metadata` tetap menggunakan editor JSON di panel properti agar objek penelitian yang bersifat khusus tidak hilang. Simpan file konfigurasi bersama repository supaya konfigurasi, log, dan hash sesi dapat diaudit.

Saat konfigurasi PEBT ringkas yang memiliki `generator` dibuka, builder mengembangkannya menjadi lima block dan 49 trial eksplisit agar setiap trial dapat diedit. Hasil ekspansi selalu menjadi copy `draft`; saat disimpan, file baru ditempatkan di `configs/user/`. File generator baseline tidak ditimpa.

## Struktur konfigurasi

```json
{
  "schema_version": 1,
  "task_type": "generic",
  "protocol_id": "STUDY-ID-V1",
  "title": "Judul protokol",
  "protocol_status": "draft",
  "description": "Ringkasan dan batas penggunaan",
  "instructions": "Instruksi awal partisipan",
  "random_seed": 2026,
  "data_directory": "data/experiments",
  "participant_conditions": [],
  "display": {
    "fullscreen": true,
    "background": "#000000",
    "foreground": "#FFFFFF",
    "font_size": 34
  },
  "sources": [],
  "blocks": []
}
```

`data_directory` dipertahankan untuk kompatibilitas schema/runner lama. Pada Web UI lokal, backend sengaja mengabaikan path tersebut dan selalu menulis hasil ke root terkontrol `data/experiments/` agar konfigurasi tidak dapat mengarahkan penulisan ke lokasi arbitrer.

### Status protokol

- `demo`: hanya untuk pengujian software/hardware.
- `draft`: protokol sedang diterjemahkan atau menunggu validasi peneliti.
- `validated`: boleh dipakai setelah seluruh parameter cocok dengan paper/protokol yang disetujui.

Konfigurasi berstatus `validated` wajib memiliki sekurangnya satu entri `sources` dengan `source_type: "research_paper"`. Validator menolak status tervalidasi jika sumber paper tidak dicantumkan.

### Konfigurasi PEBT berbasis paper

File `configs/pebt_yamawaki_2023_draft.json` menggunakan `task_type: "pebt"` dan generator ringkas. Saat file dimuat, `pebt.py` mengembangkan faktor tersebut menjadi satu trial konfirmasi lampu dan 48 trial pilihan:

| Urutan | Isi | Jumlah trial |
|--------|-----|--------------|
| Konfirmasi hardware | 12 lampu menyala 10 detik | 1, tidak dianalisis |
| SET1, blok 12 lampu | pilihan SEST/DIFT dengan karakter kucing | 12 |
| SET1, blok 4 lampu | pilihan SEST/DIFT dengan karakter kucing | 12 |
| SET2, blok 12 lampu | pilihan SEST/DIFT setelah kontak Piyota | 12 |
| SET2, blok 4 lampu | pilihan SEST/DIFT setelah kontak Piyota | 12 |

Kondisi antarpartisipan yang tersedia adalah `interactive_agent` dan `non_interactive_agent`. Penentuan kondisi dilakukan oleh peneliti; software merekam pilihan tersebut tetapi tidak melakukan assignment otomatis.

Distribusi setiap SET adalah DIFT 5 detik × 8, 10 detik × 4, 15 detik × 4, 20 detik × 4, dan 25 detik × 4. Selisih waktu SEST-DIFT adalah 0 detik × 2, 5 detik × 8, 10 detik × 10, dan 15 detik × 4. Karena paper hanya melaporkan frekuensi marginal, generator mengacak kedua daftar secara deterministik lalu memasangkannya. Pasangan tepat ini masih harus disetujui peneliti.

Urutan trial dalam setiap blok diacak secara deterministik berdasarkan seed konfigurasi, ID partisipan, block ID, dan repetisi. Dengan file serta ID partisipan yang sama, urutannya dapat direproduksi.

### Halaman instruksi

`instruction_pages` menggantikan rangkaian form instruksi OpenSesame. Setiap halaman memiliki `page_id`, `title`, `text`, dan `hint`. Durasi membaca dicatat melalui event `instruction_page_start` dan `instruction_page_complete`.

```json
{
  "instruction_pages": [
    {
      "page_id": "task-overview",
      "title": "PETUNJUK PEBT",
      "text": "Pilih SEST atau DIFT pada setiap perjalanan.",
      "hint": "Tekan SPASI untuk melanjutkan"
    }
  ]
}
```

Jika array tersebut tidak diberikan, engine membuat satu halaman kompatibilitas dari properti `instructions`.

### Block dan randomisasi

```json
{
  "block_id": "practice",
  "instructions": "Tekan SPASI untuk memulai blok latihan.",
  "repetitions": 1,
  "randomize_trials": true,
  "trials": []
}
```

Randomisasi bersifat deterministik berdasarkan `random_seed`, ID partisipan, block ID, dan nomor repetisi. Partisipan yang sama mendapatkan urutan yang sama jika konfigurasi tidak berubah.

### Trial dan fase

```json
{
  "trial_id": "left-condition-01",
  "condition": "left",
  "correct_key": "space",
  "metadata": {
    "independent_variable": "light_direction"
  },
  "phases": [
    {
      "name": "fixation",
      "duration_ms": 500,
      "text": "+",
      "lights": [],
      "collect_response": false
    },
    {
      "name": "stimulus",
      "duration_ms": 1000,
      "text": "SPASI",
      "lights": ["left"],
      "collect_response": true,
      "allowed_keys": ["space"]
    }
  ]
}
```

Nilai `lights` yang valid adalah `left`, `right`, dan `front`. Kombinasi diperbolehkan. Mapping output selalu `(left, right, front, 0)`, sehingga Relay 4 tetap OFF.

Fase pilihan PEBT tidak memiliki timeout dan berakhir ketika respons valid diterima:

```json
{
  "name": "choice",
  "duration_ms": null,
  "collect_response": true,
  "allowed_keys": ["left", "right"],
  "end_on_response": true
}
```

Sesudah respons, hanya satu fase waktu tunggu dijalankan. Contoh cabang SEST:

```json
{
  "name": "sest_wait",
  "duration_ms": 15000,
  "lights": [],
  "collect_response": false,
  "run_if_response_key": "left"
}
```

`duration_ms: null` hanya valid pada fase yang mengumpulkan respons dan memiliki `end_on_response: true`. Nilai `run_if_response_key` harus termasuk allowed key dari fase respons trial yang sama.

## Data hasil

Setiap sesi menghasilkan dua file pada `data/experiments/`:

- `*.events.csv`: event log append-only yang di-flush setelah setiap baris. Jika aplikasi atau komputer berhenti mendadak, baris yang sudah ditulis tetap dapat dianalisis sebagai data parsial.
- `*.summary.json`: manifest sesi yang ditulis secara atomik. Saat sesi dimulai statusnya `in_progress`; pada akhir normal, abort, atau error status berubah menjadi `completed`, `aborted`, atau `error`.

Nama file memuat UTC timestamp, ID partisipan yang telah disanitasi, protocol ID, dan delapan karakter awal session UUID. UUID mencegah tabrakan nama ketika dua sesi dimulai pada detik yang sama.

Log mencatat:

- identitas sesi, partisipan, protokol, file konfigurasi, dan SHA-256 isi konfigurasi;
- block, trial, condition, repetition, phase, serta metadata;
- lampu yang diminta dan hasil readback empat relay;
- scheduled duration, actual elapsed time, serta drift;
- tombol respons, response time, dan correctness;
- kondisi partisipan, pilihan SEST/DIFT, SET, jumlah lampu, waktu tunggu terpilih, kedua faktor timing, observer, serta indikator pro-environmental;
- waktu membaca setiap halaman instruksi;
- durasi aktual layar jeda blok (`block_gate_complete`), termasuk jeda kontak agen sebelum SET2;
- session completion, abort, atau error.

Ringkasan JSON menyimpan status akhir, waktu mulai/selesai, hash konfigurasi, nama event log, urutan trial hasil kompilasi, jumlah trial selesai, jumlah respons dan timeout, mean response time, jumlah pilihan SEST/DIFT per kondisi dan per SET, persentase pilihan pro-environmental, serta ukuran perubahan utama paper (`jumlah SEST SET2 - jumlah SEST SET1`). Hash konfigurasi dan urutan trial membuat sesi dapat diaudit terhadap file protokol yang benar.

Clock respons authoritative berada pada backend Python dan menggunakan `time.perf_counter_ns()`. Browser juga mengirim estimasi elapsed time sebagai detail pendukung, tetapi tidak menentukan hasil timing utama. Setiap fase memakai dua gate bertoken: browser mengirim `ready` dari layar netral sebelum backend mengubah/membaca relay, lalu mengirim `presented` setelah stimulus benar-benar dicat. Clock fase, deadline, dan window respons dimulai ketika backend menerima `presented`; `command_duration_ms`, latensi relay-ke-ACK browser, dan elapsed browser disimpan pada `details_json`. Masing-masing ACK dibatasi lima detik. Pada setiap batas fase, backend lebih dahulu mematikan serta membaca balik relay dan menampilkan transisi netral sebelum fase berikutnya. Latensi mekanis relay, transport browser, dan waktu aktual perubahan luminansi tetap harus diukur pada pilot jika menjadi variabel penting penelitian.

Selama runner aktif, tab pemilik mengirim heartbeat ke backend. Jika heartbeat hilang sekitar 15 detik karena tab disembunyikan, browser terputus, atau halaman ditutup, backend meng-abort sesi lalu memerintahkan OFF dan memeriksa readback. Jika OFF tidak dapat diverifikasi, UI menampilkan state tidak diketahui dan operator harus memakai pemutus daya fisik. Manual control juga dikunci selama sesi agar hanya runtime eksperimen yang memiliki relay.

## Checklist menerjemahkan paper

Sebelum mengubah status menjadi `validated`, peneliti harus mengonfirmasi:

1. Seluruh kondisi, faktor, level, block, jumlah trial, latihan, dan repetisi.
2. Aturan randomisasi, counterbalancing, dan assignment partisipan.
3. Urutan setiap fase dan timing dalam milidetik.
4. Kombinasi lampu untuk setiap kondisi serta mapping Relay 1/2/3.
5. Stimulus layar, instruksi, allowed keys, correct response, dan timeout.
6. Kriteria abort, exclusion, missing response, dan pengulangan trial.
7. Kolom data yang dibutuhkan untuk analisis paper.
8. Validasi timing dengan pilot dan alat ukur bila presisi onset cahaya diperlukan.
9. Citation, halaman, tabel, atau gambar paper dicatat pada `sources` dan `notes`.

Untuk draft Yamawaki 2023, keputusan yang masih terbuka dirinci dalam [pemetaan protokol](pebt-protocol-mapping.md): deret fisik untuk 4 lampu, pasangan faktor timing, detail latihan, pengulangan konfirmasi lampu, persetujuan terjemahan instruksi, aset karakter, dan prosedur Wizard-of-Oz. Urutan blok 12 lampu lalu 4 lampu mengikuti Fig. 1. Setelah semua keputusan ditulis dalam konfigurasi, lakukan review peneliti, uji timing, dan pilot hardware sebelum mengubah status menjadi `validated`.
