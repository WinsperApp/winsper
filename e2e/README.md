# Winsper E2E Laboratory

The lab deliberately separates model accuracy, Polish quality, deterministic
commands, Windows delivery, and real-app compatibility. Combining those layers
would produce statistics that cannot identify the failing subsystem.

## Fully unattended run

Run the real corpus, two labelled Windows TTS voices, all configured ASR
candidates, prompt contracts, repeated local-AI evaluation, and controlled
Windows integration checks:

```powershell
.\scripts\e2e-auto.ps1
```

The report clearly distinguishes real and synthetic audio. Logged-in third-party
apps remain unassessed unless dedicated test accounts are provided; local
fixtures are not reported as Gmail, Slack, or Teams certification.

The 134-case human manifest is the primary accuracy, accent, first-word, language,
and microphone check. Synthetic voices can add repeatable smoke coverage, but do
not count as proof of real-human recognition quality.

## Automated baseline

```powershell
.\scripts\e2e.ps1 -Suite deterministic
```

Artifacts are written under `artifacts/e2e/<run-id>/`:

- `manifest.json`: commit, OS, Python, and selected models
- `results.jsonl`: complete machine-readable results
- `results.csv`: spreadsheet-friendly case results
- `summary.json`: aggregate and safety-gate statistics
- `report.html`: local dashboard

## Speech corpus

Record the exact expected phrases declared in `cases.yaml` into `e2e/audio/`.
Use mono PCM WAV. Keep the same files for every model so model comparisons are
fair. Real human recordings are required for launch decisions; TTS is suitable
only for pipeline smoke testing.

The guided recorder shows every phrase and saves clips to the declared paths:

```powershell
.\scripts\e2e-record.ps1
```

For the current solo launch lane, record English, Hindi, and Hinglish across all
assignment buckets. Existing clips are skipped, so this command safely resumes:

```powershell
.\scripts\e2e-record.ps1 -SoloTester -Seconds 6
.\.venv\Scripts\python.exe -m devtools.corpus_audit --cases .\e2e\cases.yaml --solo-tester --require-audio
```

This produces meaningful single-tester functional evidence, not a broad
speaker/accent claim. When more fluent testers are available, record each
anonymous assignment separately and run the audit without `--solo-tester`.
`-Seconds` is the minimum recording window. Longer phrases automatically receive
more time based on their word count, so long cases are not cut off.

List missing/existing clips or record one case:

```powershell
.\scripts\e2e-record.ps1 -List
.\scripts\e2e-record.ps1 -Case asr-first-word
.\scripts\e2e-record.ps1 -SoloTester -Language hi -List
```

Safe controlled Windows integration checks can run independently:

```powershell
.\scripts\e2e.ps1 -Suite hardware
```

They briefly focus a Winsper-owned field and synthesize a harmless test hotkey.

The checked-in manifest enforces the recommended minimum corpus:

- 80 clean utterances across normal, technical, Indian English, names, places,
  self-corrections, and layout commands
- 20 fast-start utterances for first-word capture
- 20 noisy utterances
- 10 silence/noise-only clips for hallucination testing
- 20 Hindi and 20 mixed Hindi-English cases in the solo launch lane
- at least three consenting speakers only when claiming broad accent support

See `CERTIFICATION_RUNBOOK.md` for the frozen-build, competitor, real-app,
physical-device, accessibility, and evidence-retention procedure. Use
`manual-benchmark-template.csv` and `python -m devtools.manual_benchmark` for
blinded same-corpus competitor results.

Run all candidate models against the same corpus:

```powershell
.\scripts\e2e.ps1 -Suite asr -Models "parakeet-tdt-0.6b-v2-int8,parakeet-tdt-0.6b-v3-int8,small.en"
```

## Phase 4 speech-quality certification

The Phase 4 gate is deliberately stricter than a smoke test. It counts only
real human recordings; generated/TTS audio remains useful for regression tests
but cannot certify speech quality.

A passing run over the solo lane certifies the tested build, machine, microphone,
and tester for English/Hindi/Hinglish. It does not certify broad accents or
population-level recognition; keep that claim pending until multiple speakers run
the same corpus.

```powershell
python -m devtools.e2e_lab `
  --config config.yaml `
  --suite asr `
  --models "small.en,small,large-v3-turbo" `
  --certify-phase4
```

Certification requires the representative sample minimums encoded in
`devtools/phase4_release.py`:

- English WER at or below 7% (50+ clips)
- protected-name accuracy at or above 95% (20+ clips)
- zero fixed-language translation (20+ clips)
- mixed-script preservation at or above 90% (20+ clips)
- short Polish-instruction intent at or above 95% (50+ clips)
- first-word capture at or above 99% (50+ clips)

The report evaluates the CPU policy (`small.en` for English, `small` for other
languages) and NVIDIA policy (`large-v3-turbo`) independently. Optional speed
models such as Parakeet remain visible in the benchmark leaderboard but cannot
make the release gate pass or fail. An insufficient corpus or either unproven
hardware profile fails certification instead of silently passing.

## Polish constraints

Start Ollama and run:

```powershell
.\scripts\e2e.ps1 -Suite polish -PolishRuns 3
```

Polish cases use required, forbidden, and protected facts instead of exact
strings. Repeated runs expose inconsistent intent or fact preservation.

Run the Phase 5 release matrix through production prompts and validators:

```powershell
python -m devtools.e2e_lab `
  --config config.yaml `
  --suite phase5 `
  --certify-phase5 `
  --output artifacts\e2e-phase5
```

The matrix expands destination-neutral dictated/selected-text scenarios across
12 real destination classes: general text, email, chat, documents, Markdown,
prompt fields, Python/TypeScript editors, terminal, spreadsheet, presentation,
and browser forms. A scenario that declares its own destination remains bound
to that destination; for example, a terminal-command expectation is never
copied into Notepad or mail. The current catalog produces more than 500
distinct production-model executions without maintaining hundreds of copied
YAML entries. Scoring checks only objective invariants: required/protected
content, forbidden leakage, unchanged output when transformation is required,
requested list structure, length bounds, writing-system preservation, prompt
boundaries, and degenerate output.

Phase 5 passes only when all 500+ executions pass, both dictated and selected
branches are present and clean, exactly one model is represented, and measured
model-inference p95 meets the configured model-tier target. Runner startup,
report generation, and `nvidia-smi` diagnostics are excluded from inference
latency.

Run a repeatable embedded-GGUF matrix through the same production prompts:

```powershell
python -m devtools.model_matrix `
  --runtime artifacts\llama-runtime\llama-b9859-cuda-12.4\llama-server.exe `
  --device CUDA0 `
  --backend-label cuda `
  --runs 10
```

The runner discovers benchmark files under `models_test/`, reuses installed
Ollama model blobs as baselines, separates cold and warm latency, and records
llama-server RAM, VRAM, and decode throughput. `models_test/` is intentionally
Git-ignored.

To test whether Polish improves or damages real ASR output:

```powershell
python -m devtools.audio_polish_benchmark `
  --asr-results artifacts\e2e\<run-id>\results.jsonl `
  --runtime artifacts\llama-runtime\llama-b9859-cuda-12.4\llama-server.exe `
  --names llama3.2-3b,qwen3-8b
```

## Guided app certification

Close production conversations and use disposable drafts, documents, and test
channels. Then run:

```powershell
.\scripts\e2e.ps1 -Suite guided -Guided
```

Never test trailing Enter in a real conversation. A skipped safety gate remains
`UNASSESSED`; it is not silently counted as passing.

## Launch gates

Aggregate scores never override safety gates. Release requires zero observed:

- lost transcripts
- wrong-target insertions
- destructive accidental actions
- protected fact/name corruption in gated cases
- cancelled-thought leakage

Resource soak and multi-device coverage should be reported with sample count,
p50/p95/p99 latency, and memory growth rather than a subjective score.
