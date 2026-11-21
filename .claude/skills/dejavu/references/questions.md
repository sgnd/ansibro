# The interview

Ask a few questions at a time, in the user's language, in plain words. Each question fills one field of `handover.yml`. Write `null` for "I don't know yet": the documents then say "not provided". Never ask for a password.

Ask in this order. Skip a question when `handover.yml` already has the answer.

## 1. Language and documents

| Field | Ask (id) | Ask (en) | Default / example |
| --- | --- | --- | --- |
| `lang` | Dokumen dalam Bahasa Indonesia, Inggris, atau keduanya? | Should the documents be in Indonesian, English, or both? | `id` for an Indonesian company or government client; `[id, en]` for a foreign-owned client (PT PMA) |
| `environment` | Sistem ini disebut apa di dokumen? Misalnya Produksi atau Staging. | What should the documents call this system? For example Production or Staging. | `Produksi` |
| `document.number` | Nomor dokumen teknisnya? | The number of the technical document? | `001/DOK/<VENDOR>/<month in Roman>/<year>` |
| `document.prepared_by`, `reviewed_by`, `approved_by` | Siapa yang menyusun, memeriksa, dan menyetujui dokumen ini? | Who prepared, reviewed and approved these documents? | names |

## 2. The BAST

| Field | Ask (id) | Ask (en) | Default / example |
| --- | --- | --- | --- |
| `bast.number` | Nomor BAST-nya? | The BAST number? | `001/BAST/<VENDOR>/XI/2026` |
| `bast.date`, `bast.place` | Tanggal dan tempat serah terima? | Date and place of the handover? | `2026-11-04`, `Jakarta` |
| `bast.contract` | Apa dasar pekerjaannya: nama, nomor, dan tanggal kontrak, SPK, atau PO? | What is the basis of the work: the name, number and date of the contract, SPK or PO? | |
| `bast.stage` | Ini serah terima tunggal, PHO (pekerjaan selesai, masa garansi mulai), atau FHO (akhir)? | Is this a single handover, a provisional one (work done, warranty starts), or the final one? | `single`; with `pho` also `fho_date` |
| `bast.first_party` | Siapa PIHAK PERTAMA: vendor (yang menyerahkan) atau klien? | Who is the first party: the vendor (handing over) or the client? | `vendor` |
| `bast.meterai` | Perlu kotak meterai Rp10.000? Di sisi siapa? | Do you need a Rp10,000 stamp-duty box? On whose side? | `{enabled: false, side: client}` |
| `bast.copies` | Dicetak berapa rangkap? | How many printed copies? | `2` |
| `bast.mengetahui`, `bast.witnesses` | Ada yang ikut mengetahui atau menjadi saksi? Nama, jabatan, perusahaan. | Does anyone acknowledge or witness it? Name, title, company. | `[]` |

## 3. The two parties

| Field | Ask (id) | Ask (en) |
| --- | --- | --- |
| `client.name`, `client.short`, `client.address` | Nama lengkap perusahaan klien, nama pendeknya, dan alamatnya? | The client company's full name, a short name, and its address? |
| `client.signer` | Siapa yang menandatangani dari pihak klien? Nama dan jabatan. | Who signs for the client? Name and title. |
| `vendor.*` | Sama untuk perusahaan Anda (vendor): nama, alamat, telepon, email, situs web, penandatangan. | The same for your company (the vendor): name, address, phone, email, website, signer. |
| `client.logo`, `vendor.logo` | Ada file logo (PNG atau SVG)? Di mana? | Is there a logo file (PNG or SVG)? Where? |

## 4. The system

| Field | Ask (id) | Ask (en) | Notes |
| --- | --- | --- | --- |
| `provider`, `servers.<name>.provider`, `.region` | Server-servernya di mana? Misalnya DigitalOcean Singapura, atau di gedung sendiri. | Where do the servers run? For example DigitalOcean Singapore, or on-premises. | |
| `servers.<name>.public_ip` | Server ini punya IP publik? | Does this server have a public IP? | Ask only for servers whose `host` is a private IP |
| `dns.mode` | Bagaimana orang membuka alamat *.<domain>: lewat DNS biasa, DNS kantor, atau belum ada DNS? | How do people reach *.<domain>: normal DNS, company DNS, or no DNS yet? | `public`, `internal`, `hosts` |
| `dns.provider`, `dns.owner`, `dns.proxied` | Domain dikelola di mana, siapa pemiliknya, dan apakah ada CDN di depannya (misalnya Cloudflare)? | Where is the domain managed, who owns it, and is there a CDN in front (like Cloudflare)? | |

## 5. People and access

| Field | Ask (id) | Ask (en) | Notes |
| --- | --- | --- | --- |
| `people` | Siapa saja staf klien yang perlu akses? Untuk tiap orang: nama, perannya (hanya halaman web / juga SSH / akan menjalankan ansibro sendiri), laptopnya Windows, Mac, atau Linux, dan IP internetnya. | Which client staff need access? For each: name, role (web pages only / also SSH / will run ansibro), Windows, Mac or Linux laptop, and their internet IP. | persona `viewer`, `operator`, `successor`. Their IP: they open https://ifconfig.me |
| `ssh_handover` | Klien bisa membuat kunci SSH sendiri, atau kami buatkan? | Can the client make their own SSH key, or should we make one? | `client_key` (safest) or `generated` |
| `state_owner` | Setelah serah terima, siapa yang memegang folder ansibro untuk mengubah sistem: vendor atau klien? | After the handover, who keeps the ansibro folder to change the system: the vendor or the client? | `vendor`. The client always gets a copy in the credentials file |

When `facts` warns that a person's IP is outside an allow-list, tell the user now: the vendor adds it to `config.yml` and runs `./install.sh` (with consent).

## 6. Delivery and after

| Field | Ask (id) | Ask (en) | Default |
| --- | --- | --- | --- |
| `delivery.kdbx_channel` | Bagaimana file kredensial diserahkan? Misalnya USB langsung. | How will the credentials file travel? For example a USB stick in person. | |
| `delivery.passphrase_channel`, `recipient` | Kata sandi pembukanya disampaikan lewat jalur lain, misalnya telepon. Kepada siapa? | Its passphrase travels another way, for example a phone call. To whom? | must differ from the file's channel |
| `password_change_days` | Dalam berapa hari klien mengganti semua kata sandi? | Within how many days does the client change every password? | `7` |
| `vendor_access_end` | Kapan akses vendor (kunci SSH dan IP) dicabut? | When is the vendor's access (SSH key and IPs) removed? | a date |
| `restore_drill` | Pernah dicoba memulihkan dari backup? Kapan? | Was a restore from backup ever tested? When? | `null` = never |

## 7. Support and free text

| Field | Ask (id) | Ask (en) |
| --- | --- | --- |
| `support.contacts`, `hours`, `sla` | Siapa yang dihubungi bila ada masalah, jam berapa, dan berapa cepat responsnya? | Who does the client call when something is wrong, at what hours, and how fast is the response? |
| `support.warranty` | Ada garansi? Berapa bulan, sampai kapan, mencakup apa? | Is there a warranty? How many months, until when, covering what? |
| `out_of_scope` | Ada yang bukan bagian pekerjaan ini? | Is anything not part of this work? |
| `extra_apps` | Ada aplikasi milik klien sendiri di cluster ini? | Does the client run their own apps on this cluster? |
| `summary_note`, `notes` | Ada catatan lain untuk ringkasan atau BAST? | Anything else for the summary or the BAST? |
