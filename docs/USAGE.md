# Winsper user and developer guide

Winsper is a Windows-first, local push-to-talk dictation app.

Winsper source code is available under the [MIT License](../LICENSE). Model
weights and bundled third-party components have separate licenses; see
[third-party notices](../THIRD_PARTY_NOTICES.md).

Core capabilities:

- Hold a global hotkey to record speech.
- Transcribe locally with `faster-whisper`, with optional experimental Parakeet support.
- Paste the transcript into the currently focused app in Dictate mode.
- Replace selected text exactly by selecting text and using Dictate mode.
- Optionally polish dictated text with a local AI model before pasting.
- Select text and use Polish mode to speak a rewrite instruction and replace it immediately.
- Use voice edit commands such as `make it shorter`, `turn it into bullets`,
  `translate to Hindi`, `undo last paste`, and `open history`.
- Learn local correction rules such as `avery morgan` -> `Avery Morgan`.
- Quick-tap the dictate hotkey to toggle long dictation on and off.
- Paste saved snippets by speaking exact triggers such as `signature`.
- Save successful local insertions to History for copy, re-paste, and undo recovery.
- Show a compact wave-only HUD while listening, then hide it while processing and delivery finish.
- Play an optional readiness chime before capture, plus a non-blocking stop chime.
- Show a Windows tray icon with Quit and Copy Diagnostics actions.
- Guide first launch with a PySide6 setup wizard for hardware-aware speech recommendations, real-shortcut Dictation and Polish exercises, and app-aware rewrite examples.
- Edit config through a polished PySide6 settings window.
- Manage local speech models, install status, and benchmarks from Settings.
- Run Speed Lab to benchmark models and apply Instant/Balanced/Precise/GPU Boost intents.
- Use Privacy in Settings to inspect and clear local data files.
- Copy a local diagnostics report from Settings for troubleshooting.

## Quick Start

From this folder:

```powershell
.\scripts\setup.ps1
.\scripts\run.ps1
```

The first normal run opens the setup wizard. It starts with language and
transcription quality, shows a speech-model recommendation from the detected PC
capabilities, then lets the user configure and trigger the actual Dictate and
Polish shortcuts. Dictation uses the real HUD. Optional Polish demonstrates both
rough-speech cleanup across familiar app contexts and spoken instructions over
selected text. A final hands-on step uses the same Dictate path to recognize spoken
layout, Enter, and the built-in `today's date` shortcut before saving `config.yaml`.
Microphone selection remains available
in Settings if the Windows default is not suitable. Before enabling the Dictate
exercise, setup warms the selected production speech runtime and microphone. It
never substitutes a smaller setup-only model. The final step launches Winsper
directly. Winsper is free software under the MIT License. To test defaults
without the wizard:

```powershell
.\scripts\run.ps1 -SkipSetup
```

The first transcription run downloads the selected speech model into the
normal Hugging Face cache. The default stable path is `faster-whisper`. Optional
Parakeet models use `sherpa-onnx` and should be benchmarked before becoming a
default. Setup and Settings show download progress for explicit model installs,
including downloaded size and remaining size when Hugging Face reports totals.

Automatic microphone selection is recommended. Settings shows the microphone
Winsper is actually using and lists the currently available built-in, wired,
and USB inputs without connection-state noise. Bluetooth headphones remain
available for playback, but Winsper does not open their hands-free microphone
because that Windows route has reproduced kernel crashes on real hardware. A
legacy Bluetooth microphone preference is normalized to Automatic. If no usable
input exists, Settings shows `No microphone found` with a link-free instruction
to check Windows sound
settings. The native recorder follows Windows endpoint notifications while
idle and retains a bounded capture-start recovery path.
On recognized built-in codecs, it also keeps the matching internal audio graph
awake with WASAPI buffers flagged silent. This optional latency path never
selects the default output, Bluetooth, USB, HDMI, docks, monitors, or virtual
devices; it carries no authored PCM and fails open without blocking microphone
capture. Bluetooth microphone capture remains blocked independently at both the
Python and native boundaries.

To benchmark your real CPU speed:

```powershell
.\scripts\benchmark.ps1 -Model base.en -Seconds 5
.\scripts\benchmark.ps1 -Model small.en -Seconds 5
.\scripts\benchmark.ps1 -Model large-v3-turbo -Device cuda -ComputeType float16 -Seconds 5
```

The benchmark records once, prepares/downloads the selected model, then reports
transcription speed. Run it with each model you want to compare.

Results are saved to `speed_benchmarks.json` and shown in Settings > Advanced > Speed Lab.
If silence trimming is enabled, the captured speech duration can be shorter than
the requested recording duration.

Optional Parakeet support:

```powershell
uv pip install --python .\.venv\Scripts\python.exe -r requirements-parakeet.txt
.\.venv\Scripts\winsper.exe --config .\config.yaml --download-speech-model parakeet-tdt-0.6b-v2-int8
```

You can also open Settings > Advanced > Models and use the Parakeet card to
install support, download the model, and select it for Precise dictation.

To inspect installed speech models without opening Settings:

```powershell
.\.venv\Scripts\winsper.exe --config .\config.yaml --list-speech-models
```

To download a model explicitly:

```powershell
.\.venv\Scripts\winsper.exe --config .\config.yaml --download-speech-model small.en
```

To verify global hotkeys without recording audio or pasting text:

```powershell
.\.venv\Scripts\winsper.exe --config .\config.yaml --test-hotkeys
```

To open settings directly:

```powershell
.\.venv\Scripts\winsper.exe --config .\config.yaml --settings
```

To open local history:

```powershell
.\.venv\Scripts\winsper.exe --config .\config.yaml --history
```

To reopen first-run setup:

```powershell
.\.venv\Scripts\winsper.exe --config .\config.yaml --setup-wizard
```

To print the same diagnostics report available in Settings:

```powershell
.\.venv\Scripts\winsper.exe --config .\config.yaml --print-diagnostics
```

To ask the running app to reload settings, stop, or restart cleanly:

```powershell
.\.venv\Scripts\winsper.exe --config .\config.yaml --reload
.\.venv\Scripts\winsper.exe --config .\config.yaml --stop
.\.venv\Scripts\winsper.exe --config .\config.yaml --restart
```

The Interface section supports `system`, `dark`, and `light` themes. `system`
follows the Windows app theme and applies to both Settings and the HUD. The HUD
can use the full or compact style at bottom center, bottom left, bottom right, or
top center. It also has a Start with Windows toggle, which creates or removes a
local startup script in the current user's Windows Startup folder.

To check which app/profile Winsper currently detects:

```powershell
.\.venv\Scripts\winsper.exe --config .\config.yaml --print-app-context
```

For a friendlier app-awareness smoke test:

```powershell
.\scripts\run.cmd --test-app-awareness
```

After running it, switch to the browser tab or app you want to test during the
short countdown.

Winsper can also detect the active browser domain for common Windows
browsers when `pywinauto` is installed. It uses the configured
`browser_context.browser_processes` list, so niche browsers can be added by
their `.exe` name when they expose an address bar through Windows UI
Automation. Domains route sites like Gmail, Google Docs, ChatGPT, GitHub,
Slack, and Teams to better writing profiles. The HUD shows labels such as
Gmail, ChatGPT, or GitHub when detected. Polish also receives
site-specific guidance, so Claude/ChatGPT behaves like prompt writing, Gmail
behaves like email drafting, and GitHub/Jira/Linear preserve technical
identifiers. Full URLs are not stored in history.

Prompt Mode is strongest in AI tools such as ChatGPT, Claude, Gemini, and
Perplexity. In Polish mode, rough speech is rewritten into a direct prompt with
task, context, constraints, examples, and desired output preserved. Winsper
does not answer the prompt; it prepares it for the focused AI app.

To stop any stuck background process:

```powershell
.\scripts\stop.ps1
```

From Command Prompt:

```cmd
scripts\stop.cmd
```

## Languages and Speech Models

Dictation's Advanced model settings provide searchable coverage for Whisper's
100 languages plus auto-detection. Winsper recommends Parakeet v2 for English,
Parakeet v3 for its 25 supported European languages, and multilingual Whisper
for other languages. Changing language filters incompatible models; downloads
start only after explicit confirmation. Applying a model updates the speech
engine and every dictation-mode model together.

## Optional Local Polish

Polish mode supports a Winsper-managed embedded llama.cpp server and Ollama.
Embedded mode detects NVIDIA, AMD, Intel, CPU-only, and Windows ARM64 systems,
then prioritizes CUDA or Vulkan acceleration with a small CPU runtime included
as a reliable fallback. Optional acceleration downloads are resumable and
checked against pinned SHA-256 digests before installation. Low-memory
integrated GPUs use CPU by default because shared-memory Vulkan drivers can be
slower or unstable. Model selection remains separate from runtime installation.

Winsper's consumer Polish presets use exact pinned GGUF artifacts:

- Fast: Qwen 2.5 1.5B Q4_K_M for low-resource systems and lowest latency.
- Balanced (recommended): Qwen 3 4B Instruct 2507 Q4_K_M for everyday use.
- Best quality: Qwen 3 8B Q4_K_M as the largest local option; it is slower and
  is not uniformly more accurate than Balanced,
  with higher memory use and latency.

Ollama remains available for advanced setups. Winsper lists models already
installed in Ollama and shows the install URL or `ollama pull ...` command when
required.

```powershell
ollama pull qwen2.5:1.5b
```

If the selected local AI provider is unavailable, ordinary dictation still
works and Polish can fall back to the raw Dictate transcript when configured.

## Default Hotkeys

- Dictate: `ctrl+space`
- Polish: `ctrl+alt+p`
- Cancel current action: `ctrl+win+esc`

If `hotkeys.tap_to_toggle_dictation` is enabled, quickly tap the dictate
hotkey to lock recording on. Tap it again to stop and paste. Hold the same
hotkey normally for short push-to-talk dictation.

Dictate mode is the fastest path: speech to transcript to paste. If text is
selected, Dictate replaces that selection exactly and does not call an LLM. Polish mode
uses the same speech model first, then sends the transcript to the configured
local model for cleanup before pasting. Disable it from Settings if
you want dictation to stay entirely in the STT path.

While Winsper transcribes, the HUD shows a live transcript preview as local
speech segments arrive. Press the cancel hotkey to stop recording or prevent an
in-flight result from being inserted.

The HUD also shows model-loading and local-transcription status so first use and
cached-model warmup do not feel frozen.

Spoken Enter is enabled by default. Say `press enter` at the end of Dictate or
Polish speech to insert the text, remove that phrase, and then send Enter. With
no selection, Polish also recognizes local actions and exact Text Shortcuts
before calling the local model. The phrase can be changed in Settings > Dictation.

Speed profiles let each mode use a different speech model:

- Dictate model: fast daily dictation, usually `small.en` or `base.en`.
- Polish STT model: transcript before cleanup, usually `small.en`.
- Selection instruction model: short spoken instructions for selected-text Polish, usually `small.en`.

If `speech.preload_on_startup` is enabled, Winsper loads those mode models
in the background at startup. Polish mode falls back to the Dictate transcript
if the local rewrite model is unavailable.

The selected-text Polish flow is:

1. Select text in any app, hold Polish, speak an instruction.
2. Release the hotkey.
3. Winsper copies the selection, rewrites it, and replaces the selection.

If there is no selected text, Polish treats your speech as new dictation and cleans it before paste.
An optional preview can be enabled from Advanced Settings if you want to review selected-text rewrites before applying them.

Voice edit commands are recognized before the instruction is sent to local AI:

- `make it shorter`
- `turn it into bullets`
- `fix grammar`
- `make it professional`
- `make it casual`
- `format as email`
- `make it a Slack message`
- `translate to Hindi`
- `replace the last sentence with ...`

Local action commands do not call Ollama:

- `undo last paste`
- `copy last output`
- `open history`
- `open settings`

These commands use Polish on selected text and can be disabled from Advanced Settings.

## Text Shortcuts

Text Shortcuts are exact spoken triggers that paste saved text instead of the
raw transcript. Add them from Settings, or edit `config.yaml`:

```yaml
snippets:
  enabled: true
  items:
    - name: Signature
      trigger: signature
      text: |-
        Best,
        Avery
      aliases:
        - my signature
      profiles:
        - email
```

Shortcut text supports `{date}`, `{time}`, and `{datetime}` placeholders.

Fresh installs include three removable, global-safe shortcuts: `today's date`,
`current time`, and `date and time`. Personal content such as signatures, email
addresses, phone numbers, and postal addresses is never prefilled.

Text Shortcuts are for intentional voice macros: you speak a trigger such as
`signature` or `insert mail id here`, and Winsper inserts saved content.
Corrections are for automatic STT cleanup: Winsper silently changes recurring
mistakes such as `avery morgan` to `Avery Morgan` inside normal dictation.

## History

Winsper stores successful Dictate, Polish, selected-text Polish, and snippet insertions in
`history.jsonl` next to the active config file. History is local-only and can be
disabled from Settings.

The History window supports:

- Search previous insertions.
- Copy output.
- Re-paste an old output into the currently focused app.
- Send `Ctrl+Z` as an undo for the last paste.
- Learn a correction from the selected history item.
- Clear local history.

Winsper also keeps a local `usage.json` next to the config with words
dictated and estimated typing time saved. Settings > Home shows today's words
and estimated time saved as a simple value proof.

## Words & corrections

Personalize > Words & corrections combines custom vocabulary with local replacement rules.
Corrections are stored in `corrections.json` next to the active config file and
run after transcription and before Text Shortcuts or Polish.

Fresh installs include the term `Winsper` and the exact correction
`win spur` -> `Winsper`. Both are removable; no personal names or regional
vocabulary is prefilled.

Examples:

```text
avery morgan -> Avery Morgan
gen ai -> GenAI
cursor ai -> Cursor
config yammel -> config.yaml
```

Rules can be global or scoped to profiles such as `code`, `email`, or `chat`
when edited in advanced config. Manage everyday names, terms, and corrections
from Settings > Personalize > Words & corrections, or select text in History and choose Learn
Correction.

## Speed Lab

Speed Lab stores local benchmark results in `speed_benchmarks.json` next to the
active config file. It can benchmark the stable Whisper models and, when the
optional runtime is installed, Parakeet candidates from one recording. It then
applies:

- Instant: favors lowest latency.
- Balanced: prefers `small.en` when your machine handles it comfortably.
- Precise: uses higher-accuracy models, including Parakeet when available.
- GPU Boost: uses GPU-oriented models when CUDA is present.

Profile application updates Dictate, Polish, selection instruction models, compute
settings, and preload behavior. Save Settings to apply changes to the running
listener automatically.

## Privacy

Settings > Privacy explains the local-first data model and lets you turn local
History on or off and choose its retention period. Diagnostics can be copied
from Settings > About after review. Model downloads, updates, support, and the
website use network services; Dictation and the default Polish backend stay local.

## Safety Notes

- Clipboard contents are restored after paste/copy operations.
- Audio is held in memory and temporary WAV files are deleted after
  transcription.
- No cloud AI API is enabled by default. A deliberately configured remote model
  endpoint sends its inputs to that endpoint's operator.
- `pynput`, `pyautogui`, and global hotkeys may be blocked by some admin,
  remote desktop, or security-managed apps.
- The main listener is single-instance per config file. Settings and History can
  still open while the listener is running.

## Testing

Run deterministic lint, unit, and offscreen Qt tests:

```powershell
.\scripts\test.ps1
```

Run opt-in real Windows integration tests for the microphone, clipboard paste,
global hotkey hook, local STT, and browser UI Automation:

```powershell
.\scripts\test-hardware.ps1 -ExpectedBrowserDomain example.com
```

These tests record the configured microphone and generate keyboard input. Close
the running Winsper listener first. The browser test needs the matching tab to
be focused during its countdown.

## Project Layout

```text
voicepilot/
  __main__.py       CLI entrypoint
  app.py            thin application composition root
  app_lifecycle.py  listener, tray, recording, and shutdown lifecycle
  app_pipeline.py   transcription, command, rewrite, and insertion pipeline
  audio.py          push-to-talk audio capture
  config.py         YAML config loading
  hotkeys.py        global hold hotkey listener
  hud_core.py       shared HUD state and formatting
  hud_qt.py         PySide6 Winsper overlay
  history.py        local insertion history storage
  history_details.py  focused edit, correction, paste, and undo actions for Settings History
  corrections.py    local correction memory storage and matching
  speed_lab.py      benchmark result storage and profile recommendations
  models.py         local speech model catalog and cache detection
  onboarding_qt.py  first-run wizard shell
  onboarding_pages.py  onboarding page construction
  onboarding_shortcuts.py  real-shortcut Dictation and Polish exercises
  app_icons.py      shared verified app marks used by Settings and onboarding
  onboarding_tests.py  onboarding hardware/model checks
  diagnostics.py    local health report used by Settings and CLI
  settings_qt.py    settings window shell and shared controls
  settings_home.py  home, dictation, and hotkey settings
  settings_models.py  model and performance settings
  settings_pages.py  remaining focused settings pages
  settings_icons.py  theme-aware settings navigation icons
  settings_style.py  settings theme stylesheet
  settings_sync.py  synchronized settings bindings
  storage.py        atomic local persistence
  paste.py          clipboard-safe paste/copy helpers
  rewrite.py        provider-neutral local rewrite client
  ai_hardware.py    local AI hardware detection
  ai_catalog.py     pinned runtime and model metadata
  ai_runtime.py     verified runtime install and selection
  snippets.py       spoken snippet matching and placeholder expansion
  transcribe.py     faster-whisper transcription wrapper
```
