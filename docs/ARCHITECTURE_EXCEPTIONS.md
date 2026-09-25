# Phase 6 Architecture Exceptions

The normal production-module target is approximately 500 lines. A limit is a maintainability signal, not a reason to split cohesive safety code into artificial layers. `scripts/check_architecture.py` enforces the strict targets and caps these reviewed exceptions.

| Module | Why it remains cohesive | Split trigger |
| --- | --- | --- |
| `audio.py` | One stateful recorder owns stream selection, callback state, warm reuse, and recovery invariants. Splitting it now would distribute a safety-critical state machine with hardware-sensitive behavior. | A second recorder backend or independent device service is introduced. |
| `paste.py` | Clipboard snapshot, focus guard, paste, restore, and recovery form one transaction. | A non-Windows insertion backend is introduced. |
| `app_pipeline.py` | One orchestration surface connects typed dictation/polish outcomes; hardware, rendering, and support actions are already external. | Another action pipeline stops sharing the same transaction. |
| `app_context.py` | Foreground and browser context are one bounded detection service with a shared cache. | Browser detection becomes an independent process/service. |
| `config.py` | Mostly typed schema declarations plus built-in profile defaults; migration and storage are already separate. | Schema declarations exceed the current cap or profile defaults move to data assets. |

The gate also freezes the current size of the following cohesive legacy surfaces while they are split incrementally. They are exceptions to the 500-line target, not preferred module sizes:

- UI composition: `settings_style.py`, `settings_dictation_page.py`, `settings_speech_models_page.py`, `settings_rewrite_embedded.py`, and `settings_update_prompt.py`.
- Onboarding: `onboarding_qt.py`, `onboarding_pages.py`, `onboarding_shortcuts.py`, and the onboarding runtime mixin in `onboarding_tests.py`.
- Runtime boundaries: `transcribe.py`, `ai_runtime.py`, `llama_server.py`, `history.py`, `hotkeys.py`, `lifecycle_capture.py`, and `__main__.py`.
- Prompt safety: `polish_prompts.py` and `polish_validation.py`.

Each has an explicit ceiling in `scripts/check_architecture.py`; every other production module is checked against 500 lines automatically. Split when a new independent owner, backend, state machine, or reusable view can be extracted without weakening lifecycle invariants.

## Broad exception audit

Broad catches remain only where Python cannot enumerate failures from native Windows APIs, optional third-party libraries, callbacks, or best-effort shutdown/UI cleanup. Runtime-critical paths must log context or convert failure to a typed/domain error. Straightforward standard-library and known PortAudio/CUDA discovery catches were narrowed during Phase 6.

High broad-catch modules and their boundary:

- `audio.py`: native PortAudio callbacks, host API enumeration, and close/recovery cleanup.
- `app_context.py`: optional UI Automation, browser APIs, and Windows foreground probes.
- lifecycle modules: independent shutdown cleanup, timer callbacks, and user-facing domain conversion.
- Settings/onboarding modules: optional diagnostics and UI cleanup; failures are presented inline rather than crashing Settings.
- `branding.py` and `tray.py`: best-effort Windows shell integration.
- isolated speech/rewrite processes: process boundary conversion and forced-cleanup fallback.

New broad catches require a comment identifying one of: harmless best effort, logged fallback, domain conversion, or native/third-party boundary. The architecture gate and review should reject silent business-logic catches.
