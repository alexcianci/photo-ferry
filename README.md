# Photo Drop

Send photos and videos from your iPhone to a Windows PC over your own Wi-Fi. No cloud, no
account, nothing leaves your local network. You launch it from an icon, scan a QR code with
your iPhone, and the files save straight to your Pictures folder at full quality.

This is **not** AirDrop. AirDrop rides on Apple's proprietary AWDL protocol, which has no
supported implementation on Windows. Photo Drop instead runs a tiny HTTPS receiver on your
PC that your iPhone uploads to through Safari. Same result, fully local.

## Why it's safe

- **Nothing listens until you open it.** No background service, no always-on port.
- **Local only.** The receiver binds to your LAN address and the Windows Firewall rule is
  scoped to your local subnet on the Private profile. It is unreachable from the internet.
- **Two-factor, per session.** A 128-bit token in the QR code plus a 6-digit code shown on
  your PC. Five wrong codes shuts it down.
- **Encrypted in transit** over HTTPS, so no one else on your Wi-Fi can read the photos.
- **Strict about files.** Photos and videos only, filenames sanitized, size-capped, written
  atomically, never executed.
- **Zero outbound.** The running app never phones home.

## Requirements

- Windows 10 or 11
- Python 3.12+ (3.14 recommended)
- Git for Windows (setup uses its bundled `openssl`)
- An iPhone on the same Wi-Fi network

## Install (once)

```powershell
git clone https://github.com/alexcianci/iphone-photo-drop.git photo-drop
cd photo-drop
powershell -ExecutionPolicy Bypass -File .\setup\setup.ps1
```

Setup creates a virtual environment, installs the app, generates a local certificate
authority and server certificate, adds a scoped Windows Firewall rule (one UAC prompt:
Private profile, LocalSubnet only, port 8443), and puts an **Import from iPhone** shortcut
in your Pictures folder.

## Use

1. Double-click **Import from iPhone** in your Pictures folder.
2. Scan the QR code with the iPhone Camera app and open the link in Safari.
3. Enter the 6-digit code shown on your PC.
4. Tap **Select photos or videos**, choose your files, tap **Publish**. Each gets a green
   check as it arrives in `Pictures\iPhone Drop\`.
5. Click **Stop** (or let the 10-minute idle timeout close it).

### Stop the certificate warning (optional, once per phone)

Because the certificate is generated locally rather than by a public authority, Safari shows
a one-time "not private" warning. To remove it for good:

1. On the phone page, tap **Trust this PC once**. Safari downloads a profile.
2. Install it: Settings, then the downloaded profile, then Install.
3. Enable trust: Settings > General > About > Certificate Trust Settings, and turn on the
   "Photo Drop Local CA" toggle.

After that the warning never returns, even when the session code or your PC's IP changes, and
only that one phone trusts only your PC's own local certificate authority.

## Photo quality

Files are saved exactly as your iPhone sends them: full resolution, no re-encoding or
compression on the PC side. Note that when picking from your Photo Library, iOS itself may
convert HEIC to full-resolution JPEG during a web upload; that is iOS behavior, not this tool.

## Development

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## License

MIT. See [LICENSE](LICENSE). Third-party credits in [NOTICE](NOTICE).

## Support

If Photo Drop saved you a cable hunt, there is a **Sponsor** button at the top of
the repo. No pressure — the tool is free and always will be.
