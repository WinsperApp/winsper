from __future__ import annotations

import logging
import os
import re
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import replace
from difflib import SequenceMatcher
from functools import lru_cache
from threading import Lock
from time import monotonic

from .audio import AudioClip
from .config import ProfileStyle, SpeechConfig
from .models import (
    DownloadProgress,
    DownloadProgressCallback,
    engine_for_model,
    find_speech_model,
    model_supports_language,
    resolve_model_path,
)
from .speech_languages import (
    SPEECH_LANGUAGE_NAMES,
    mixed_language_mode,
    mixed_transcribe_prompt,
    model_language_code,
)
from .voice_commands import edit_command_hotwords

logger = logging.getLogger(__name__)

ModelRuntimeKey = tuple[str, str, str, str]
ModelRequestKey = tuple[str, str, str, str, str, int]
PARTIAL_UPDATE_MIN_INTERVAL_SECONDS = 0.08
PARTIAL_UPDATE_MIN_GROWTH_CHARS = 160
SPEECH_ACTIVITY_SAMPLE_RATE = 16_000
SPEECH_ACTIVITY_MIN_DURATION_MS = 96
SPEECH_BOUNDARY_PADDING_SECONDS = 0.24
SPEECH_WARM_UP_SECONDS = 1.0
SPEECH_WARM_UP_SOURCE_RATE = 48_000

NON_ENGLISH_TRANSCRIBE_PROMPTS = {
    "hi": "यह हिंदी भाषण का लिप्यंतरण है। हिंदी में लिखें। अंग्रेज़ी में अनुवाद न करें।",
}


class FasterWhisperTranscriber:
    def __init__(
        self,
        config: SpeechConfig,
        vocabulary: list[str],
        on_device_fallback: Callable[[SpeechConfig, SpeechConfig], None] | None = None,
    ) -> None:
        self.config = config
        self.vocabulary = vocabulary
        self.on_device_fallback = on_device_fallback
        self._models: OrderedDict[ModelRuntimeKey, object] = OrderedDict()
        self._device_fallbacks: dict[ModelRequestKey, SpeechConfig] = {}
        self._model_lock = Lock()

    def transcribe(
        self,
        clip: AudioClip,
        on_partial: Callable[[str], None] | None = None,
        profile: ProfileStyle | None = None,
        config: SpeechConfig | None = None,
        progress_callback: DownloadProgressCallback | None = None,
    ) -> str:
        speech_config = config or self.config
        speech_config = self._device_fallbacks.get(model_key(speech_config), speech_config)
        # faster-whisper already applies Silero VAD inside transcribe().
        # Sherpa/Parakeet does not, so guard it with the same local detector.
        # Also keep silence rejection when advanced users disable Whisper VAD.
        needs_activity_gate = speech_config.engine == "sherpa_onnx" or not speech_config.vad_filter
        if needs_activity_gate and not clip_has_speech_activity(clip):
            return ""
        if speech_config.engine == "faster_whisper":
            return self._transcribe_faster_whisper(clip, on_partial, profile, speech_config, progress_callback)
        if speech_config.engine == "sherpa_onnx":
            return self._transcribe_sherpa_onnx(clip, on_partial, profile, speech_config, progress_callback)
        raise RuntimeError(f"Unsupported speech engine: {speech_config.engine}")

    def warm_up(
        self,
        config: SpeechConfig | None = None,
        progress_callback: DownloadProgressCallback | None = None,
    ) -> bool:
        """Load the selected runtime and execute one private, discarded inference."""
        import numpy as np

        speech_config = config or self.config
        source_clip = AudioClip(
            samples=np.zeros(
                int(SPEECH_WARM_UP_SOURCE_RATE * SPEECH_WARM_UP_SECONDS),
                dtype="float32",
            ),
            sample_rate=SPEECH_WARM_UP_SOURCE_RATE,
            duration_seconds=SPEECH_WARM_UP_SECONDS,
        )
        if speech_config.engine == "faster_whisper":
            # Exercise resampling, VAD initialization, prompt prefill, and one
            # timestamp-aware decode. Any synthetic result is discarded.
            samples = _resample(
                source_clip.samples,
                source_clip.sample_rate,
                SPEECH_ACTIVITY_SAMPLE_RATE,
            )
            clip = AudioClip(samples, SPEECH_ACTIVITY_SAMPLE_RATE, SPEECH_WARM_UP_SECONDS)
            return self._warm_up_faster_whisper(clip, speech_config, progress_callback)
        if speech_config.engine == "sherpa_onnx":
            clip = AudioClip(
                np.zeros(
                    int(SPEECH_ACTIVITY_SAMPLE_RATE * SPEECH_WARM_UP_SECONDS),
                    dtype="float32",
                ),
                SPEECH_ACTIVITY_SAMPLE_RATE,
                SPEECH_WARM_UP_SECONDS,
            )
            self._transcribe_sherpa_onnx(
                clip,
                None,
                None,
                speech_config,
                progress_callback,
            )
            return True
        raise RuntimeError(f"Unsupported speech engine: {speech_config.engine}")

    def _warm_up_faster_whisper(
        self,
        clip: AudioClip,
        speech_config: SpeechConfig,
        progress_callback: DownloadProgressCallback | None,
    ) -> bool:
        model = self.load_model(speech_config, progress_callback=progress_callback)
        _emit_speech_progress(progress_callback, speech_config.model, "Preparing local transcription")
        configured_language = speech_config.language or ""
        initial_prompt = self._initial_prompt_for_language(configured_language, None)
        hotword_terms = self._hotwords(None, instruction=False)
        hotwords = ", ".join(hotword_terms) if hotword_terms else None
        vad_params = _vad_parameters(instruction=False)
        common_options = {
            "language": model_language_code(configured_language),
            "task": "transcribe",
            "beam_size": speech_config.beam_size,
            "condition_on_previous_text": False,
            "initial_prompt": initial_prompt,
            "hotwords": hotwords,
            "no_speech_threshold": 0.4,
            "compression_ratio_threshold": 2.4,
            "log_prob_threshold": -1.0,
            "max_new_tokens": 1,
        }
        try:
            # Silence lets Silero initialize without generating model text.
            vad_segments, _info = model.transcribe(
                clip.samples,
                vad_filter=True,
                vad_parameters=vad_params,
                **common_options,
            )
            for _segment in vad_segments:
                pass
            # Bypass only VAD for a bounded decoder pass. This primes the same
            # prompt/hotword/timestamp path used by real Dictation.
            decode_segments, _info = model.transcribe(
                clip.samples,
                vad_filter=False,
                vad_parameters=None,
                **common_options,
            )
            for _segment in decode_segments:
                pass
        except RuntimeError as exc:
            if self._should_retry_on_cpu(exc, speech_config):
                return self._warm_up_faster_whisper(
                    clip,
                    replace(speech_config, device="cpu", compute_type="int8"),
                    progress_callback,
                )
            raise
        return True

    def _transcribe_faster_whisper(
        self,
        clip: AudioClip,
        on_partial: Callable[[str], None] | None,
        profile: ProfileStyle | None,
        speech_config: SpeechConfig,
        progress_callback: DownloadProgressCallback | None,
    ) -> str:
        model = self.load_model(speech_config, progress_callback=progress_callback)
        _emit_speech_progress(progress_callback, speech_config.model, "Running local transcription")

        audio = clip.samples
        if clip.sample_rate != 16000:
            audio = _resample(audio, clip.sample_rate, 16000)
        audio = _pad_audio_boundaries(audio, 16000)

        instruction = speech_config.purpose == "polish_instruction"
        vad_params = _vad_parameters(instruction) if speech_config.vad_filter else {}

        configured_language = speech_config.language or ""
        lang = model_language_code(configured_language)
        initial_prompt = self._initial_prompt_for_language(configured_language, profile)
        hotword_terms = self._hotwords(profile, instruction=instruction)
        hotwords = ", ".join(hotword_terms) if hotword_terms else None
        beam_size = (
            max(3, speech_config.beam_size)
            if instruction or mixed_language_mode(configured_language) is not None
            else speech_config.beam_size
        )
        parts: list[str] = []
        partial_length = 0
        last_partial_length = 0
        last_partial_at = 0.0
        last_partial = ""
        try:
            segments, _info = model.transcribe(
                audio,
                language=lang,
                task="transcribe",  # Explicit: never default to the translate task.
                beam_size=beam_size,
                vad_filter=speech_config.vad_filter,
                vad_parameters=vad_params if speech_config.vad_filter else None,
                condition_on_previous_text=False,
                initial_prompt=initial_prompt,
                hotwords=hotwords,
                no_speech_threshold=0.35 if instruction else 0.4,
                compression_ratio_threshold=2.2 if instruction else 2.4,
                log_prob_threshold=-0.8 if instruction else -1.0,
            )
            for segment in segments:
                segment_text = segment.text.strip()
                if not segment_text:
                    continue
                if parts:
                    partial_length += 1
                parts.append(segment_text)
                partial_length += len(segment_text)
                if on_partial is not None:
                    now = monotonic()
                    if (
                        not last_partial
                        or now - last_partial_at >= PARTIAL_UPDATE_MIN_INTERVAL_SECONDS
                        or partial_length - last_partial_length >= PARTIAL_UPDATE_MIN_GROWTH_CHARS
                    ):
                        partial = normalize_transcript(" ".join(parts), self._vocabulary(profile))
                        on_partial(partial)
                        last_partial = partial
                        last_partial_length = partial_length
                        last_partial_at = now
        except RuntimeError as exc:
            if self._should_retry_on_cpu(exc, speech_config):
                cpu_config = replace(speech_config, device="cpu", compute_type="int8")
                return self._transcribe_faster_whisper(clip, on_partial, profile, cpu_config, progress_callback)
            raise
        text = normalize_transcript(" ".join(parts).strip(), self._vocabulary(profile))
        if on_partial is not None and text and text != last_partial:
            on_partial(text)
        return text

    def _should_retry_on_cpu(self, exc: RuntimeError, speech_config: SpeechConfig) -> bool:
        err = str(exc).lower()
        if not any(s in err for s in ("cublas", "cuda", "cudnn", "cufft", "curand", "dll")):
            return False
        requested_key = model_key(speech_config)
        with self._model_lock:
            self._models.pop(model_runtime_key(speech_config), None)
        if speech_config.device == "cpu":
            return False
        logger.warning("CUDA inference failed (%s); retrying on CPU/int8.", exc)
        cpu_config = replace(speech_config, device="cpu", compute_type="int8")
        self._device_fallbacks[requested_key] = cpu_config
        if self.on_device_fallback is not None:
            try:
                self.on_device_fallback(speech_config, cpu_config)
            except Exception:
                pass
        return True


    def _transcribe_sherpa_onnx(
        self,
        clip: AudioClip,
        on_partial: Callable[[str], None] | None,
        profile: ProfileStyle | None,
        speech_config: SpeechConfig,
        progress_callback: DownloadProgressCallback | None,
    ) -> str:
        _emit_speech_progress(progress_callback, speech_config.model, "Loading local transcription model")
        recognizer = self.load_model(speech_config, progress_callback=progress_callback)
        _emit_speech_progress(progress_callback, speech_config.model, "Running local transcription")
        # Parakeet packages expose BPE tokens but not the BPE vocabulary file
        # sherpa-onnx requires for safe runtime hotword encoding. Passing plain
        # words is rejected by the native runtime, so use deterministic
        # dictionary normalization after decoding instead.
        stream = recognizer.create_stream()
        stream.accept_waveform(
            clip.sample_rate,
            _pad_audio_boundaries(clip.samples, clip.sample_rate),
        )
        recognizer.decode_stream(stream)
        text = normalize_transcript(stream.result.text.strip(), self._vocabulary(profile))
        if on_partial is not None and text:
            on_partial(text)
        return text

    @property
    def model(self):
        return self.load_model(self.config)

    def mode_config(self, model: str | None) -> SpeechConfig:
        selected = (model or "").strip()
        if not selected:
            selected = self.config.model
        language = (self.config.language or "").strip().casefold()
        preset = find_speech_model(selected)
        if preset is not None and not model_supports_language(preset, language):
            configured = find_speech_model(self.config.model)
            preset = (
                configured
                if configured is not None and model_supports_language(configured, language)
                else find_speech_model("small.en" if language == "en" else "small")
            )
            if preset is not None:
                selected = preset.model
        return replace(self.config, model=selected, engine=engine_for_model(selected, self.config.engine))

    def load_model(self, config: SpeechConfig | None = None, progress_callback: DownloadProgressCallback | None = None):
        speech_config = config or self.config
        request_key = model_key(speech_config)
        fallback = self._device_fallbacks.get(request_key)
        if fallback is not None:
            return self.load_model(fallback, progress_callback)
        runtime_key = model_runtime_key(speech_config)
        with self._model_lock:
            if runtime_key in self._models:
                self._models.move_to_end(runtime_key)
                return self._models[runtime_key]
            if speech_config.engine == "sherpa_onnx":
                model = self._load_sherpa_onnx_model(speech_config, progress_callback)
                return self._cache_model_locked(runtime_key, model)

            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            if speech_config.device == "cuda":
                # Worker processes are spawned fresh on Windows. Make a
                # previously verified, app-managed runtime visible inside this
                # process before CTranslate2 attempts to load CUDA DLLs.
                from .speech_runtime import activate_managed_runtime

                activate_managed_runtime()
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError("Install faster-whisper from requirements.txt.") from exc

            model_ref = speech_config.model
            preset = find_speech_model(speech_config.model)
            if preset is not None and preset.engine == "faster_whisper":
                model_ref = str(resolve_model_path(preset))
            _emit_speech_progress(progress_callback, speech_config.model, "Loading model into memory")
            try:
                model = WhisperModel(
                    model_ref,
                    device=speech_config.device,
                    compute_type=speech_config.compute_type,
                )
            except Exception as exc:
                if speech_config.device == "cuda":
                    fallback = replace(speech_config, device="cpu", compute_type="int8")
                    fallback_key = model_runtime_key(fallback)
                    try:
                        if fallback_key in self._models:
                            self._models.move_to_end(fallback_key)
                            model = self._models[fallback_key]
                        else:
                            model = WhisperModel(
                                model_ref,
                                device=fallback.device,
                                compute_type=fallback.compute_type,
                            )
                            self._cache_model_locked(fallback_key, model)
                        self._device_fallbacks[request_key] = fallback
                        if self.on_device_fallback is not None:
                            try:
                                self.on_device_fallback(speech_config, fallback)
                            except Exception:
                                pass
                    except Exception as fallback_exc:
                        raise RuntimeError(
                            "Could not load the speech model on CUDA, and CPU fallback also failed. "
                            "Use cpu/int8 in Settings, or install the NVIDIA CUDA/cuDNN runtime required by faster-whisper."
                        ) from fallback_exc
                    return model
                raise RuntimeError(
                    f"Could not load speech model {speech_config.model} on "
                    f"{speech_config.device}/{speech_config.compute_type}: {exc}"
                ) from exc
            return self._cache_model_locked(runtime_key, model)

    def _cache_model_locked(self, key: ModelRuntimeKey, model: object):
        self._models[key] = model
        self._models.move_to_end(key)
        evicted = False
        limit = max(1, min(3, int(self.config.max_cached_models)))
        while len(self._models) > limit:
            _old_key, old_model = self._models.popitem(last=False)
            if old_model is not model:
                del old_model
            evicted = True
        if evicted:
            import gc

            gc.collect()
        return model

    def _load_sherpa_onnx_model(self, speech_config: SpeechConfig, progress_callback: DownloadProgressCallback | None = None):
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise RuntimeError(
                "Parakeet needs the optional sherpa-onnx runtime. Install it with: "
                "uv pip install --python .\\.venv\\Scripts\\python.exe -r requirements-parakeet.txt"
            ) from exc

        preset = find_speech_model(speech_config.model)
        if preset is None or preset.engine != "sherpa_onnx":
            raise RuntimeError(f"{speech_config.model} is not a sherpa-onnx speech model.")
        model_dir = resolve_model_path(preset)
        encoder = model_dir / "encoder.int8.onnx"
        decoder = model_dir / "decoder.int8.onnx"
        joiner = model_dir / "joiner.int8.onnx"
        tokens = model_dir / "tokens.txt"
        missing = [path.name for path in (encoder, decoder, joiner, tokens) if not path.exists()]
        if missing:
            raise RuntimeError(f"Parakeet model files are incomplete: {', '.join(missing)}")

        provider = "cuda" if speech_config.device == "cuda" else "cpu"
        try:
            return sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=str(encoder),
                decoder=str(decoder),
                joiner=str(joiner),
                tokens=str(tokens),
                num_threads=min(4, max(1, os.cpu_count() or 1)),
                sample_rate=16000,
                feature_dim=80,
                decoding_method="greedy_search",
                provider=provider,
                model_type="nemo_transducer",
            )
        except Exception as exc:
            raise RuntimeError(f"Could not load Parakeet with sherpa-onnx on {provider}: {exc}") from exc

    def _initial_prompt(self, profile: ProfileStyle | None) -> str | None:
        vocabulary = self._vocabulary(profile)
        return "Vocabulary: " + ", ".join(vocabulary) if vocabulary else None

    def _initial_prompt_for_language(self, language: str | None, profile: ProfileStyle | None) -> str | None:
        if not language:
            prompt = (
                "Transcribe exactly as spoken. Preserve every detected language and each language's normal "
                "writing system. Preserve language switches. Do not translate or paraphrase."
            )
            vocabulary = self._vocabulary(profile)
            return f"{prompt}\nProper nouns: {', '.join(vocabulary)}" if vocabulary else prompt
        code = language.strip().casefold()
        mixed_prompt = mixed_transcribe_prompt(code)
        if mixed_prompt:
            vocabulary = self._vocabulary(profile)
            return f"{mixed_prompt}\nProper nouns: {', '.join(vocabulary)}" if vocabulary else mixed_prompt
        if code == "en":
            return self._initial_prompt(profile)
        label = SPEECH_LANGUAGE_NAMES.get(code, code)
        prompt = NON_ENGLISH_TRANSCRIBE_PROMPTS.get(
            code,
            f"Transcribe in {label}. Keep the spoken language and writing system. Do not translate to English.",
        )
        vocabulary = self._vocabulary(profile)
        return f"{prompt}\nProper nouns: {', '.join(vocabulary)}" if vocabulary else prompt

    def _hotwords(self, profile: ProfileStyle | None, *, instruction: bool) -> list[str]:
        del profile
        terms = list(edit_command_hotwords()) if instruction else []
        return dedupe_terms([" ".join(term.split()) for term in terms if term.strip()])

    def _vocabulary(self, profile: ProfileStyle | None) -> list[str]:
        terms = list(self.vocabulary)
        if profile is not None:
            terms.extend(profile.vocabulary)
        return dedupe_terms(terms)


def normalize_transcript(text: str, vocabulary: list[str]) -> str:
    normalized = " ".join(text.split())
    terms = dedupe_terms(vocabulary)
    for term in terms:
        if not term:
            continue
        normalized = replace_case_insensitive(normalized, term)
    return _normalize_likely_dictionary_variants(normalized, terms)


def _normalize_likely_dictionary_variants(text: str, vocabulary: list[str]) -> str:
    """Repair conservative single-token name/term variants from closed-vocabulary ASR."""
    canonical_keys = {term.casefold() for term in vocabulary}
    candidates = [
        term
        for term in vocabulary
        if " " not in term and len(term) >= 5 and not term.isupper() and any(char.isupper() for char in term)
    ]
    text = _normalize_split_dictionary_variants(text, candidates)
    replacements: list[tuple[int, int, str]] = []
    for match in re.finditer(r"(?<!\w)[\w'-]+(?!\w)", text, re.UNICODE):
        heard = match.group(0)
        if heard.casefold() in canonical_keys or not heard[:1].isupper():
            continue
        ranked: list[tuple[float, str]] = []
        for canonical in candidates:
            if heard.casefold()[:1] != canonical.casefold()[:1]:
                continue
            length_limit = 3 if len(canonical) >= 8 else 2
            if abs(len(heard) - len(canonical)) > length_limit:
                continue
            score = SequenceMatcher(None, heard.casefold(), canonical.casefold()).ratio()
            if len(canonical) < 8:
                if _phonetic_skeleton(heard) != _phonetic_skeleton(canonical) or score < 0.65:
                    continue
            elif score < 0.72:
                continue
            ranked.append((score, canonical))
        ranked.sort(reverse=True)
        if ranked and (len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= 0.08):
            replacements.append((match.start(), match.end(), ranked[0][1]))
    for start, end, canonical in reversed(replacements):
        text = text[:start] + canonical + text[end:]
    return text


def _normalize_split_dictionary_variants(text: str, vocabulary: list[str]) -> str:
    words = list(re.finditer(r"(?<!\w)[\w'-]+(?!\w)", text, re.UNICODE))
    ranked: list[tuple[float, int, int, str]] = []
    for index in range(len(words) - 1):
        for width in (2, 3):
            group = words[index : index + width]
            if len(group) != width:
                continue
            gaps = [text[left.end() : right.start()] for left, right in zip(group, group[1:])]
            if not all(gap.isspace() for gap in gaps):
                continue
            heard = "".join(match.group(0) for match in group)
            if not heard[:1].isupper():
                continue
            for canonical in vocabulary:
                if heard.casefold()[:1] != canonical.casefold()[:1] or abs(len(heard) - len(canonical)) > 3:
                    continue
                score = SequenceMatcher(None, heard.casefold(), canonical.casefold()).ratio()
                threshold = 0.72 if len(canonical) >= 8 else 0.90
                if score >= threshold:
                    ranked.append((score, group[0].start(), group[-1].end(), canonical))
    chosen: list[tuple[int, int, str]] = []
    for _score, start, end, canonical in sorted(ranked, reverse=True):
        if any(start < chosen_end and end > chosen_start for chosen_start, chosen_end, _ in chosen):
            continue
        chosen.append((start, end, canonical))
    for start, end, canonical in sorted(chosen, reverse=True):
        text = text[:start] + canonical + text[end:]
    return text


def _phonetic_skeleton(value: str) -> str:
    consonants = (character for character in value.casefold() if character.isalpha() and character not in "aeiouywh")
    output = ""
    for character in consonants:
        mapped = "k" if character in "cq" else ("s" if character == "z" else character)
        if not output or output[-1] != mapped:
            output += mapped
    return output


def clip_has_speech_activity(clip: AudioClip) -> bool:
    """Reject acoustic silence without classifying transcript words as filler."""
    try:
        import numpy as np

        audio = np.asarray(clip.samples, dtype="float32").reshape(-1)
    except (TypeError, ValueError):
        return True
    if audio.size == 0:
        return False
    if float(np.max(np.abs(audio))) < 0.0005:
        return False
    if clip.sample_rate != SPEECH_ACTIVITY_SAMPLE_RATE:
        audio = _resample(audio, clip.sample_rate, SPEECH_ACTIVITY_SAMPLE_RATE)
    audio = np.ascontiguousarray(audio, dtype="float32")
    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps

        timestamps = get_speech_timestamps(
            audio,
            VadOptions(
                threshold=0.5,
                min_speech_duration_ms=SPEECH_ACTIVITY_MIN_DURATION_MS,
                min_silence_duration_ms=160,
                speech_pad_ms=0,
            ),
            sampling_rate=SPEECH_ACTIVITY_SAMPLE_RATE,
        )
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        # Third-party VAD failure must not discard genuine user speech.
        logger.warning("Speech activity check unavailable; preserving capture: %s", exc)
        return True
    return bool(timestamps)


def replace_case_insensitive(text: str, canonical: str) -> str:
    return _vocabulary_pattern(canonical).sub(canonical, text)


@lru_cache(maxsize=1024)
def _vocabulary_pattern(canonical: str):
    return re.compile(rf"\b{re.escape(canonical)}\b", re.IGNORECASE)



def dedupe_terms(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for term in terms:
        key = term.lower().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(term)
    return output


def _emit_speech_progress(callback: DownloadProgressCallback | None, model: str, status: str) -> None:
    if callback is None:
        return
    try:
        callback(DownloadProgress(model=model, repo_id="", status=status))
    except Exception:
        pass


def model_key(config: SpeechConfig) -> tuple[str, str, str, str, str, int]:
    return (
        config.engine,
        config.model,
        config.device,
        config.compute_type,
        config.language,
        config.beam_size,
    )


def model_runtime_key(config: SpeechConfig) -> ModelRuntimeKey:
    """Return only fields that change the loaded model runtime."""
    return (
        config.engine,
        config.model,
        config.device,
        config.compute_type,
    )


def _vad_parameters(instruction: bool) -> dict[str, float | int]:
    return {
        "min_speech_duration_ms": SPEECH_ACTIVITY_MIN_DURATION_MS,
        "min_silence_duration_ms": 320 if instruction else 800,
        "speech_pad_ms": 160 if instruction else 200,
        "threshold": 0.35 if instruction else 0.5,
    }


def _pad_audio_boundaries(samples: object, sample_rate: int) -> object:
    """Give VAD/ASR context around speech recorded at exact hotkey boundaries."""
    import numpy as np

    audio = np.asarray(samples, dtype="float32").reshape(-1)
    padding_size = max(0, int(sample_rate * SPEECH_BOUNDARY_PADDING_SECONDS))
    if not audio.size or not padding_size:
        return audio
    padding = np.zeros(padding_size, dtype="float32")
    return np.concatenate((padding, audio, padding))


def _resample(samples: object, from_rate: int, to_rate: int) -> object:
    """Antialiased mono resampling through FFmpeg's bundled audio resampler."""
    import av
    import numpy as np

    if from_rate == to_rate:
        return samples
    audio = np.asarray(samples, dtype="float32").reshape(-1)
    if not audio.size:
        return audio
    frame = av.AudioFrame.from_ndarray(audio.reshape(1, -1), format="fltp", layout="mono")
    frame.sample_rate = from_rate
    resampler = av.AudioResampler(format="fltp", layout="mono", rate=to_rate)
    frames = [*resampler.resample(frame), *resampler.resample(None)]
    if not frames:
        return np.empty(0, dtype="float32")
    return np.concatenate([item.to_ndarray().reshape(-1) for item in frames]).astype("float32", copy=False)
