# Winsper human and competitor certification

This runbook is the release-evidence procedure. Automated, physical-device, and competitor evidence stay separate. A skipped or missing test is `UNASSESSED`, never a pass.

## 1. Freeze the candidate

Record the Git commit, installer hash, Winsper version, model IDs and hashes, Windows build, CPU, GPU, RAM, microphone, audio driver, display scale, and recording-room description. Do not change prompts, models, vocabulary, or quality settings inside one run.

Use two lanes:

1. `baseline`: default settings and no personal corrections.
2. `personalized`: the same cases after explicitly adding the tested names to Words & corrections.

## 2. Record the real-human corpus

The V1 solo lane contains at least 130 English, Hindi, Hinglish, silence, and noise cases. The `speaker-a`/`speaker-b`/`speaker-c` values are future assignment buckets; `--solo-tester` deliberately ignores them. This is valid functional evidence for the tested voice and environment, but it must not be described as broad speaker/accent certification. Do not commit WAV files containing identifiable voices.

From this checkout, using the existing project environment:

```powershell
$python = ".\.venv\Scripts\python.exe"
& $python -m devtools.corpus_audit --cases .\e2e\cases.yaml --solo-tester
& $python -m devtools.e2e_record --config .\config.yaml --cases .\e2e\cases.yaml --solo-tester --seconds 6
& $python -m devtools.corpus_audit --cases .\e2e\cases.yaml --solo-tester --require-audio
```

Read the displayed sentence exactly once at a natural pace. Start speaking promptly after `Recording...`; first-word cases deliberately test the opening boundary. Follow the stated environment: clean, noisy, silence, or noise-only.

The guided recorder saves native mono 48 kHz 16-bit PCM on current Windows audio devices; canonical mono 16 kHz files are also accepted. Both are decoded through Winsper's normal audio path. `--seconds` sets the minimum window; longer phrases receive additional time from a generic word-count estimate. Existing files are skipped unless `--overwrite` is explicitly supplied.

## 3. Winsper Phase 4

Run the same human WAVs through both release policies:

```powershell
$python = ".\.venv\Scripts\python.exe"
& $python -m devtools.e2e_lab --config .\config.yaml --suite asr --models "small.en,small,large-v3-turbo" --certify-phase4 --output .\artifacts\e2e-phase4
```

Required independently for CPU and NVIDIA policy: English WER `<=7%`, protected-term accuracy `>=95%`, fixed-language translation errors `0`, mixed-script preservation `>=90%`, short-instruction intent `>=95%`, and first-word capture `>=99%`.

For a solo corpus, label the verdict `single-tester English/Hindi/Hinglish functional certification`. Multi-speaker and broad-accent certification remains `UNASSESSED`.

## 4. Repeatable competitor lane

Use one fixed virtual microphone only after the user approves installing its driver. Replay the exact human WAV at a fixed level. Record product version, plan, mode, cloud/local status, network state, and audio route. Defaults are the primary comparison; tuned settings are a separate labelled run.

For each comparable Windows product and mode:

- 10 cold runs: fully quit, relaunch, then capture one case.
- 30 warm runs: product already loaded.
- Identical WAV, volume, input route, destination, and expected text.
- Measure shortcut-to-ready and release-to-result separately.
- Preserve raw output. Do not fix spelling before scoring.

Enter observations in `e2e/manual-benchmark-template.csv`, then aggregate:

```powershell
& $python -m devtools.manual_benchmark .\artifacts\manual-benchmark\results.csv
```

Different hardware invalidates direct latency ranking. Mac-only products can share the accuracy corpus, but their latency must be reported as a separate platform result.

## 5. Real-app lane

Use disposable drafts, documents, fields, and test channels:

```powershell
.\scripts\e2e.ps1 -Suite guided -Guided
```

Cover Dictate, no-selection Polish, selected-text Polish, layout actions, URLs, currencies, names, corrections, cancellation, silence, target switching, clipboard restoration, and rich text. Run high-risk destinations with Fast, Balanced, and Best; run the remaining destinations with the recommended default. Never execute trailing Enter in a real conversation or terminal.

## 6. Physical-device and lifecycle lane

Test built-in and wired/USB microphones; connect/disconnect; default-device changes; mute/unmute; sleep/resume; cold launch; 100 Dictations; 25 Polish actions; 10 cancellations; tray quit; relaunch; launch at login; update notification; uninstall; and reinstall. Separately verify Bluetooth headphones remain stable for playback while Winsper uses a supported non-Bluetooth microphone. Record p50/p95/p99 latency, failures, memory growth, and whether any unexpected output sound was heard. Do not merge this evidence with virtual-microphone results.

## 7. Release verdict

Release blockers are any lost transcript, wrong-target insertion, destructive accidental action, protected fact/name corruption in a gated case, cancelled-thought leakage, or silence hallucination. Aggregate scores cannot override these gates. Keep the raw CSV, Phase 4 output, app checklist, environment manifest, screenshots, and installer hash together under one revision-bound artifact directory.
