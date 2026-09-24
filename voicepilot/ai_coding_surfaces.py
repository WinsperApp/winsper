"""Exact app identities for popular AI-assisted development surfaces.

Keep this registry identity-only. Prompt behavior remains generic and depends on
the semantic ``profile``/``destination`` pair, never on a product-specific prompt.
Terminal agents are intentionally absent: Windows reports their terminal host as
the foreground app, so guessing from process or document titles would be unsafe.
IDE extensions such as Copilot, Cline, Roo Code, Continue, Gemini Code Assist,
Amazon Q, and JetBrains AI intentionally inherit their verified editor route.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NativeAICodingSurface:
    id: str
    label: str
    processes: tuple[str, ...]
    profile: str
    destination: str


@dataclass(frozen=True)
class WebAICodingSurface:
    id: str
    label: str
    domain: str
    profile: str
    destination: str


NATIVE_AI_CODING_SURFACES: tuple[NativeAICodingSurface, ...] = (
    # Standalone agent/chat surfaces: spoken text is normally an AI prompt.
    NativeAICodingSurface("codex", "Codex", ("codex.exe",), "prompt", "prompt"),
    NativeAICodingSurface("chatgpt", "ChatGPT", ("chatgpt.exe",), "prompt", "prompt"),
    NativeAICodingSurface("claude", "Claude", ("claude.exe",), "prompt", "prompt"),
    NativeAICodingSurface("antigravity", "Antigravity", ("antigravity.exe",), "prompt", "prompt"),
    NativeAICodingSurface("ollama-app", "Ollama", ("ollama app.exe",), "prompt", "prompt"),
    # Full editors/IDEs: preserve code syntax and editor context by default.
    NativeAICodingSurface(
        "antigravity-ide",
        "Antigravity IDE",
        ("antigravity ide.exe",),
        "code",
        "code",
    ),
    NativeAICodingSurface("kiro", "Kiro", ("kiro.exe",), "code", "code"),
    NativeAICodingSurface("trae", "TRAE", ("trae.exe",), "code", "code"),
    NativeAICodingSurface("zed", "Zed", ("zed.exe", "zed-preview.exe"), "code", "code"),
    NativeAICodingSurface("vscodium", "VSCodium", ("vscodium.exe",), "code", "code"),
)


WEB_AI_CODING_SURFACES: tuple[WebAICodingSurface, ...] = (
    # Browser IDEs and code workspaces.
    WebAICodingSurface("replit", "Replit", "replit.com", "code", "code"),
    WebAICodingSurface("stackblitz", "StackBlitz", "stackblitz.com", "code", "code"),
    WebAICodingSurface("codesandbox", "CodeSandbox", "codesandbox.io", "code", "code"),
    WebAICodingSurface("github-codespaces", "GitHub Codespaces", "github.dev", "code", "code"),
    WebAICodingSurface("vscode-web", "VS Code", "vscode.dev", "code", "code"),
    WebAICodingSurface(
        "firebase-studio",
        "Firebase Studio",
        "studio.firebase.google.com",
        "code",
        "code",
    ),
    WebAICodingSurface("gitpod", "Gitpod", "gitpod.io", "code", "code"),
    # Prompt-first app builders.
    WebAICodingSurface("bolt", "Bolt", "bolt.new", "prompt", "prompt"),
    WebAICodingSurface("v0", "v0", "v0.dev", "prompt", "prompt"),
    WebAICodingSurface("lovable", "Lovable", "lovable.dev", "prompt", "prompt"),
    WebAICodingSurface("base44", "Base44", "base44.com", "prompt", "prompt"),
)


NATIVE_AI_PROCESS_DESTINATIONS = {
    process.casefold(): surface.destination
    for surface in NATIVE_AI_CODING_SURFACES
    for process in surface.processes
}

NATIVE_AI_PROCESS_LABELS = {
    process.casefold(): surface.label
    for surface in NATIVE_AI_CODING_SURFACES
    for process in surface.processes
}


def native_ai_profile_hints() -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple(
        (
            profile,
            tuple(
                process
                for surface in NATIVE_AI_CODING_SURFACES
                if surface.profile == profile
                for process in surface.processes
            ),
        )
        for profile in ("prompt", "code")
    )


def web_ai_domains(profile: str) -> tuple[str, ...]:
    return tuple(surface.domain for surface in WEB_AI_CODING_SURFACES if surface.profile == profile)


def web_ai_surface_for_domain(domain: str) -> WebAICodingSurface | None:
    folded = domain.strip().casefold().rstrip(".")
    return next(
        (
            surface
            for surface in WEB_AI_CODING_SURFACES
            if folded == surface.domain or folded.endswith(f".{surface.domain}")
        ),
        None,
    )
