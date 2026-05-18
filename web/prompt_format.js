/**
 * comfyui-cyberdelia-prompt-format — Frontend extension
 *
 * Adds a "✨ Format" + "↶ Undo" button to existing prompt nodes that have
 * no built-in format step (CLIPTextEncode and its variants). Our own
 * PromptFormat nodes are NOT touched — they format automatically when the
 * workflow runs, so a button there would be redundant and cause confusion
 * (double-apply risk, and inconsistency between widget value and run output).
 *
 * Clicking the button sends the current prompt to /cyberdelia/prompt_format
 * and replaces the widget's value with the cleaned version.
 */

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// Foreign nodes that get the Format / Undo buttons.
// Add more here if you use other third-party encoders.
const FOREIGN_NODE_ALLOWLIST = new Set([
    "CLIPTextEncode",
    "CLIPTextEncodeSDXL",
    "CLIPTextEncodeSDXLRefiner",
    "CLIPTextEncodeFlux",
    "BNK_CLIPTextEncodeAdvanced",
    "smZ CLIPTextEncode",
]);

// Per-node-type preferences persisted in localStorage. Foreign nodes don't
// have our widget inputs, so toggles live in the right-click menu instead.
const STORAGE_KEY = "cyberdelia_promptformat_prefs";

function loadPrefs() {
    try {
        const raw = localStorage.getItem(STORAGE_KEY);
        return raw ? JSON.parse(raw) : {};
    } catch {
        return {};
    }
}

function savePrefs(prefs) {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
    } catch {
        /* quota / disabled storage — ignore */
    }
}

function getTextWidget(node) {
    if (!node.widgets) return null;
    // Prefer a widget literally named "text"; fall back to first multiline
    // STRING widget so "prompt" / "positive" etc. still work.
    const exact = node.widgets.find((w) => w.name === "text");
    if (exact) return exact;
    return node.widgets.find(
        (w) =>
            w.type === "customtext" ||
            (w.options && w.options.multiline && typeof w.value === "string"),
    );
}

async function callFormat(payload) {
    const res = await api.fetchApi("/cyberdelia/prompt_format", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });
    if (!res.ok) throw new Error(`Format failed (${res.status})`);
    return await res.json();
}

// One undo snapshot per node, keyed by node id.
const undoStore = new Map();

async function formatNode(node) {
    const textWidget = getTextWidget(node);
    if (!textWidget) return;

    const prefs = loadPrefs();
    const nodePrefs = prefs[node.comfyClass] || {};

    const payload = {
        text: textWidget.value ?? "",
        dedupe: nodePrefs.dedupe ?? true,
        remove_underscores: nodePrefs.remove_underscores ?? true,
        append_comma: nodePrefs.append_comma ?? true,
        // Foreign nodes don't expose exclusions/aliases — use defaults.
        // Users who want custom aliases should chain a PromptFormat node.
        exclusions: "",
        aliases: "",
    };

    try {
        const { text } = await callFormat(payload);
        if (typeof text !== "string") return;

        undoStore.set(node.id, textWidget.value);
        textWidget.value = text;
        if (textWidget.inputEl) textWidget.inputEl.value = text;

        node.setDirtyCanvas(true, true);
    } catch (err) {
        console.error("[PromptFormat]", err);
        alert(`Prompt Format failed: ${err.message}`);
    }
}

function undoNode(node) {
    const previous = undoStore.get(node.id);
    if (previous === undefined) return;
    const textWidget = getTextWidget(node);
    if (!textWidget) return;
    textWidget.value = previous;
    if (textWidget.inputEl) textWidget.inputEl.value = previous;
    undoStore.delete(node.id);
    node.setDirtyCanvas(true, true);
}

app.registerExtension({
    name: "Cyberdelia.PromptFormat",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        const name = nodeData.name;
        if (!FOREIGN_NODE_ALLOWLIST.has(name)) return;

        const origOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = origOnNodeCreated?.apply(this, arguments);

            this.addWidget("button", "✨ Format", "format", () => formatNode(this));
            this.addWidget("button", "↶ Undo", "undo", () => undoNode(this));

            return r;
        };

        const origGetExtraMenuOptions = nodeType.prototype.getExtraMenuOptions;
        nodeType.prototype.getExtraMenuOptions = function (_, options) {
            const r = origGetExtraMenuOptions?.apply(this, arguments);

            const node = this;
            const prefs = loadPrefs();
            const nodePrefs = prefs[name] || {};

            const toggle = (key, label, fallback = true) => ({
                content: `${(nodePrefs[key] ?? fallback) ? "✓ " : "  "}${label}`,
                callback: () => {
                    const p = loadPrefs();
                    p[name] = {
                        ...(p[name] || {}),
                        [key]: !(p[name]?.[key] ?? fallback),
                    };
                    savePrefs(p);
                },
            });

            options.unshift(
                { content: "✨ Format prompt", callback: () => formatNode(node) },
                { content: "↶ Undo format", callback: () => undoNode(node) },
                null, // separator
                toggle("dedupe", "Dedupe"),
                toggle("remove_underscores", "Remove underscores"),
                toggle("append_comma", "Append comma"),
                null, // separator
            );

            return r;
        };
    },
});
