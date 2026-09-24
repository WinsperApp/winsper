# Winsper security and privacy model

This document describes the release behavior of the native Windows app. It is
the engineering source of truth behind the in-app Privacy Report.

## Data flow

- Microphone audio exists in memory only for the active capture and local speech
  processing. Normal dictation does not create a temporary WAV file.
- Speech recognition and the default Polish backend run locally. Ollama is an
  optional local backend chosen by the user.
- Selected text and inserted text pass through the Windows clipboard briefly.
  Winsper snapshots and restores the previous clipboard when that option is
  enabled and restoration is safe.
- History, correction memory, usage statistics, configuration, and diagnostics
  are local files under the user's Winsper data directory. History can be
  disabled or cleared.
- Winsper does not upload diagnostics or crash reports automatically.

## Expected network activity

- Speech models are downloaded over HTTPS from exact repository revisions pinned
  in the release. Optional Polish models and runtimes additionally require the
  release-owned size and SHA-256 values.
- Update metadata and installers use HTTPS. Installers must match the manifest
  SHA-256 and have a trusted Authenticode signature from the configured Winsper
  publisher before launch.
- The website, support contact, model downloads, and software updates use
  network services independently of the local speech and writing paths.

## Trust boundaries and mitigations

| Boundary | Primary risk | Mitigation |
| --- | --- | --- |
| Hotkey/audio input | Stale or untrusted device state | Explicit action state machine, bounded retries, local capture only |
| Selected text/clipboard | Data loss or wrong-target insertion | Clipboard snapshot/restore, target re-checks, typed outcomes, safe fallback |
| Speech/model downloads | Tampered files or archive traversal | HTTPS, exact speech revisions, pinned Polish SHA-256, safe ZIP extraction, atomic installation |
| Embedded Polish server | Local-network exposure or unauthorised calls | Random per-process API key and `127.0.0.1` binding only |
| Polish prompt boundary | Selected text acting as instructions | Selected text is delimited as untrusted context; output validation blocks unsafe/no-op replacement |
| License service | Stolen key or local-state tampering | HTTPS provider API, DPAPI state, product policy compiled into the app |
| Updates | Malicious installer | HTTPS feed, strict manifest, SHA-256, pinned trusted publisher signature |
| Diagnostics | Secrets or dictated text in support logs | No transcript logging by default, credential redaction, user-initiated sharing only |
| Config/history writes | Partial or corrupt files | Atomic replace writes and bounded local stores |

## Accessibility security

Accessibility preferences are not telemetry. Winsper reads the Windows reduced
motion and High Contrast settings locally. High Contrast keeps system-owned
window-frame colors and switches the application surfaces to a measured,
high-contrast palette. Core status messages always include text or an icon, not
color alone.

## Release verification

Automated tests cover integrity checks, safe extraction, atomic writes, local
server binding/authentication, log redaction, reduced motion, High Contrast
palette selection, and privacy-report claims. NVDA announcements, Windows High
Contrast rendering, keyboard-only navigation, 200% display scaling, Hindi/RTL
rendering, and timeout-sensitive HUD behavior also require the release-candidate
hardware/UI certification pass because unit tests cannot prove screen-reader or
real display behavior.
