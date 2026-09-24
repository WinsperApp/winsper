# Contributing to Winsper

Thanks for helping make Winsper more reliable. Bug reports, accessibility findings, documentation fixes, and focused pull requests are welcome.

Before changing behavior, open an issue describing the user-visible problem and expected result. For a fix, work from `main`, keep the patch narrow, and include a regression test when practical. Run `.\scripts\test.ps1` on Windows before submitting. If your change touches microphone capture, global hotkeys, model downloads, or text insertion, explain how you tested failure and recovery paths. Hardware-only results should be labeled as such; they do not replace deterministic tests.

Please do not include recordings, dictated text, personal paths, model weights, API tokens, or build outputs in issues or pull requests. Use the application's Copy Diagnostics action only after reviewing and redacting its contents. For vulnerabilities, use the private route in [SECURITY.md](SECURITY.md).

Winsper-owned source is MIT-licensed. Dependencies, separately downloaded models, and app marks have their own terms; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
