<p align="center">
  <img src=".github/assets/winsper-social-card.png" alt="Winsper banner with full and compact recording HUDs" width="900">
</p>

<h1 align="center">Winsper</h1>

<p align="center">Talk it out. Winsper puts your words to work in the app you're already using.</p>

<p align="center">
  <a href="https://winsper.app/download/">Download for Windows</a> ·
  <a href="https://winsper.app/">winsper.app</a> ·
  <a href="docs/USAGE.md">Guide</a>
</p>

<p align="center">
  <a href="https://github.com/WinsperApp/winsper/actions/workflows/ci.yml"><img src="https://github.com/WinsperApp/winsper/actions/workflows/ci.yml/badge.svg" alt="CI status"></a>
</p>

Hold a shortcut, speak, release. Winsper writes at your cursor without a copy-paste detour. Dictate uses on-device speech recognition. Polish can clean up a rough thought or change text you've selected, with the destination app as context.

## Why it feels different

- **It meets you where you type.** Write an email in Outlook, a quick reply in Slack, or a prompt in your coding tool. App-aware Polish uses that destination to guide tone and format.
- **Two ways to Polish.** Speak freely with nothing selected to tidy the thought; select text and speak an instruction to change only that text.
- **Small when you want it small.** Choose a full status HUD, a compact listening wave, or sound-only feedback. Add personal corrections, text shortcuts, and spoken formatting as needed.
- **Local first.** Dictation and the default Polish engine run on your PC. Ollama and custom model settings are available for people who want more control.

Full HUD and compact HUD, rendered from the app's own interface:

<p align="center">
  <img src=".github/assets/hud-listening-light.png" alt="Winsper full recording HUD with listening status" width="500">
  <img src=".github/assets/hud-compact-light.png" alt="Winsper compact recording HUD with listening wave" width="180">
</p>

## Get started

1. Download the [Windows installer](https://winsper.app/download/).
2. Run Winsper and choose a speech model in setup. Model downloads need internet; dictation then runs locally.
3. Hold your Dictate shortcut, speak, and release. Enable Polish if you want local rewriting too.

The current direct installer is **not code-signed**. Windows may show an *Unknown publisher* or SmartScreen warning. Verify the [published checksum](https://winsper.app/download/) and never disable antivirus protection to install Winsper. The release currently targets Windows 10/11 x64. Bluetooth headphones can be used for playback, but Bluetooth hands-free microphone input is intentionally unsupported for safety.

Speech and default Polish processing stay on your PC. Model downloads, update checks, the website, and support may use the network. A remote model endpoint receives text only if you configure one. See [Privacy](https://winsper.app/privacy/) for details.

## Build from source

On Windows with Python 3.12 or 3.13 and PowerShell:

```powershell
.\scripts\setup.ps1
.\scripts\run.ps1
```

Run the deterministic tests with `.\scripts\test.ps1`. Hardware tests are separate and opt-in. See the [full guide](docs/USAGE.md) for shortcuts, model choices, configuration, troubleshooting, and the project layout.

## Project

- [Contributing](CONTRIBUTING.md) · [Report a security issue](SECURITY.md)
- [MIT license](LICENSE) · [Third-party and model terms](THIRD_PARTY_NOTICES.md) · [Code signing policy](CODE_SIGNING.md)
- [Download and checksum](https://winsper.app/download/)
