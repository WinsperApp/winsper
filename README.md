<p align="center">
  <img src=".github/assets/winsper-social-card.png" alt="Winsper banner with full and compact recording HUDs" width="900">
</p>

<h1 align="center">Winsper</h1>

<p align="center">Less typing. More you.</p>

<p align="center">
  <a href="https://winsper.app/download/">Download for Windows</a> ·
  <a href="https://github.com/WinsperApp/winsper/releases/latest">Release notes</a> ·
  <a href="https://winsper.app/">winsper.app</a> ·
  <a href="docs/USAGE.md">Guide</a>
</p>

<p align="center">
  <a href="https://github.com/WinsperApp/winsper/actions/workflows/ci.yml"><img src="https://github.com/WinsperApp/winsper/actions/workflows/ci.yml/badge.svg" alt="CI status"></a>
</p>

Your keyboard can take a break. Hold a shortcut, speak, release—Winsper writes at your cursor. Dictate your words as they are, turn a rambling thought into an app-ready message, or select text and say what to change. Speech recognition and built-in AI Polish run on your PC.

## One voice, two ways to write

- **Dictate:** Say it once. Winsper transcribes locally and inserts text in the focused app.
- **Polish, nothing selected:** Talk through an unfinished thought. Winsper cleans fillers, grammar, and punctuation while keeping your meaning. The destination app helps shape the result: email, chat, notes, or a coding tool.
- **Polish, text selected:** Highlight text, then say what you want changed—“make this shorter” or “turn this into bullets.” Winsper uses your selection as context and replaces that selection.

No editor plugin required. Winsper works wherever Windows lets it capture a shortcut and insert text.

## Why Winsper

- **An email isn't a chat message.** App-aware Polish uses the focused app to guide tone and format—without sending screenshots to a model.
- **Runs locally by default.** Speech and built-in Polish stay on your PC. No account, subscription, or API key needed. Ollama and custom models remain optional choices.
- **No always-on speech capture.** Winsper briefly conditions the microphone at startup, then stops capture. It listens for speech when you use the shortcut, not while you work between requests.
- **Built with Qt, not Electron.** Winsper can preload your chosen speech model so the first Dictate shortcut need not wait for model loading. Dictation goes from local speech recognition straight to insertion, without a Polish model call.
- **Your words, remembered.** Add names, terms, and corrections; revisit past results in local History.
- **As visible as you want.** Pick a full HUD, compact wave, or sound-only feedback, with light and dark themes.

Full HUD and compact HUD, rendered from the app's own interface:

<p align="center">
  <img src=".github/assets/hud-listening-light.png" alt="Winsper full recording HUD with listening status" width="500">
  <img src=".github/assets/hud-compact-light.png" alt="Winsper compact recording HUD with listening wave" width="180">
</p>

## More than transcription

- **Speak the layout.** Say `new line` or `new paragraph` to format as you dictate. End with `press enter` to insert your words and send Enter; the phrase itself is not pasted. These voice triggers also work with Polish.
- **Skip the repeat typing.** Save `insert my signature` with your actual sign-off, then say the trigger to paste it. Date/time shortcuts come included; personal snippets are yours to add.
- **Choose your language and models.** The speech picker lists 100 languages, auto-detection, and mixed-language options such as Hinglish. Compatible models vary by language: Winsper offers Whisper and Parakeet for speech, and Qwen 2.5/3 models for local Polish. Fast, Balanced, and Best trade speed, memory, and output quality differently; optional Ollama supports your own models.

See the [guide](docs/USAGE.md) for trigger settings, language/model compatibility, and custom shortcuts.

## Get started

1. Download the [Windows installer](https://winsper.app/download/) for Windows 10/11 x64.
2. Run setup, choose your language, and download a speech model. Internet is needed for downloads, not everyday local dictation.
3. Click a text field. Hold **Ctrl+Space**, say something, then release to insert it.
4. Want a cleaner draft? Enable Polish and download its model. Hold **Ctrl+Alt+P** to speak a rough thought, or select existing text first and say what to change.

These are the default shortcuts. You can change them in Settings.

The current direct installer is **not code-signed**. Windows may show an *Unknown publisher* or SmartScreen warning. Verify the [published checksum](https://winsper.app/download/) and never disable antivirus protection to install Winsper. Bluetooth headphones can be used for playback, but Bluetooth hands-free microphone input is intentionally unsupported for safety.

Speech and default Polish processing stay on your PC. Model downloads, update checks, the website, and support may use the network. A remote model endpoint receives text only if you configure one. See [Privacy](https://winsper.app/privacy/) for details.

## Build from source

On Windows with Python 3.12 or 3.13 and PowerShell:

```powershell
.\scripts\setup.ps1
.\scripts\run.ps1
```

Run the deterministic tests with `.\scripts\test.ps1`. Hardware tests are separate and opt-in. See the [full guide](docs/USAGE.md) for shortcuts, model choices, configuration, troubleshooting, and the project layout.

## Project

Winsper is free forever. If it saves you time, you can [support Winsper on Buy Me a Coffee](https://www.buymeacoffee.com/winsper). Contributions are optional and never unlock features.

- [Contributing](CONTRIBUTING.md) · [Report a security issue](SECURITY.md)
- [MIT license](LICENSE) · [Third-party and model terms](THIRD_PARTY_NOTICES.md) · [Code signing policy](CODE_SIGNING.md)
- [Download and checksum](https://winsper.app/download/)
