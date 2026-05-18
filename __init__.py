"""comfyui-cyberdelia-prompt-format — Cyberdelia
"""

from .prompt_format import PromptFormatNode, PromptFormatEncodeNode

NODE_CLASS_MAPPINGS = {
    "CyberdeliaPromptFormat": PromptFormatNode,
    "CyberdeliaPromptFormatEncode": PromptFormatEncodeNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "CyberdeliaPromptFormat": "Prompt Format (Cyberdelia)",
    "CyberdeliaPromptFormatEncode": "Prompt Format + Encode (Cyberdelia)",
}

# Tells ComfyUI to serve everything in ./web as static frontend files
# and auto-load any .js files there as frontend extensions.
WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
