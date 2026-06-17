"""
comfyui-cyberdelia-prompt-format

Cleans up prompts: removes duplicate tags, fixes bracket/comma spacing,
swaps underscores to spaces (with exclusions), and optionally appends
a trailing comma per line.

"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import folder_paths  # type: ignore  # provided by ComfyUI at runtime


@dataclass(frozen=True)
class ProtectedNames:
    exact: list[str]
    wildcard_patterns: list[re.Pattern]


# --------------------------------------------------------------------------
# Core formatter (Python port of LeFormatter from prompt_format.js)
# --------------------------------------------------------------------------


class PromptFormatter:
    """Stateless formatter. All methods are classmethods; instance-free."""

    # Placeholder tokens used during pipeline so regex passes don't mangle
    # protected content.
    _SHY = "$SHY$"
    _CAT = "$CAT$"
    _TI_TEMPLATE = "@TEXTUAL{}INVERSION@"

    # --- Network (lora/lyco) stripping -----------------------------------

    # Matches angle-bracket networks like <lora:name:1.0> and lbw block weights.
    _RE_BLOCK_WEIGHT = re.compile(r"(lbw=)?\s*(\d+(\.\d+)?)(\s*,\s*(\d+(\.\d+)?))+")
    _RE_NETWORK = re.compile(r"\s*<.+?>\s*")

    @classmethod
    def _strip_networks(cls, text: str) -> str:
        """Remove <lora:...> / <lyco:...> / block-weight syntax entirely."""
        text = cls._RE_BLOCK_WEIGHT.sub("", text)
        text = cls._RE_NETWORK.sub(" ", text)
        return text

    # --- Expression protection (emoticons like "> <" and ":3") -----------

    _RE_SHY_IN = re.compile(r"(?:,|\n|^)\s*> <\s*(?:,|\n|$)")
    _RE_CAT_IN = re.compile(r"(?:,|\n|^)\s*:3\s*(?:,|\n|$)")

    @classmethod
    def _protect_expressions(cls, text: str) -> str:
        text = cls._RE_SHY_IN.sub(f", {cls._SHY},", text)
        text = cls._RE_CAT_IN.sub(f", {cls._CAT},", text)
        return text

    @classmethod
    def _restore_expressions(cls, text: str) -> str:
        return text.replace(cls._SHY, "> <").replace(cls._CAT, ":3")

    # --- Underscore handling ---------------------------------------------

    @classmethod
    def _rm_underscore(cls, text: str, protected: ProtectedNames) -> str:
        """Replace underscores with spaces, but not inside protected names
        (embedding / textual-inversion filenames or user-excluded tags)."""
        if not text.strip():
            return ""

        # Swap protected names out for placeholders
        placeholders: list[str] = []

        for pattern in protected.wildcard_patterns:
            def stash(match):
                placeholders.append(match.group(0))
                return cls._TI_TEMPLATE.format(len(placeholders) - 1)

            text = pattern.sub(stash, text)

        for name in protected.exact:
            if name and name in text:
                placeholders.append(name)
                text = text.replace(name, cls._TI_TEMPLATE.format(len(placeholders) - 1))

        text = text.replace("_", " ")

        for i, name in enumerate(placeholders):
            text = text.replace(cls._TI_TEMPLATE.format(i), name)

        return text

    # --- Deduplication ---------------------------------------------------

    _RE_KEYWORD = re.compile(r"^(AND|BREAK)$")
    _RE_BRACKETS = re.compile(r"[\[\]\(\)]")
    _RE_MULTISPACE = re.compile(r"\s+")

    @classmethod
    def _dedupe(cls, tags: list[str], aliases: list[tuple[re.Pattern, str]]) -> list[str]:
        unique: set[str] = set()
        out: list[str] = []

        for tag in tags:
            cleaned = cls._RE_BRACKETS.sub("", tag)
            cleaned = cls._RE_MULTISPACE.sub(" ", cleaned).strip()

            # Keep prompt-control keywords (AND, BREAK) as-is, always.
            if cls._RE_KEYWORD.match(cleaned):
                out.append(tag)
                continue

            # Pure numbers (e.g. weights) pass through.
            try:
                float(cleaned)
                out.append(tag)
                continue
            except ValueError:
                pass

            # Alias lookup: if tag matches a pattern, substitute with main tag
            substitute: str | None = None
            for pattern, main_tag in aliases:
                if pattern.match(cleaned):
                    substitute = main_tag
                    break

            if substitute is None and cleaned not in unique:
                unique.add(cleaned)
                out.append(tag)
                continue

            if substitute is not None and substitute not in unique:
                unique.add(substitute)
                out.append(tag.replace(cleaned, substitute))
                continue

            # Duplicate: blank out the content but keep the slot so brackets
            # upstream still balance. The later "prune empty chunks" pass
            # removes it.
            out.append(tag.replace(cleaned, ""))

        return out

    # --- Main per-line formatter -----------------------------------------

    # Comma-after-bracket cleanups
    _RE_FIX_COMMAS = [
        (re.compile(r",+\s*\)"), "),"),
        (re.compile(r",+\s*\]"), "],"),
        (re.compile(r",+\s*\}"), "},"),
        (re.compile(r"\(\s*,+"), ",("),
        (re.compile(r"\[\s*,+"), ",["),
        (re.compile(r"\{\s*,+"), ",{"),
    ]
    _RE_FIX_SPACES = [
        (re.compile(r"\s+\)"), ")"),
        (re.compile(r"\s+\]"), "]"),
        (re.compile(r"\s+\}"), "}"),
        (re.compile(r"\(\s+"), "("),
        (re.compile(r"\[\s+"), "["),
        (re.compile(r"\{\s+"), "{"),
    ]
    _RE_PIPE = re.compile(r"\s*\|\s*")
    _RE_COLON = re.compile(r"\s*\:\s*")
    _RE_EMPTY_BRACKET = re.compile(r"\(\s*\)|\[\s*\]")
    _RE_FRANCHISE = re.compile(r"\\\(([^\\\)]+?):([^\\\)]+?)\\\)")
    _RE_COLON_CLEAN = re.compile(r",\s*:(\d)")

    @classmethod
    def format_line(
        cls,
        line: str,
        dedupe: bool,
        rm_underscore: bool,
        protected: ProtectedNames,
        aliases: list[tuple[re.Pattern, str]],
    ) -> str:
        # 1) Strip LoRA/network syntax outright (ComfyUI handles those elsewhere)
        line = cls._strip_networks(line)

        # 2) Underscore replacement (with embedding name protection)
        if rm_underscore:
            line = cls._rm_underscore(line, protected)

        # 3) Protect emoticons
        line = cls._protect_expressions(line)

        # 4) Normalize commas around brackets
        for pattern, repl in cls._RE_FIX_COMMAS:
            line = pattern.sub(repl, line)
        for pattern, repl in cls._RE_FIX_SPACES:
            line = pattern.sub(repl, line)

        # 5) Tighten pipe and colon syntax
        line = cls._RE_PIPE.sub("|", line)
        line = cls._RE_COLON.sub(":", line)

        # 6) Split into tags, dedupe, rejoin
        tags = [t.strip() for t in line.split(",")]
        if dedupe:
            tags = cls._dedupe(tags, aliases)

        line = ", ".join(tags)
        line = cls._RE_MULTISPACE.sub(" ", line)

        # 7) Drop empty brackets iteratively
        while cls._RE_EMPTY_BRACKET.search(line):
            line = cls._RE_EMPTY_BRACKET.sub("", line)

        # 8) Franchise escape: \(series: name\) -> \(series: name\)  (space after colon)
        line = cls._RE_FRANCHISE.sub(r"\\(\1: \2\\)", line)

        # 9) Prune empty chunks
        line = ", ".join(t.strip() for t in line.split(",") if t.strip())

        # 10) Clean up stray empty-before-colon like ",:2"
        line = cls._RE_COLON_CLEAN.sub(r":\1", line)

        # 11) Restore protected emoticons
        line = cls._restore_expressions(line)

        return line

    @classmethod
    def format_pipeline(
        cls,
        text: str,
        dedupe: bool,
        rm_underscore: bool,
        append_comma: bool,
        protected: ProtectedNames,
        aliases: list[tuple[re.Pattern, str]],
    ) -> str:
        lines = text.split("\n")
        formatted = [
            cls.format_line(line, dedupe, rm_underscore, protected, aliases)
            for line in lines
        ]

        if not append_comma:
            return "\n".join(formatted)

        joined = ",\n".join(formatted)
        joined = re.sub(r"\n,\n", "\n\n", joined)
        joined = re.sub(r"\s*,\s*$", "", joined)
        return joined


# --------------------------------------------------------------------------
# Helpers for gathering embedding filenames + parsing user aliases
# --------------------------------------------------------------------------


def get_embedding_names() -> list[str]:
    """Scan ComfyUI's embedding folders for filenames to protect during
    underscore replacement."""
    extensions = (".pt", ".pth", ".ckpt", ".safetensors", ".sft")
    names: set[str] = set()

    try:
        folders = folder_paths.get_folder_paths("embeddings")
    except Exception:
        folders = []

    for folder in folders:
        base = Path(folder)
        if not base.is_dir():
            continue
        for ext in extensions:
            for file in base.rglob(f"*{ext}"):
                names.add(file.stem)

    return sorted(names)


def parse_aliases(raw: str) -> list[tuple[re.Pattern, str]]:
    """Parse alias config (same syntax as Forge extension):

        main_tag: alt1, alt2, regex_pattern
        1girl: girl, woman, lady
        adult: \\d+\\s*(y\\.?o\\.?|[Yy]ear[s]? [Oo]ld)
    """
    aliases: list[tuple[re.Pattern, str]] = []
    if ":" not in raw:
        return aliases

    # Accept both the original multi-line format and a compact one-line
    # semicolon-separated format for the smaller aliases widget.
    entries = [
        part.strip()
        for line in raw.splitlines()
        for part in line.split(";")
        if part.strip()
    ]

    for line in entries:
        if ":" not in line:
            continue
        tag, words = line.split(":", 1)
        main = tag.strip()
        if not main:
            continue
        for word in (w.strip() for w in words.split(",")):
            if not word or word == main:
                continue
            # Strip anchors; we always anchor full-match in the formatter.
            cleaned = word.lstrip("^").rstrip("$")
            try:
                pattern = re.compile(f"^{cleaned}$")
            except re.error:
                continue
            aliases.append((pattern, main))

    return aliases


def parse_exclusions(raw: str) -> list[str]:
    """User-provided tags that should NOT have their underscores stripped
    (e.g. score_9, score_8_up, score_*)."""
    return [t.strip() for t in raw.split(",") if t.strip()]


def compile_wildcard_exclusion(raw: str) -> re.Pattern | None:
    """Compile an exclusion with * wildcards to a tag-ish text matcher."""
    if "*" not in raw:
        return None

    pieces = [re.escape(part) for part in raw.split("*")]
    pattern = r"[A-Za-z0-9_:\-.]*".join(pieces)
    try:
        return re.compile(rf"(?<![A-Za-z0-9_:\-.]){pattern}(?![A-Za-z0-9_:\-.])")
    except re.error:
        return None


# --------------------------------------------------------------------------
# ComfyUI Node
# --------------------------------------------------------------------------


class PromptFormatNode:
    """Clean up a prompt string.

    Inputs: raw prompt text + toggles.
    Output: cleaned prompt, ready to feed into a text encoder.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": (
                    "STRING",
                    {
                        "multiline": True,
                        "dynamicPrompts": True,
                        "placeholder": "your prompt here...",
                        "default": "",
                    },
                ),
                "dedupe": ("BOOLEAN", {"default": True}),
                "remove_underscores": ("BOOLEAN", {"default": True}),
                "append_comma": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "exclusions": (
                    "STRING",
                    {
                        "multiline": False,
                        "default": "",
                        "placeholder": "score_9, score_8_up, score_7_up",
                    },
                ),
                "aliases": (
                    "STRING",
                    {
                        "multiline": False,
                        "default": "",
                        "placeholder": "1girl: girl, woman, lady",
                    },
                ),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("prompt",)
    FUNCTION = "format"
    CATEGORY = "Cyberdelia/text"
    OUTPUT_NODE = False

    # Cache embedding list across calls within a session; invalidate cheaply.
    _embedding_cache: list[str] | None = None

    @classmethod
    def _get_protected(cls, exclusions: str) -> ProtectedNames:
        if cls._embedding_cache is None:
            cls._embedding_cache = get_embedding_names()
        extras: list[str] = []
        wildcard_patterns: list[re.Pattern] = []

        for exclusion in parse_exclusions(exclusions):
            pattern = compile_wildcard_exclusion(exclusion)
            if pattern is None:
                extras.append(exclusion)
            else:
                wildcard_patterns.append(pattern)

        # Longest names first so "score_8_up" matches before "score".
        exact = sorted(set(cls._embedding_cache + extras), key=len, reverse=True)
        return ProtectedNames(exact=exact, wildcard_patterns=wildcard_patterns)

    def format(
        self,
        text: str,
        dedupe: bool,
        remove_underscores: bool,
        append_comma: bool,
        exclusions: str = "",
        aliases: str = "",
    ):
        protected = self._get_protected(exclusions)
        alias_list = parse_aliases(aliases)

        cleaned = PromptFormatter.format_pipeline(
            text,
            dedupe=dedupe,
            rm_underscore=remove_underscores,
            append_comma=append_comma,
            protected=protected,
            aliases=alias_list,
        )
        return (cleaned,)


class PromptFormatEncodeNode:
    """Format a prompt AND encode it with a CLIP model in one step.

    Equivalent to chaining PromptFormat -> CLIPTextEncode.
    Output is CONDITIONING, ready for a sampler.
    """

    @classmethod
    def INPUT_TYPES(cls):
        base = PromptFormatNode.INPUT_TYPES()
        base["required"] = {"clip": ("CLIP",), **base["required"]}
        return base

    RETURN_TYPES = ("CONDITIONING",)
    RETURN_NAMES = ("conditioning",)
    FUNCTION = "encode"
    CATEGORY = "Cyberdelia/text"

    def encode(
        self,
        clip,
        text: str,
        dedupe: bool,
        remove_underscores: bool,
        append_comma: bool,
        exclusions: str = "",
        aliases: str = "",
    ):
        formatter = PromptFormatNode()
        (cleaned,) = formatter.format(
            text, dedupe, remove_underscores, append_comma, exclusions, aliases
        )

        tokens = clip.tokenize(cleaned)
        output = clip.encode_from_tokens_scheduled(tokens)
        return (output,)


# --------------------------------------------------------------------------
# API route for the frontend "Format" button
# --------------------------------------------------------------------------

try:
    from aiohttp import web
    from server import PromptServer  # type: ignore

    @PromptServer.instance.routes.post("/cyberdelia/prompt_format")
    async def _format_route(request):
        """Frontend calls this when the user clicks the ✨ Format button.
        Returns the cleaned prompt so the JS can write it back into the
        widget's textarea."""
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)

        text = data.get("text", "") or ""
        dedupe = bool(data.get("dedupe", True))
        rm_underscore = bool(data.get("remove_underscores", True))
        append_comma = bool(data.get("append_comma", True))
        exclusions = data.get("exclusions", "") or ""
        aliases = data.get("aliases", "") or ""

        protected = PromptFormatNode._get_protected(exclusions)
        alias_list = parse_aliases(aliases)

        cleaned = PromptFormatter.format_pipeline(
            text,
            dedupe=dedupe,
            rm_underscore=rm_underscore,
            append_comma=append_comma,
            protected=protected,
            aliases=alias_list,
        )
        return web.json_response({"text": cleaned})

except ImportError:
    # If we're imported outside ComfyUI (tests, tooling), skip route setup.
    pass
