# Raspberry Pi 24/7 deployment

This runbook targets Ubuntu Server 24.04 LTS arm64 on a Raspberry Pi 4B with 4 GB RAM,
one active fan, and a 1 TB M.2 SATA SSD. A Pi 4B does not expose the Pi 5 PCIe connector;
the SATA HAT presents the SSD through a USB 3 bridge. Keep the first live deployment in
shadow mode for at least 24 hours and review its decisions before enabling DOCX writes.

## 1. Prepare the host

Install Ubuntu Server 24.04 LTS arm64 on the intended boot media. Raspberry Pi Imager
can write the image directly to the SSD, or Ubuntu can remain on microSD while only
application data uses the SSD. Raspberry Pi 4 uses EEPROM-controlled
[USB mass-storage boot](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#usb-mass-storage-boot).
Early Pi 4 revisions may require a bootloader update. Test the exact SATA bridge under
Linux before relying on SSD boot because some USB-SATA adapters behave differently when
Linux selects UAS mode.

After the first boot:

```bash
uname -m
lsblk -o NAME,MODEL,SERIAL,TRAN,SIZE,FSTYPE,MOUNTPOINTS
lsusb -t
findmnt /
cat /sys/class/thermal/thermal_zone0/temp
sudo apt update
sudo apt full-upgrade -y
sudo apt install -y ca-certificates curl git smartmontools usbutils
sudo systemctl enable --now fstrim.timer
sudo reboot
```

`uname -m` must report `aarch64`. Confirm the root filesystem or the dedicated data
mount is actually on the SSD. `lsusb -t` should show the SATA bridge on a `5000M` USB 3
path, not a `480M` USB 2 path. Follow the HAT manufacturer's cabling and power guidance;
the bridge design may require a short USB connector even though the board is shaped as
a HAT. Use the official
[Docker Engine for Ubuntu instructions](https://docs.docker.com/engine/install/ubuntu/)
to install Docker Engine, Buildx, and the Compose plugin from Docker's apt repository.
Ubuntu 24.04 and arm64 are supported. Then enable Docker at boot:

```bash
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
```

Log out and back in before using Docker without `sudo`. Membership in the `docker`
group is root-equivalent; grant it only to the administrator account.

Raspberry Pi recommends a good-quality 5.1 V, 3 A USB-C supply for the Pi 4B, whose USB
ports share a 1.2 A peripheral budget. Verify the SSD and HAT requirements and use the
HAT's supported external-power arrangement if that budget is insufficient. Do not feed
power through multiple paths unless the HAT manual explicitly permits it. For unattended
operation, a small UPS with clean-shutdown support is strongly recommended; a fan
protects thermals but not filesystem state during power loss.

A single fan is sufficient only if airflow reaches the Pi SoC and does not trap heat
from the SSD or bridge. If it is a simple always-on 5 V fan, verify it starts on every
boot. If it is GPIO-controlled, configure it according to the case/HAT instructions.
Record both temperature and throttling status during the soak instead of assuming the
fan makes the enclosure safe.

```bash
docker version
docker compose version
docker run --rm hello-world
```

## 2. Put persistent data on the SSD

If Ubuntu itself boots from the 1 TB SSD, `/srv` already uses SSD storage and no extra
mount is needed. Otherwise, mount the dedicated SSD at `/srv/auto-interner` by UUID in
`/etc/fstab`, verify it with `findmnt`, and test a reboot before starting the worker.
Do not format or repartition a device until its exact identity and backups are verified.

Create private bind-mount directories owned by the image's fixed UID/GID `10001`:

```bash
sudo install -d -m 0750 -o 10001 -g 10001 /srv/auto-interner/data
sudo install -d -m 0750 -o 10001 -g 10001 /srv/auto-interner/state
sudo install -d -m 0700 /srv/auto-interner/backups
findmnt -T /srv/auto-interner/data
df -h /srv/auto-interner/data
```

The Compose file refuses to create missing bind paths. This catches spelling mistakes,
but it cannot prove a separate SSD is mounted. Always run `findmnt -T` after a reboot.

## 3. Configure the application

Clone the repository to the SSD or the root filesystem, then create the ignored local
configuration:

```bash
git clone https://github.com/WeedenAndrew/auto_Interner.git
cd auto_Interner
cp .env.example .env
chmod 600 .env
```

Set at least these values in `.env`:

```dotenv
RECRUITING_YEAR=2027
ANTHROPIC_MODEL=<model-id-available-to-your-account>
ANTHROPIC_API_KEY=
SHADOW_MODE=true
AUTO_INTERNER_DATA_DIR=/srv/auto-interner/data
AUTO_INTERNER_STATE_DIR=/srv/auto-interner/state
AUTO_INTERNER_MEMORY_LIMIT=1536m
AUTO_INTERNER_MEMORY_RESERVATION=256m
AUTO_INTERNER_CPUS=2.0
HEALTHCHECK_MAX_AGE_SECONDS=10800
```

`HEALTHCHECK_MAX_AGE_SECONDS` must exceed the poll interval plus the longest expected
run. Populate `ANTHROPIC_API_KEY` only in this ignored host file. Never paste
`docker compose config` output into an issue because resolved environment values can
include the API key.

Copy the private base résumé to the cycle baseplate path:

```bash
sudo install -d -m 0750 -o 10001 -g 10001 \
  /srv/auto-interner/data/2027/baseplate
sudo install -m 0640 -o 10001 -g 10001 /path/to/base_resume.docx \
  /srv/auto-interner/data/2027/baseplate/base_resume.docx
```

## 4. Build and smoke-test

The image uses Debian Bookworm's matching `chromium` and `chromium-driver` packages and
the multi-architecture Python 3.12 slim base. It runs as UID/GID `10001`, publishes no
ports, drops all Linux capabilities, and uses a read-only root filesystem.

```bash
docker compose config --quiet
docker compose build --pull worker
docker compose --profile tools run --rm smoke
docker compose --profile tools run --rm browser-smoke
docker run --rm --entrypoint id auto-interner:local
```

The fixture smoke has no network and writes only to container tmpfs. The browser smoke
opens an in-memory page with networking disabled. `id` should report UID and GID `10001`.

## 5. Start in shadow mode

```bash
docker compose up -d worker
docker compose ps
docker compose logs --tail=200 worker
docker inspect --format '{{json .State.Health}}' auto-interner-worker-1
```

The daemon runs once immediately, then waits the configured interval after completion.
Docker starts it after host reboot because the service uses `restart: unless-stopped`.
An unhealthy status does not automatically restart a running container; inspect logs,
the heartbeat, storage availability, and configuration before deciding to restart it.

Useful checks:

```bash
docker compose exec worker python -m auto_interner.healthcheck
docker compose exec worker auto-interner manual-review-count --state-dir /app/state
sudo cat /srv/auto-interner/state/heartbeat.json
docker stats --no-stream auto-interner-worker-1
```

## 6. Complete the 24-hour soak

Keep `SHADOW_MODE=true` for at least twelve two-hour cycles. Record:

- container health and restart count;
- idle and peak memory, CPU, PID count, and filesystem use;
- Pi temperature and any throttling warnings;
- SSD/SATA bridge health, USB resets, I/O errors, TRIM support, and free space;
- run-summary count, durations, retries, and manual-review count;
- absence of leftover Chromium/chromedriver processes after each run;
- bounded Docker log configuration and log-file growth;
- clean stop/start behavior and persistence after one host reboot.

Representative commands:

```bash
docker inspect --format '{{.RestartCount}} {{json .HostConfig.LogConfig}}' \
  auto-interner-worker-1
docker stats --no-stream auto-interner-worker-1
docker compose top worker
du -sh /srv/auto-interner/data /srv/auto-interner/state
cat /sys/class/thermal/thermal_zone0/temp
command -v vcgencmd >/dev/null && vcgencmd get_throttled
sudo smartctl --scan-open
sudo smartctl -a /dev/sda
sudo fstrim -av
sudo dmesg --level=err,warn | grep -iE 'under-voltage|usb|uas|reset|i/o error'
```

Adapt the SATA device name and any `smartctl -d` option based on `lsblk` and
`smartctl --scan-open`; never assume `/dev/sda` identifies the intended SSD. Any repeated
USB reset, UAS error, undervoltage warning, thermal throttling, or I/O error blocks Phase
7 acceptance. The phase remains open until the arm64 smoke tests and this soak pass on
the rebuilt server.

## 7. Enable document generation

Review every shadow-mode disqualification and a sample of passes. When the results are
acceptable, change `SHADOW_MODE=false` and recreate the worker:

```bash
docker compose up -d --force-recreate worker
docker compose logs --tail=200 worker
```

Generated documents appear at:

```text
/srv/auto-interner/data/<year>/<company>/<role>_<MM-DD-YY>.docx
```

## 8. Backup and recovery

Stop the worker so the backup captures one consistent state boundary:

```bash
docker compose stop worker
sudo tar --acls --xattrs -C /srv/auto-interner \
  -czf /srv/auto-interner/backups/auto-interner-$(date -u +%Y%m%dT%H%M%SZ).tar.gz \
  data state
docker compose start worker
```

Copy backups to another physical device or encrypted remote destination. A backup on
the same SSD is not protection from SSD failure. To restore, stop the worker, preserve
the current directories, extract one verified backup under `/srv/auto-interner`, restore
UID/GID `10001`, and run the fixture smoke before starting the worker.

For upgrades:

```bash
git pull --ff-only
docker compose build --pull worker
docker compose up -d worker
docker image prune
```

Take a backup first. Do not use destructive Git commands or delete runtime directories
as part of an application upgrade.
