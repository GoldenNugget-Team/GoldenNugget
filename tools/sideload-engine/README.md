# gn-sideload

The GoldenNugget Mobile sign-and-sideload engine — a thin CLI wheel around the
[`isideload`](https://github.com/nab138/isideload) crate (MIT), which powers
[nab138/iloader](https://github.com/nab138/iloader). It signs an IPA with a
free Apple ID (GrandSlam login, remote v3 anisette, device registration,
development certificate, provisioning profiles) and installs it over usbmuxd.

Unlike `xtool` this is plain Rust — it builds and runs on **macOS, Linux and
Windows** (Windows needs usbmuxd served by Apple Devices/iTunes).

## Build

```sh
cargo build --release        # → target/release/gn-sideload[.exe]
```

Linux needs the D-Bus development headers: `isideload` persists its signing
state through the platform keyring, whose Linux backend
(`dbus-secret-service` → `libdbus-sys`) needs `dbus-1.pc` and aborts the build
without it. Install the headers first:

```sh
sudo apt-get install -y libssl-dev pkg-config libdbus-1-dev
```

The GoldenNugget desktop app discovers the binary itself: settings override
(`mobile_helper/engine_path`) → PATH → bundled copy (PyInstaller root) →
this checkout's `target/release/`. The helper dialog also has a
"Build Engine (cargo)" button that runs the build for the user.

## Usage

```
gn-sideload --apple-id me@icloud.com [--password PW | --password-stdin] [--udid UDID] <ipa>
gn-sideload --version
```

`--password-stdin` waits for the engine's `PROMPT PASSWORD` line and then reads
one line, so the password never appears in the process list (credentials are
only ever sent to Apple).

## Line protocol (stdout; everything else goes to stderr)

```
PROTOCOL 1                   engine started up
PROGRESS <0-100>             overall progress (sign 0-30, install 30-100)
STAGE <name>                 stage label (login | sign | install)
PROMPT PASSWORD              password wanted on stdin
PROMPT 2FA <json>            serde `TwoFactorCallbackParams`; answer: code | d
                             (send to devices) | r (resend) | p<id> (send SMS)
                             | q (abort)
PROMPT TEAM <json>           {"teams":[{"id":…,"name":…}]}; answer: 1-based index
PROMPT CERTS <json>          certificates to revoke; answer: comma 1-based indices
RESULT OK                    app installed
RESULT ERROR <message>       aborted (exit 1)
```

Free-account constraints surfaced to the user: 3 active sideloads, 2
development certificates, provisioning profiles expire after 7 days, and a
dev-signed install on iOS 16+ needs Developer Mode enabled on the device.

## Notes

- Signing state (certificate, team choice) persists in the platform keyring
  (`KeyringStorage`, service `goldennugget`); the Apple ID password never is.
- Machine name on the certificate is `GoldenNugget` so a user can spot it in
  Apple's certificate list.
- `iloader#337`-style Windows path translation: the engine always receives the
  IPA path as an argument from the same process that spawned it, so no shell
  re-quoting happens; report new Windows path issues against `isideload`.
