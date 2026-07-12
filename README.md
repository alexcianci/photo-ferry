# iPhone Photo Drop

A local, on-demand HTTPS receiver that lets your iPhone send photos and videos to this
Windows PC's `Pictures\iPhone Drop\` folder over your home Wi-Fi. No cloud, no account,
no internet exposure. This is **not** AirDrop (AWDL is unavailable on Windows); it is a
self-hosted local web receiver.

## Install (once)

```powershell
cd iphone-photo-drop
powershell -ExecutionPolicy Bypass -File .\setup\setup.ps1
```

This creates a virtual environment, installs the app, generates a self-signed TLS
certificate, adds a scoped Windows Firewall rule (one UAC prompt: Private profile,
LocalSubnet only, port 8443), and places a **Receive from iPhone** shortcut in your
Pictures folder.

## Use

1. Double-click **Receive from iPhone** in your Pictures folder.
2. Scan the QR code with the iPhone Camera app; open the link in Safari.
3. Tap through the one-time "Not Private" warning (self-signed certificate).
4. Enter the 6-digit PIN shown on the PC.
5. Choose photos/videos and upload. They land in `Pictures\iPhone Drop\`.
6. Click **Stop** (or wait for the 10-minute idle timeout). The port closes.

## Security

- Nothing listens on the network unless the window is open.
- Bound to your LAN IP only; firewall scoped to LocalSubnet + Private profile.
- The app also rejects any client outside your subnet.
- HTTPS end to end; two-factor local auth (128-bit QR token + 6-digit PIN);
  lockout after 5 wrong PINs.
- Photo/video allowlist, filename sanitization, per-file (2 GB) and per-session (20 GB)
  size caps, atomic writes. Files are never executed.
- The running app makes zero outbound connections.

## Certificate fallback (if openssl is unavailable)

Setup uses `openssl` (bundled with Git for Windows). If it is missing, generate the cert
manually with PowerShell and export it to `%LOCALAPPDATA%\iPhonePhotoDrop\cert.pem` /
`key.pem`, then re-run setup. See `New-SelfSignedCertificate` docs.

## Development

```powershell
.\.venv\Scripts\python.exe -m pytest
```
