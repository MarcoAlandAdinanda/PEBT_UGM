# Web UI Lokal dan Backend Python

Dokumen ini adalah runbook operator untuk interface Web lokal PEBT UGM. Interface utama tidak lagi memakai Tkinter. `python gui.py` menjalankan server Python pada loopback dan menyajikan HTML, CSS, serta JavaScript milik repository ke browser pada PC yang sama.

## Quick start tanpa hardware

Jalankan dari root repository:

```bash
python gui.py --demo
```

Terminal menampilkan alamat yang aktif, biasanya `http://127.0.0.1:8765/`, lalu browser dibuka otomatis. Mode demo menggunakan `DemoRelayController`, sehingga semua alur dapat dicoba tanpa driver, `Ydci.dll`, atau RLY-P4-U.

Jika browser tidak boleh dibuka otomatis atau port default sedang dipakai:

```bash
python gui.py --demo --no-browser
python gui.py --demo --port 8877
```

Buka alamat yang dicetak terminal. Hentikan server dengan `Ctrl+C` setelah eksperimen selesai. Shutdown meminta abort jika masih ada sesi aktif, mengirim perintah OFF, memeriksa readback, lalu menutup relay. Jika OFF/readback gagal, proses menampilkan `[SAFETY ERROR]`, mengembalikan exit code nonzero, dan tidak mengklaim relay sudah mati; operator harus memakai pemutus daya fisik.

## Menjalankan mode hardware

1. Gunakan Windows 10/11, Python 3.7+, dan browser modern.
2. Instal driver USB vendor.
3. Pastikan arsitektur Python dan `Ydci.dll` sama-sama 32-bit atau sama-sama 64-bit.
4. Letakkan `Ydci.dll` resmi di folder proyek bersama `gui.py` atau pada Windows `PATH`. DLL harus menyediakan export `YdciOpen`, `YdciRlyOutput`, `YdciRlyOutputStatus`, dan `YdciClose`.
5. Atur DIP switch RLY-P4-U ke board ID `0`, hubungkan USB, dan periksa perangkat di Device Manager.
6. Jalankan:

   ```bash
   python gui.py
   ```

7. Pada **Manual**, klik **Hubungkan relay**, uji satu deret pada satu waktu, cocokkan **Actual readback**, lalu klik **Matikan semua**.

Browser hanya merupakan interface. Jalur kendali hardware yang sebenarnya adalah:

```text
Browser → HTTP localhost → backend Python → relay_controller.py
        → ctypes → Ydci.dll → USB → RLY-P4-U
```

Python memiliki relay lease tunggal, menjalankan clock eksperimen, memvalidasi action browser, melakukan readback, dan menulis log. Browser tidak dapat memanggil DLL secara langsung.

## Tiga mode kerja

### Build

**Build** memakai bento grid dan glassmorphism 2.0 untuk menampilkan struktur, inspector properti, audit protokol, dan workflow secara bersamaan.

1. Klik **Eksperimen baru**, atau pilih konfigurasi lalu klik **Buka**.
2. Susun hierarchy Experiment → Block → Trial → Phase menggunakan tambah, duplikasi, hapus, naik, dan turun.
3. Pilih node, edit inspector, lalu klik **Terapkan properti**.
4. Klik **Validasi** untuk memeriksa schema, ID, timing, response key, sumber, dan mapping lampu.
5. Klik **Simpan** untuk menulis file di `configs/user/`, atau **Gunakan di Execute** untuk mengirim snapshot builder yang sudah divalidasi.

Jika konfigurasi PEBT generator ringkas dibuka, backend mengembangkannya menjadi lima block dan 49 trial yang dapat diedit. Hasil ekspansi menjadi copy `draft`; file baseline tidak ditimpa.

### Execute

1. Pilih file atau gunakan snapshot dari Build.
2. Klik **Muat & validasi**, lalu periksa status, jumlah block/trial/page, durasi, dan config hash.
3. Isi ID partisipan, label sesi, dan kondisi partisipan bila tersedia.
4. Untuk protocol `demo`/`draft`, centang override pilot. Override hanya mengizinkan uji sistem dan tidak mengubah status ilmiah menjadi `validated`.
5. Klik **Mulai eksperimen**. Biarkan tab runner terlihat selama sesi.
6. Gunakan tombol layar atau keyboard sesuai konfigurasi. Gate instruksi/block menerima `Space`; `Esc` membuka konfirmasi abort.
7. Setelah selesai, klik **Kembali ke dashboard**. Hasil terbaru tampil pada kartu arsip sesi.

Runner partisipan memakai latar solid dan tidak memakai efek kaca. Bento grid dan glassmorphism hanya diterapkan pada workspace operator agar dekorasi tidak memengaruhi stimulus.

### Manual / System Setup

**Manual** hanya untuk setup dan diagnosis. Relay 1, 2, dan 3 masing-masing mewakili deret kiri, kanan, dan depan. Backend selalu membentuk `(left, right, front, 0)`, sehingga Relay 4 tetap OFF.

Manual control ditolak saat eksperimen aktif. Gunakan **Matikan semua** sebelum **Putuskan** atau sebelum meninggalkan setup hardware.

## Penyimpanan data

- Konfigurasi yang disimpan dari Build berada di `configs/user/`.
- Event sesi berada di `data/experiments/*.events.csv` dan di-flush per baris.
- Manifest/ringkasan berada di `data/experiments/*.summary.json` dan ditulis secara atomik.
- Backend Web selalu memakai root output terkontrol `data/experiments/`. Field kompatibilitas `data_directory` dalam JSON tidak mengalihkan output Web ke path lain.
- Backend monotonic clock adalah sumber response time utama. Estimasi elapsed time dari browser hanya disimpan sebagai detail pendukung.

Sebelum setiap fase, browser lebih dahulu menampilkan layar netral dan mengirim `ready`; relay baru diubah setelah ACK tersebut. Setelah stimulus benar-benar dicat pada frame browser, tab pemilik mengirim `presented`. Clock fase, deadline, dan window respons backend dimulai ketika ACK `presented` diterima. Masing-masing gate memiliki timeout lima detik; kegagalan dicatat sebagai `browser_presentation_timeout`. Pada timeout kedua relay mungkin sudah aktif, sehingga handler abort segera mengirim OFF dan memverifikasi readback. Setiap akhir fase juga memasuki layar transisi netral dan mematikan/memeriksa relay sebelum fase berikutnya.

## Keamanan lokal dan fail-safe

- Server hanya menerima bind address `127.0.0.1`, `localhost`, atau `::1`; alamat LAN ditolak.
- Request dengan `Host` non-lokal ditolak.
- Setiap proses menghasilkan control token acak. Semua request yang mengubah state wajib membawa token tersebut pada header `X-PEBT-Token`.
- Setiap tab menghasilkan `client_id` acak. Sesi diikat ke tab yang memulainya; action, heartbeat, long-poll, dan dismiss dari tab atau sesi lama ditolak.
- Response menerapkan Content Security Policy, `X-Frame-Options: DENY`, `nosniff`, `no-referrer`, dan `no-store`.
- Hanya satu sesi eksperimen dapat aktif. Sesi aktif mengunci Manual.
- Browser terlihat mengirim heartbeat setiap dua detik. Jika tab disembunyikan/terputus dan tidak ada heartbeat sekitar 15 detik, backend meng-abort sesi, memerintahkan OFF, dan memeriksa readback.
- Backend meminta OFF pada setiap batas fase, setelah trial, completion, abort, error, heartbeat timeout, dan shutdown. Jika perintah/readback gagal, state ditampilkan sebagai `[?, ?, ?, ?]` dengan peringatan keselamatan; gunakan pemutus daya fisik dan periksa beban.

Web UI ini sengaja bukan server jaringan. Jangan membuka port melalui firewall atau proxy. Kontrol software tetap harus dilengkapi wiring yang aman, isolasi beban, prosedur operator, dan pemutus daya fisik yang dapat dijangkau.

## Ringkasan API lokal

API digunakan oleh `web/app.js`; operator normal tidak perlu memanggilnya secara manual.

| Method | Endpoint | Fungsi |
|--------|----------|--------|
| `GET` | `/api/system` | Mode, versi Python, token proses, status relay/sesi, dan jumlah konfigurasi |
| `GET` | `/api/configs` | Daftar konfigurasi dalam `configs/` |
| `GET` | `/api/config?id=…&mode=builder|execute` | Muat dokumen dan ringkasan konfigurasi |
| `GET` | `/api/relay` | Connection, readback, mode, dan relay lease |
| `GET` | `/api/experiment?after=VERSION&timeout_ms=10000&session_id=SESSION_ID&client_id=CLIENT_ID` | Long-poll snapshot sesi milik tab; timeout maksimum 15 detik |
| `GET` | `/api/results` | Ringkasan hasil terbaru |
| `POST` | `/api/config/validate`, `/api/config/save` | Validasi atau simpan builder document |
| `POST` | `/api/relay/connect`, `/api/relay/apply`, `/api/relay/off`, `/api/relay/disconnect` | Operasi Manual |
| `POST` | `/api/experiment/start`, `/api/experiment/action`, `/api/experiment/heartbeat`, `/api/experiment/dismiss` | Lifecycle sesi dan input runner |

Body `POST` harus berupa `application/json`, dibatasi 5 MiB, dan menyertakan control token. Server menyajikan file Web statis serta API dari proses Python yang sama.

`POST /api/experiment/start` menyertakan `client_id` dan mengembalikan `session_id`. Semua action berikutnya wajib membawa keduanya. State interaktif juga membawa `gate_token` unik: kirim `continue` untuk instruction/block, `ready` untuk `phase_prepare`, `presented` setelah stimulus dicat, dan `response` beserta `key` saat `waiting_for` bernilai `phase`. Semua action selain abort wajib membawa `gate_token` layar yang sama; token terlambat/duplikat ditolak dengan HTTP 409. Abort tetap wajib membawa `session_id` dan `client_id`. Heartbeat serta dismiss juga wajib memakai scope sesi/tab tersebut.

## Verifikasi

```bash
python -m py_compile main.py relay_controller.py pebt.py experiment.py experiment_document.py web_runtime.py web_app.py gui.py
python -m unittest discover -s tests -v
```

Jika Node.js sudah tersedia, cek syntax modul browser tanpa instalasi tambahan:

```bash
node --check web/app.js
node --test tests/test_start_gate.mjs
```

Lakukan smoke test demo: buka ketiga mode, simpan konfigurasi uji, jalankan `configs/demo_experiment.json`, kirim respons, pastikan hasil dibuat, uji semua kombinasi Manual, dan konfirmasi vector/readback kembali `[0, 0, 0, 0]`.

Test otomatis dan demo tidak membuktikan komunikasi DLL atau timing lampu fisik. Verifikasi akhir membutuhkan Windows, driver dan `Ydci.dll` resmi, RLY-P4-U board ID `0`, beban lampu aktual, pemeriksaan `YdciOpen`/`YdciRlyOutput`/`YdciRlyOutputStatus`/`YdciClose`, uji kegagalan fail-safe, serta alat ukur bila onset cahaya merupakan variabel penelitian.
