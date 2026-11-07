# Offline install

For servers with no internet (for example only VPN access).

**1. Get a bundle.** Each release on GitHub has one for each Ubuntu version.
They come in parts (GitHub allows 2 GB per file); put the parts back together and check them:

```bash
cat ansibro-24.04.tar.gz.part* > ansibro-24.04.tar.gz
sha256sum -c ansibro-24.04.tar.gz.sha256   # on a Mac: shasum -a 256 -c ...
```

Or build one yourself: **on a machine with internet and Docker**, build a bundle for the Ubuntu version
of your servers. A Mac (Docker Desktop or OrbStack) works too. On a Mac or Linux machine with an ARM CPU,
building needs QEMU, which lets it run Intel/AMD programs.
This command installs it (the image is pinned, like in `versions.yml`):

```bash
docker run --privileged --rm tonistiigi/binfmt:qemu-v10.2.3@sha256:400a4873b838d1b89194d982c45e5fb3cda4593fbfd7e08a02e76b03b21166f0 --install amd64
```

```bash
./build-bundle.sh          # Ubuntu 24.04
./build-bundle.sh 26.04    # Ubuntu 26.04
```

This makes `dist/ansibro-<ubuntu>.tar.gz` (about 4 GB). It holds this project, apt packages,
Ansible and all Docker images from `versions.yml`. Your project folder is not changed.

**2. Copy it to the first manager**, together with your SSH private key and, if you use them,
your `tls_cert`/`tls_key`/`acme_ca_cert` files (the bundle leaves out keys and certificates).
The installer connects over SSH to every server, the first manager itself too, so that key must
be allowed on all servers. Then run the installer there:

```bash
tar -xzf ansibro-24.04.tar.gz
cd ansibro
cp config.example.yml config.yml   # set tls: selfsigned (or custom), and ssh.key
./install.sh
```

The installer sees the `bundle/` folder and uses it instead of the internet.
The servers' own apt settings are not changed.

Notes:
- Every server must run the bundle's Ubuntu version.
- Let's Encrypt needs internet. Use `tls: selfsigned`, `tls: custom`, or an ACME server
  in your network (`acme_server`, see `config.example.yml`).
- Time sync (chrony) needs a time server. Without internet, use one in your network. On each server:

  ```bash
  echo "server <time server ip> iburst" | sudo tee /etc/chrony/sources.d/local.sources
  # Ubuntu 26.04 only uses signed (NTS) time servers while it has them; allow your own one too:
  echo "authselectmode ignore" | sudo tee /etc/chrony/conf.d/offline.conf
  sudo systemctl restart chrony
  ```
