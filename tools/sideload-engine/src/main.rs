//! gn-sideload — the GoldenNugget Mobile sideload engine.
//!
//! A thin CLI wheel around the `isideload` crate (nab138, MIT): it signs an IPA
//! with a free Apple ID (GrandSlam login, device registration, certificate,
//! provisioning) and installs it over usbmuxd. The GoldenNugget desktop app
//! drives the process and relays every user decision through dialogs.
//!
//! # Protocol (stdout, one line at a time; tracing goes to stderr)
//!
//! ```text
//! PROTOCOL 1                   sent once the engine started up
//! PROGRESS <0-100>             overall progress (sign 0-30, install 30-100)
//! STAGE <name>                 stage label (sign | install)
//! PROMPT PASSWORD              the Apple ID password is wanted on stdin
//! PROMPT 2FA <json>            two-factor code params (serde TwoFactorCallbackParams);
//!                              answer: code | d (send to devices) | r (resend) |
//!                              p<id> (send SMS) | q (abort)
//! PROMPT TEAM <json>           {"teams": [{"id":…, "name":…}]};  answer: 1-based index
//! PROMPT CERTS <json>          certificate list to revoke;  answer: comma 1-based indices
//! RESULT OK                    app installed
//! RESULT ERROR <message>       aborted (exit code 1)
//! ```
//!
//! Usage:
//!
//! ```text
//! gn-sideload --apple-id me@icloud.com [--password PW | --password-stdin] [--udid UDID] <ipa>
//! gn-sideload --version
//! ```
//!
//! `--password-stdin` waits for `PROMPT PASSWORD` and then reads one line, so
//! the password never shows up in the process list.
use std::io::Write;
use std::path::PathBuf;
use std::process::exit;

use idevice::usbmuxd::{UsbmuxdAddr, UsbmuxdConnection};
use isideload::anisette::remote_v3::RemoteV3AnisetteProvider;
use isideload::auth::apple_account::{
    AppleAccount, TwoFactorCallbackParams, TwoFactorCallbackResponse,
};
use isideload::dev::certificates::DevelopmentCertificate;
use isideload::dev::developer_session::DeveloperSession;
use isideload::dev::developer_session::DevicesApi;
use isideload::dev::teams::DeveloperTeam;
use isideload::sideload::builder::MaxCertsBehavior;
use isideload::sideload::install::install_app;
use isideload::sideload::{SideloaderBuilder, TeamSelection};
use isideload::util::callbacks::ExtensionsBehaviorCallbackBox;
use isideload::util::device::IdeviceInfo;
use isideload::util::keyring_storage::KeyringStorage;
use rootcause::prelude::*;

fn out(line: &str) {
    println!("{line}");
    let _ = std::io::stdout().flush();
}

fn error_text(err: impl std::fmt::Display) -> String {
    format!("{err}").replace('\n', "  ")
}

fn fail(message: impl AsRef<str>) -> ! {
    let text = message.as_ref().replace('\n', "  ");
    let trunc: String = text.chars().take(400).collect();
    out(&format!("RESULT ERROR {trunc}"));
    exit(1)
}

fn read_line() -> String {
    let mut line = String::new();
    let _ = std::io::stdin().read_line(&mut line);
    line
}

/// reqwest's rustls bridge refuses to build a Client until exactly one
/// process-wide crypto provider is registered (it panics with "No rustls
/// crypto provider is configured" otherwise — seen live at startup, before
/// the anisette provider could even be created). Install the `ring` one on
/// best effort: a duplicate install (another provider already registered by
/// a dependency) returns Err, which is fine.
fn install_crypto_provider() {
    let _ = rustls::crypto::ring::default_provider().install_default();
}

/// Team chooser for `TeamSelection::PromptOnce` (sync — stdin reads are fine).
fn choose_team(teams: &Vec<DeveloperTeam>) -> Option<String> {
    let items: Vec<_> = teams
        .iter()
        .map(|t| serde_json::json!({"id": t.team_id, "name": t.name}))
        .collect();
    out(&format!("PROMPT TEAM {}", serde_json::json!({"teams": items})));
    let t = read_line().trim().to_string();
    if t.eq_ignore_ascii_case("q") {
        return None;
    }
    match t.parse::<usize>() {
        Ok(index) if index >= 1 && index <= teams.len() => Some(teams[index - 1].team_id.clone()),
        _ => None,
    }
}

#[tokio::main]
async fn main() {
    install_crypto_provider();
    let raw: Vec<String> = std::env::args().skip(1).collect();

    if raw.iter().any(|a| a == "--version") {
        println!("gn-sideload {}", env!("CARGO_PKG_VERSION"));
        return;
    }

    let mut apple_id: Option<String> = None;
    let mut password: Option<String> = None;
    let mut password_stdin = false;
    let mut wanted_udid: Option<String> = None;
    let mut ipa: Option<PathBuf> = None;

    let mut it = raw.iter();
    while let Some(arg) = it.next() {
        match arg.as_str() {
            "--apple-id" => apple_id = it.next().cloned(),
            "--password" => password = it.next().cloned(),
            "--password-stdin" => password_stdin = true,
            "--udid" => wanted_udid = it.next().cloned(),
            other if other.starts_with("--") => {
                out(&format!("RESULT ERROR unknown option: {other}"));
                exit(2);
            }
            other => ipa = Some(PathBuf::from(other)),
        }
    }

    out("PROTOCOL 1");

    let apple_id = apple_id.unwrap_or_else(|| {
        out("RESULT ERROR usage: gn-sideload --apple-id ID [--password PW | --password-stdin] [--udid UDID] <ipa>");
        exit(2);
    });
    if password_stdin {
        out("PROMPT PASSWORD");
        let line = read_line();
        let trimmed = line.trim_end_matches(['\n', '\r']).to_string();
        password = Some(trimmed);
    }
    let password = password.filter(|p| !p.is_empty()).unwrap_or_else(|| {
        fail("an Apple ID password is required");
    });
    let ipa = ipa.unwrap_or_else(|| {
        fail("a path to the .ipa to install is required");
    });

    run(apple_id, password, wanted_udid, ipa).await;
}

async fn run(apple_id: String, password: String, wanted_udid: Option<String>, ipa: PathBuf) {
    let get_2fa_code = |params: TwoFactorCallbackParams| async move {
        out(&format!(
            "PROMPT 2FA {}",
            serde_json::to_string(&params).unwrap_or_else(|_| "{}".to_string())
        ));
        let t = read_line().trim().to_string();
        if t.eq_ignore_ascii_case("d") {
            Ok(TwoFactorCallbackResponse::SendToDevices)
        } else if t.eq_ignore_ascii_case("r") {
            Ok(TwoFactorCallbackResponse::ResendCode)
        } else if t.eq_ignore_ascii_case("q") {
            Ok(TwoFactorCallbackResponse::Abort)
        } else if let Some(rest) = t.strip_prefix('p') {
            rest.trim()
                .parse::<u32>()
                .map(TwoFactorCallbackResponse::SendSms)
                .map_err(|e| report!("invalid SMS choice: {e}"))
        } else {
            Ok(TwoFactorCallbackResponse::SubmitCode(t.clone()))
        }
    };

    let anisette = match RemoteV3AnisetteProvider::default() {
        Ok(provider) => provider.set_serial_number("2".to_string()),
        Err(report) => fail(error_text(&report)),
    };
    out("STAGE login");
    let account = AppleAccount::builder(&apple_id)
        .anisette_provider(anisette)
        .login(&password, get_2fa_code)
        .await;
    let mut account = match account {
        Ok(account) => account,
        Err(report) => fail(error_text(&report)),
    };
    out("INFO Signed in");
    let dev_session = match DeveloperSession::from_account(&mut account).await {
        Ok(session) => session,
        Err(report) => fail(error_text(&report)),
    };

    let mut usbmuxd = match UsbmuxdConnection::default().await {
        Ok(conn) => conn,
        Err(report) => fail(error_text(&report)),
    };
    let devices = match usbmuxd.get_devices().await {
        Ok(devices) => devices,
        Err(report) => fail(error_text(&report)),
    };
    if devices.is_empty() {
        fail("no devices connected via usbmuxd");
    }
    let target = match wanted_udid.as_deref() {
        Some(wanted) => {
            let wanted_lc = wanted.to_ascii_lowercase();
            match devices
                .iter()
                .find(|d| d.udid.to_ascii_lowercase() == wanted_lc)
            {
                Some(device) => device,
                None => fail(format!(
                    "device {wanted} is not connected (connect it and unlock)"
                )),
            }
        }
        None => &devices[0],
    };
    let addr = match UsbmuxdAddr::from_env_var() {
        Ok(addr) => addr,
        Err(report) => fail(error_text(&report)),
    };
    let provider = target.to_provider(addr, "golden-nugget");

    let device_info = match IdeviceInfo::from_device(&provider).await {
        Ok(info) => info,
        Err(report) => fail(error_text(&report)),
    };
    out(&format!(
        "INFO Device: {} ({})",
        device_info.name, device_info.udid
    ));

    let max_certs = |certs: Vec<DevelopmentCertificate>| async move {
        let items: Vec<_> = certs
            .iter()
            .map(|c| {
                serde_json::json!({
                    "name": c.name.clone(),
                    "machine_name": c.machine_name.clone(),
                })
            })
            .collect();
        out(&format!(
            "PROMPT CERTS {}",
            serde_json::json!({"certificates": items})
        ));
        let t = read_line().trim().to_string();
        if t.eq_ignore_ascii_case("q") {
            return Ok(None);
        }
        let serials: Vec<String> = t
            .split(',')
            .filter_map(|s| s.trim().parse::<usize>().ok())
            .filter(|&n| n >= 1 && n <= certs.len())
            .map(|n| certs[n - 1].serial_number.clone().unwrap_or_default())
            .collect();
        if serials.is_empty() {
            return Ok(None);
        }
        Ok(Some(serials))
    };

    let mut sideloader = SideloaderBuilder::<_, ExtensionsBehaviorCallbackBox>::new(
        dev_session,
        apple_id.clone(),
    )
    .team_selection(TeamSelection::PromptOnce(choose_team))
    .max_certs_behavior(MaxCertsBehavior::Prompt(max_certs))
    .storage(Box::new(KeyringStorage::new("goldennugget".to_string())))
    .machine_name("GoldenNugget".to_string())
    .build();

    // The device has to be registered with Developer Services before the
    // provisioning profile can name it — sign_app() does not do this itself.
    let team = match sideloader.get_team().await {
        Ok(team) => team,
        Err(report) => fail(error_text(&report)),
    };
    let dev_session = sideloader.get_dev_session();
    if let Err(report) =
        dev_session.ensure_device_registered(&team, &device_info.name, &device_info.udid, None).await
    {
        fail(error_text(&report));
    }

    out("STAGE sign");
    out("PROGRESS 0");
    let sign_progress = |p: f32| async move {
        let pct = (p * 100.0).clamp(0.0, 30.0);
        out(&format!("PROGRESS {pct:.0}"));
    };
    let (signed_path, _special) = match sideloader
        .sign_app(ipa, Some(team), true, Some(sign_progress), None, None)
        .await
    {
        Ok(result) => result,
        Err(report) => fail(error_text(&report)),
    };

    out("STAGE install");
    let install_progress = |progress: u64| {
        let pct = 30.0 + (progress.min(100) as f64 * 0.7);
        out(&format!("PROGRESS {pct:.0}"));
    };
    if let Err(report) = install_app(&provider, &signed_path, install_progress).await {
        let _ = std::fs::remove_dir_all(&signed_path);
        fail(error_text(&report));
    }
    let _ = std::fs::remove_dir_all(&signed_path);

    out("PROGRESS 100");
    out("RESULT OK");
}
