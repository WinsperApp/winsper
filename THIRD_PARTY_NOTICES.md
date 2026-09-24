# Winsper third-party notices

Winsper-owned source code is available under the MIT License in `LICENSE`. Winsper also includes or interoperates with open-source software and separately licensed model files. Their licenses remain separate; this notice is informational and does not replace upstream license terms.

Key runtime components include:

- PySide6 / Qt for Python — LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only: <https://doc.qt.io/qtforpython-6/licenses.html>
- faster-whisper and CTranslate2 — MIT: <https://github.com/SYSTRAN/faster-whisper>, <https://github.com/OpenNMT/CTranslate2>
- llama.cpp — MIT: <https://github.com/ggml-org/llama.cpp>
- sherpa-onnx — Apache-2.0: <https://github.com/k2-fsa/sherpa-onnx>
- Hugging Face Hub — Apache-2.0: <https://github.com/huggingface/huggingface_hub>
- pynput and pystray — LGPL-3.0: <https://github.com/moses-palmer/pynput>, <https://github.com/moses-palmer/pystray>
- sounddevice — MIT: <https://github.com/spatialaudio/python-sounddevice>
- Pillow — HPND: <https://python-pillow.github.io/license.html>

The Windows package includes the GNU GPL-3.0 and LGPL-3.0 license texts in `licenses/COPYING` and `licenses/COPYING.LGPL`, alongside this notice and `LGPL_SOURCE_OFFER.md`. That document explains how to obtain corresponding LGPL library source and replace or rebuild with modified libraries. An MIT license on Winsper does not waive those obligations.

Optional Polish models are downloaded separately. The catalog's Qwen 2.5 and Qwen 3 models derive from Apache-2.0 releases; the legacy Llama 3.2 option uses the separate Llama 3.2 Community License and is not MIT-licensed. The selected model's repository and upstream model card govern the model weights, not Winsper's MIT license.

Speech models are downloaded from the exact repository revision recorded in `voicepilot/speech_model_catalog.py`. The faster-whisper catalog includes MIT-licensed Whisper conversions, but verify each selected repository's model card. The optional Parakeet v2/v3 ONNX conversions derive from [NVIDIA Parakeet v2](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v2) and [v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3), whose model cards state CC-BY-4.0; attribution and any other applicable upstream terms remain in force. The conversion repositories do not clearly declare their own license in their model-card metadata, so do not treat them as MIT or Apache-2.0 by inference.

Each release includes `release-inventory.json`, which binds the source revision to SHA-256 hashes for packaged files and records the exact build-environment dependency versions and reported license metadata. Validate the version-specific source bundle and replacement instructions before public distribution.

Winsper also bundles unmodified Outlook, Slack, ChatGPT, Visual Studio Code, and Windows Terminal marks solely to identify example destinations in its app-awareness demonstration. Names and marks remain property of their respective owners; no affiliation or endorsement is implied. Upstream provenance is recorded in `voicepilot/assets/apps/SOURCES.md`, and applicable vendor trademark and asset-use terms must be reviewed before public distribution.
