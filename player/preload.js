/**
 * preload.js
 * Exposes only safe APIs to renderer (no Node access in UI)
 */

const { contextBridge, ipcRenderer } = require("electron");

// ✅ NEW: Load lucide from node side (reliable in Electron)

contextBridge.exposeInMainWorld("amethyst", {
  pickFolder: () => ipcRenderer.invoke("pick-folder"),
  // Add this line alongside pickFolder and getLyrics
  getSongsFromDb: () => ipcRenderer.invoke("get-songs-from-db"),
  getLyrics: (fullPath, songTitle, songArtist, songLanguage) => 
  ipcRenderer.invoke("get-lyrics", fullPath, songTitle, songArtist, songLanguage),
  // ✅ NEW: return SVG string for an icon name
  // ✅ return SVG string for an icon name (works with lucide's iconNode format)
iconSvg: (name) => {
  try {
    if (!lucide?.icons) return "";

    const raw = String(name || "").trim();
    if (!raw) return "";

    // name variants: "skip-back" → ["skip-back","SkipBack","skipBack","skipback"]
    const pascal = raw
      .split("-")
      .map(w => w.charAt(0).toUpperCase() + w.slice(1))
      .join("");

    const camel = pascal ? pascal.charAt(0).toLowerCase() + pascal.slice(1) : "";
    const nodashLower = raw.replaceAll("-", "").toLowerCase();

    const icon =
      lucide.icons[raw] ||
      lucide.icons[pascal] ||
      lucide.icons[camel] ||
      lucide.icons[nodashLower] ||
      lucide.icons["Music"] ||
      lucide.icons["music"] ||
      null;

    if (!icon) return "";

    // If toSvg exists, use it
    if (typeof icon.toSvg === "function") {
      return icon.toSvg();
    }

    // Otherwise build SVG from iconNode (Lucide format)
    const nodes = icon.iconNode || icon[1] || null;
    if (!Array.isArray(nodes)) return "";

    const attrs = {
      xmlns: "http://www.w3.org/2000/svg",
      width: "24",
      height: "24",
      viewBox: "0 0 24 24",
      fill: "none",
      stroke: "currentColor",
      "stroke-width": "2",
      "stroke-linecap": "round",
      "stroke-linejoin": "round"
    };

    const attrStr = Object.entries(attrs)
      .map(([k, v]) => `${k}="${String(v)}"`)
      .join(" ");

    const children = nodes
      .map(([tag, a]) => {
        const aStr = Object.entries(a || {})
          .map(([k, v]) => `${k}="${String(v)}"`)
          .join(" ");
        return `<${tag} ${aStr}></${tag}>`;
      })
      .join("");

    return `<svg ${attrStr}>${children}</svg>`;
  } catch (e) {
    return "";
  }
}
});
