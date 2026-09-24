from __future__ import annotations

import traceback

from .audio import AudioClip
from .config import ProfileStyle, SpeechConfig
from .transcribe import FasterWhisperTranscriber


def _speech_worker_main(requests, responses, config: SpeechConfig, vocabulary: list[str]) -> None:
    transcriber = FasterWhisperTranscriber(config, vocabulary)
    while True:
        message = requests.get()
        if not isinstance(message, dict):
            continue
        if message.get("kind") == "stop":
            return
        request_id = str(message.get("id") or "")
        try:
            speech_config = message.get("config")
            if not isinstance(speech_config, SpeechConfig):
                raise RuntimeError("Invalid speech config sent to speech worker.")
            vocab = list(message.get("vocabulary") or [])
            transcriber.config = speech_config
            transcriber.vocabulary = vocab
            transcriber.on_device_fallback = lambda requested, fallback, rid=request_id: responses.put(
                {"kind": "fallback", "id": rid, "requested": requested, "fallback": fallback}
            )
            if message.get("kind") in {"load_model", "warm_up_model"}:
                operation = (
                    transcriber.warm_up
                    if message.get("kind") == "warm_up_model"
                    else transcriber.load_model
                )
                operation(
                    speech_config,
                    progress_callback=lambda progress, rid=request_id: responses.put(
                        {"kind": "progress", "id": rid, "progress": progress}
                    ),
                )
                responses.put({"kind": "result", "id": request_id, "text": ""})
                continue
            if message.get("kind") != "transcribe":
                raise RuntimeError(f"Unsupported speech worker command: {message.get('kind')}")
            clip = message.get("clip")
            if not isinstance(clip, AudioClip):
                raise RuntimeError("Invalid audio clip sent to speech worker.")
            profile = message.get("profile")
            if profile is not None and not isinstance(profile, ProfileStyle):
                profile = None
            text = transcriber.transcribe(
                clip,
                on_partial=lambda partial, rid=request_id: responses.put(
                    {"kind": "partial", "id": rid, "text": partial}
                ),
                profile=profile,
                config=speech_config,
                progress_callback=lambda progress, rid=request_id: responses.put(
                    {"kind": "progress", "id": rid, "progress": progress}
                ),
            )
            responses.put({"kind": "result", "id": request_id, "text": text})
        except BaseException as exc:
            responses.put(
                {
                    "kind": "error",
                    "id": request_id,
                    "error": f"{exc}\n{traceback.format_exc(limit=8)}",
                }
            )
