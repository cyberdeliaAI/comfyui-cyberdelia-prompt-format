/**
 * comfyui-cyberdelia-prompt-format — Frontend extension
 *
 * Adds a compact "✨ Format" + "↶ Undo" action row to existing encoder nodes.
 * Our PromptFormat nodes format automatically when the workflow runs, but get
 * a standard Format button plus right-click Undo for manual cleanup.
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

const CYBERDELIA_NODE_CLASSES = new Set([
    "CyberdeliaPromptFormat",
    "CyberdeliaPromptFormatEncode",
]);

const CYBERDELIA_FORMAT_BUTTON = "✨ Format";
const ACTION_WIDGET_NAME = "cyberdelia_promptformat_actions";
const ACTION_ROW_HEIGHT = 24;

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

function hasActionRow(node) {
    return FOREIGN_NODE_ALLOWLIST.has(node.comfyClass ?? node.type);
}

function applyNodeEnhancements(node) {
    if (FOREIGN_NODE_ALLOWLIST.has(node.comfyClass ?? node.type)) {
        addActionRowWidget(node);
        node.setDirtyCanvas?.(true, true);
    }
}

function scheduleNodeEnhancements(node) {
    if (!node || !hasActionRow(node)) return;
    queueMicrotask(() => applyNodeEnhancements(node));
    setTimeout(() => applyNodeEnhancements(node), 0);
}

function getActionButtonRects(width, y = 0) {
    const margin = 10;
    const gap = 6;
    const height = 18;
    const buttonWidth = Math.max(36, (width - margin * 2 - gap) / 2);
    const top = y + Math.floor((ACTION_ROW_HEIGHT - height) / 2);

    return {
        format: { x: margin, y: top, w: buttonWidth, h: height },
        undo: { x: margin + buttonWidth + gap, y: top, w: buttonWidth, h: height },
    };
}

function drawActionButton(ctx, rect, label, disabled = false) {
    ctx.save();
    ctx.fillStyle = disabled ? "rgba(255,255,255,0.035)" : "rgba(255,255,255,0.075)";
    ctx.strokeStyle = disabled ? "rgba(255,255,255,0.12)" : "rgba(255,255,255,0.22)";
    ctx.lineWidth = 1;

    if (ctx.roundRect) {
        ctx.beginPath();
        ctx.roundRect(rect.x, rect.y, rect.w, rect.h, 4);
        ctx.fill();
        ctx.stroke();
    } else {
        ctx.fillRect(rect.x, rect.y, rect.w, rect.h);
        ctx.strokeRect(rect.x, rect.y, rect.w, rect.h);
    }

    ctx.fillStyle = disabled ? "rgba(255,255,255,0.45)" : "rgba(255,255,255,0.82)";
    ctx.font = "11px sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(label, rect.x + rect.w / 2, rect.y + rect.h / 2 + 0.5);
    ctx.restore();
}

function pointInRect(point, rect) {
    return (
        point[0] >= rect.x &&
        point[0] <= rect.x + rect.w &&
        point[1] >= rect.y &&
        point[1] <= rect.y + rect.h
    );
}

function getActionAtPosition(widget, pos) {
    const width = widget._lastWidth ?? 0;
    const rects = getActionButtonRects(width);

    if (pointInRect(pos, rects.format)) return "format";
    if (pointInRect(pos, rects.undo)) return "undo";

    const absolutePos = [pos[0], pos[1] - (widget._lastY ?? 0)];
    if (pointInRect(absolutePos, rects.format)) return "format";
    if (pointInRect(absolutePos, rects.undo)) return "undo";

    return null;
}

function addActionRowWidget(node) {
    if (node.widgets?.some((w) => w.name === ACTION_WIDGET_NAME)) return;

    const widget = {
        name: ACTION_WIDGET_NAME,
        type: "custom",
        value: "",
        options: { serialize: false },
        computeSize(width) {
            return [width, ACTION_ROW_HEIGHT];
        },
        draw(ctx, node, width, y) {
            this._lastWidth = width;
            this._lastY = y;

            const rects = getActionButtonRects(width, y);
            drawActionButton(ctx, rects.format, "✨ Format");
            drawActionButton(ctx, rects.undo, "↶ Undo", !undoStore.has(node.id));
        },
        mouse(event, pos, node) {
            if (!["mousedown", "pointerdown"].includes(event.type)) return false;

            const action = getActionAtPosition(this, pos);
            if (action === "format") {
                formatNode(node);
                return true;
            }
            if (action === "undo") {
                undoNode(node);
                return true;
            }
            return false;
        },
    };

    if (node.addCustomWidget) {
        node.addCustomWidget(widget);
    } else {
        node.widgets = node.widgets || [];
        node.widgets.push(widget);
    }
}

function addCyberdeliaFormatButton(node) {
    if (node.widgets?.some((w) => w.name === CYBERDELIA_FORMAT_BUTTON)) return;

    const widget = node.addWidget?.(
        "button",
        CYBERDELIA_FORMAT_BUTTON,
        "format",
        () => formatNode(node),
    );

    if (widget) {
        widget.options = { ...(widget.options || {}), serialize: false };
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

function getWidgetValue(node, name, fallback) {
    const widget = node.widgets?.find((w) => w.name === name);
    return widget?.value ?? fallback;
}

function getFormatOptions(node) {
    if (CYBERDELIA_NODE_CLASSES.has(node.comfyClass ?? node.type)) {
        return {
            dedupe: Boolean(getWidgetValue(node, "dedupe", true)),
            remove_underscores: Boolean(getWidgetValue(node, "remove_underscores", true)),
            append_comma: Boolean(getWidgetValue(node, "append_comma", true)),
            exclusions: getWidgetValue(node, "exclusions", "") || "",
            aliases: getWidgetValue(node, "aliases", "") || "",
        };
    }

    const prefs = loadPrefs();
    const nodePrefs = prefs[node.comfyClass] || {};

    return {
        dedupe: nodePrefs.dedupe ?? true,
        remove_underscores: nodePrefs.remove_underscores ?? true,
        append_comma: nodePrefs.append_comma ?? true,
        // Foreign nodes don't expose exclusions/aliases — use defaults.
        // Users who want custom aliases should chain a PromptFormat node.
        exclusions: "",
        aliases: "",
    };
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

    const payload = {
        text: textWidget.value ?? "",
        ...getFormatOptions(node),
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

        if (CYBERDELIA_NODE_CLASSES.has(name)) {
            const origOnNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                const r = origOnNodeCreated?.apply(this, arguments);
                addCyberdeliaFormatButton(this);
                return r;
            };

            const origGetExtraMenuOptions = nodeType.prototype.getExtraMenuOptions;
            nodeType.prototype.getExtraMenuOptions = function (_, options) {
                const r = origGetExtraMenuOptions?.apply(this, arguments);
                const node = this;

                options.unshift(
                    { content: "✨ Format prompt", callback: () => formatNode(node) },
                    { content: "↶ Undo format", callback: () => undoNode(node) },
                    null,
                );

                return r;
            };

            return;
        }

        if (!FOREIGN_NODE_ALLOWLIST.has(name)) return;

        const origOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = origOnNodeCreated?.apply(this, arguments);

            scheduleNodeEnhancements(this);

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

    nodeCreated(node) {
        scheduleNodeEnhancements(node);
    },

    loadedGraphNode(node) {
        scheduleNodeEnhancements(node);
    },
});
