"""Compatibility facade for Winsper's Polish service."""

from .polish_prompts import (
    build_polish_prompt,
    build_rewrite_prompt,
    clean_model_output,
    dedupe_terms,
    destination_formatting_guidance,
    language_display_name,
    polish_destination_example,
    polish_language_guidance,
    prompt_profile_for_model,
    prompt_block,
)
from .polish_service import TextRewriter
from .polish_validation import (
    apply_cpp_file_aliases,
    apply_spoken_formatting,
    leaks_superseded_numeric_facts,
    looks_like_degenerate_output,
    looks_like_polish_instruction_echo,
    missing_protected_identifiers,
    polish_correction_validation_failed,
    prepare_polish_input,
    preserves_numeric_facts,
    superseded_numeric_facts,
    violates_selected_text_boundary,
)

__all__ = [
    "TextRewriter",
    "apply_cpp_file_aliases",
    "apply_spoken_formatting",
    "build_polish_prompt",
    "build_rewrite_prompt",
    "clean_model_output",
    "dedupe_terms",
    "destination_formatting_guidance",
    "language_display_name",
    "leaks_superseded_numeric_facts",
    "looks_like_degenerate_output",
    "looks_like_polish_instruction_echo",
    "missing_protected_identifiers",
    "polish_correction_validation_failed",
    "polish_destination_example",
    "polish_language_guidance",
    "prompt_profile_for_model",
    "prepare_polish_input",
    "preserves_numeric_facts",
    "prompt_block",
    "superseded_numeric_facts",
    "violates_selected_text_boundary",
]
