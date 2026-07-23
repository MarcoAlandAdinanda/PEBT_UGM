# Jawaban Pembaruan untuk Klien

Berikut adalah informasi terbaru mengenai software experimental setup dan ketersediaan file software relay control.

## 1. Software Experimental Setup

Setup eksperimen saat ini **tidak menggunakan OpenSesame maupun Tkinter sebagai interface utama**. Eksperimen dibuat langsung sebagai aplikasi Python, kemudian dikembangkan dan dijalankan melalui Visual Studio Code (VS Code). `python gui.py` menyalakan backend Python pada komputer lokal dan membuka Web UI di browser, biasanya pada `http://127.0.0.1:8765/`. Web UI menggunakan bento grid dan glassmorphism 2.0 pada dashboard operator, sedangkan layar runner partisipan tetap solid tanpa efek dekoratif.

Aplikasi menyediakan visual **Experiment Builder** untuk menyusun block, trial, dan phase tanpa menulis kode Python; konfigurasi hasil builder disimpan sebagai JSON dan dapat langsung dieksekusi. Python tetap mengatur timing, relay, validasi input, dan logger. Aplikasi merekam respons keyboard dan response time, lalu menyimpan event log CSV dan ringkasan sesi JSON.

Alur software dan perangkat yang digunakan adalah:

```text
Browser → HTTP lokal → Python (`gui.py` / `web_app.py`) → konfigurasi JSON → `web_runtime.py`/logger → `relay_controller.py` → `ctypes` → `Ydci.dll` → USB → RLY-P4-U
```

VS Code berfungsi sebagai IDE untuk mengedit dan menjalankan program; browser hanya menjadi interface lokal. Aplikasi memiliki tiga mode utama: **Build** untuk membuat dan memvalidasi protokol, **Execute** untuk menjalankan konfigurasi tersimpan atau snapshot builder, serta **Manual / System Setup** untuk menghubungkan relay dan mengetes lampu kiri, kanan, dan depan. Mode manual bukan untuk menjalankan protokol penelitian dan otomatis dikunci ketika eksperimen aktif.

Kebutuhan software utamanya adalah Windows 10/11, Python 3.7 atau lebih baru, browser modern, VS Code, dan Microsoft Python extension. Sistem Web tidak membutuhkan instalasi package `pip`, `npm`, CDN, atau koneksi cloud. Driver USB relay dan `Ydci.dll` hanya diperlukan untuk mode hardware. Arsitektur Python dan DLL harus sama-sama 32-bit atau sama-sama 64-bit.

Mapping Web UI menggunakan Relay 1 untuk deret kiri, Relay 2 untuk deret kanan, dan Relay 3 untuk deret depan. Setiap deret dapat dipilih secara independen atau dikombinasikan. Relay 4 tidak digunakan dan selalu dipertahankan dalam kondisi mati.

Web UI hardware dijalankan dengan `python gui.py`. Untuk mencoba builder dan seluruh alur tanpa DLL atau relay, jalankan `python gui.py --demo`. Peneliti dapat membuat konfigurasi baru pada **Build**, menekan **Gunakan di Execute**, lalu memasukkan ID partisipan dan informasi sesi. Konfigurasi default adalah `configs/pebt_yamawaki_2023_draft.json`, yang diturunkan dari contoh paper Yamawaki et al. (2023). Operator memilih kondisi `interactive_agent` atau `non_interactive_agent` sesuai assignment penelitian.

Server sengaja hanya dapat diakses dari komputer yang sama. Setiap proses memakai control token acak, dan sesi diikat ke tab browser yang memulainya. Runner mengirim heartbeat; jika tab tersembunyi atau koneksi browser terputus sekitar 15 detik, backend meng-abort sesi, mengirim perintah OFF, dan memeriksa readback. Relay 4 selalu diminta OFF. Jika OFF/readback gagal, aplikasi menampilkan status relay tidak diketahui; operator wajib memakai pemutus daya fisik dan memeriksa beban secara langsung.

Baseline PEBT mengimplementasikan SET1 dan SET2, masing-masing 24 pilihan antara SEST dan DIFT. Setiap SET terdiri dari 12 trial dengan 12 lampu lalu 12 trial dengan 4 lampu. Panah kiri memilih SEST (lampu mati dan waktu tunggu dapat lebih lama), sedangkan panah kanan memilih DIFT (lampu menyala dan waktu tunggu lebih singkat). Halaman instruksi dan stimulus dua kartu dengan 12 indikator lampu menggantikan form/sketchpad OpenSesame. Distribusi waktu tunggu, demonstrasi 12 lampu selama 10 detik, dan jeda kontak agen sekitar lima menit dipetakan dari paper.

Setiap sesi mencatat hash konfigurasi, urutan trial, kondisi partisipan, durasi halaman instruksi, pilihan SEST/DIFT, response time, waktu tunggu, keadaan relay, durasi jeda blok, serta status selesai/abort/error. Ringkasan menghitung jumlah SEST/DIFT per SET dan perubahan utama penelitian (`SEST SET2 - SEST SET1`). Event CSV di-flush setiap baris agar data parsial tetap tersedia jika proses berhenti mendadak.

Konfigurasi tersebut masih berstatus **draft**. Sebelum pengambilan data final, peneliti perlu mengonfirmasi deret relay yang mewakili 4 lampu, pasangan tepat faktor timing, detail latihan dan pengulangan konfirmasi lampu, terjemahan instruksi, serta aset/prosedur karakter kucing dan Piyota/Wizard-of-Oz. Aset eksternal dari paper tidak dibundel dalam repository.

Instruksi instalasi, konfigurasi, eksekusi, troubleshooting, serta batas validasi tersedia pada [README proyek](https://github.com/MarcoAlandAdinanda/PEBT_UGM#readme). Runbook Web UI tersedia di `docs/local-web-ui.md`, sedangkan pemetaan parameter paper tersedia di `docs/pebt-protocol-mapping.md` dalam repository.

## 2. Ketersediaan File Software Relay Control

Software kontrol relay dapat diakses melalui tautan berikut:

- **Repository lengkap:** [https://github.com/MarcoAlandAdinanda/PEBT_UGM](https://github.com/MarcoAlandAdinanda/PEBT_UGM) — untuk melihat seluruh source code, dokumentasi, dan riwayat proyek.
- **Paket ZIP:** [https://github.com/MarcoAlandAdinanda/PEBT_UGM/archive/refs/heads/main.zip](https://github.com/MarcoAlandAdinanda/PEBT_UGM/archive/refs/heads/main.zip) — untuk mengunduh seluruh isi branch `main` tanpa menggunakan Git.
- **File `main.py` langsung:** [https://raw.githubusercontent.com/MarcoAlandAdinanda/PEBT_UGM/main/main.py](https://raw.githubusercontent.com/MarcoAlandAdinanda/PEBT_UGM/main/main.py) — untuk membuka atau mengunduh hanya command-line tool lama.

Untuk menjalankan aplikasi eksperimen, gunakan repository lengkap atau paket ZIP karena `gui.py` memerlukan backend (`web_app.py`, `web_runtime.py`), aset dalam folder `web/`, engine/logger, relay controller, dan file konfigurasi dalam folder proyek. Tautan `main.py` saja hanya menyediakan command-line tool satu kali dan bukan Web UI.

Tautan repository dan ZIP mengikuti isi branch `main` yang sudah dipublikasikan. Karena itu, rilis Web UI lokal harus di-commit dan di-push terlebih dahulu sebelum tautan ini dikirim sebagai paket Web UI kepada klien; jika belum, tautan remote masih dapat menampilkan rilis CLI sebelumnya.

Perlu diperhatikan bahwa tautan tersebut menyediakan software kontrol Python. File vendor `Ydci.dll` dan driver USB tidak disertakan dalam repository. Keduanya harus diperoleh dari vendor relay atau pengelola proyek yang memiliki hak distribusi. Untuk Web runtime, DLL harus menyediakan `YdciOpen`, `YdciRlyOutput`, `YdciRlyOutputStatus`, dan `YdciClose`.

Verifikasi software dapat dilakukan melalui mode demo dan test otomatis tanpa hardware. Verifikasi `YdciOpen`, output/readback relay, `YdciClose`, wiring, dan timing cahaya aktual tetap memerlukan Windows dengan driver/DLL resmi serta RLY-P4-U fisik.
