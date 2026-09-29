/* Odd$ Vault engine. Runs entirely in the browser: no fetch/XHR/upload calls, no logging.
   Requires window.zip (vendor/zip.min.js). pdf-lib is loaded on demand the first time a PDF is cleaned.
   Integration hooks (counts only, never file names or passwords): "vault:started" and "vault:success"
   CustomEvents on document. */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const state = { files: [] };
  const EPOCH = new Date(315532800000); // 1980-01-01, the earliest zip date

  if (window.zip) zip.configure({ useWebWorkers: false });

  /* ---------- helpers ---------- */
  const ascii = (b, s, n) => String.fromCharCode(...b.subarray(s, s + n));
  const concat = parts => {
    const out = new Uint8Array(parts.reduce((a, p) => a + p.length, 0));
    let o = 0; for (const p of parts) { out.set(p, o); o += p.length; }
    return out;
  };
  const fmt = n => n < 1024 ? n + " B" : n < 1048576 ? (n / 1024).toFixed(1) + " KB" : (n / 1048576).toFixed(1) + " MB";
  const ext = name => (name.split(".").pop() || "").toLowerCase();
  const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  const KINDS = { jpg: "jpeg", jpeg: "jpeg", png: "png", webp: "webp", pdf: "pdf", docx: "office", xlsx: "office", pptx: "office" };
  const kindOf = f => KINDS[ext(f.name)] || null;

  /* ---------- JPEG ---------- */
  function exifHasGps(seg) {
    try {
      const t = 10, le = seg[t] === 0x49;
      const dv = new DataView(seg.buffer, seg.byteOffset, seg.byteLength);
      const ifd = t + dv.getUint32(t + 4, le), n = dv.getUint16(ifd, le);
      for (let k = 0; k < n; k++) if (dv.getUint16(ifd + 2 + k * 12, le) === 0x8825) return true;
    } catch (e) {}
    return false;
  }
  function stripJpeg(b) {
    if (b[0] !== 0xFF || b[1] !== 0xD8) throw new Error("Not a valid JPEG");
    const out = [b.subarray(0, 2)], found = new Set();
    let i = 2;
    while (i < b.length) {
      if (b[i] !== 0xFF) { out.push(b.subarray(i)); break; }
      const m = b[i + 1];
      if (m === 0xFF) { i++; continue; }
      if (m === 0xD9) break; // end of image: drops any trailing data
      if ((m >= 0xD0 && m <= 0xD7) || m === 0x01) { out.push(b.subarray(i, i + 2)); i += 2; continue; }
      const len = (b[i + 2] << 8) | b[i + 3];
      const seg = b.subarray(i, i + 2 + len);
      if (m === 0xDA) { out.push(b.subarray(i)); break; }
      const isMeta = (m >= 0xE1 && m <= 0xEF && m !== 0xEE) || m === 0xFE;
      const isIcc = m === 0xE2 && ascii(seg, 4, 11) === "ICC_PROFILE";
      if (isMeta && !isIcc) {
        if (m === 0xE1 && ascii(seg, 4, 4) === "Exif") { found.add("EXIF"); if (exifHasGps(seg)) found.add("GPS location"); }
        else if (m === 0xE1) found.add("XMP");
        else if (m === 0xED) found.add("IPTC/Photoshop");
        else if (m === 0xFE) found.add("Comment");
        else found.add("Extra data");
      } else out.push(seg);
      i += 2 + len;
    }
    return { bytes: concat(out), found: [...found] };
  }

  /* ---------- PNG ---------- */
  function stripPng(b) {
    const sig = [137, 80, 78, 71, 13, 10, 26, 10];
    if (!sig.every((v, k) => b[k] === v)) throw new Error("Not a valid PNG");
    const dv = new DataView(b.buffer, b.byteOffset, b.byteLength);
    const drop = { tEXt: "Text", zTXt: "Text", iTXt: "Text/XMP", eXIf: "EXIF", tIME: "Timestamp", dSIG: "Signature" };
    const out = [b.subarray(0, 8)], found = new Set();
    let i = 8;
    while (i + 12 <= b.length) {
      const len = dv.getUint32(i), type = ascii(b, i + 4, 4), end = i + 12 + len;
      if (drop[type]) found.add(drop[type]); else out.push(b.subarray(i, end));
      i = end;
      if (type === "IEND") break;
    }
    return { bytes: concat(out), found: [...found] };
  }

  /* ---------- WebP ---------- */
  function stripWebp(b) {
    if (ascii(b, 0, 4) !== "RIFF" || ascii(b, 8, 4) !== "WEBP") throw new Error("Not a valid WebP");
    const dv = new DataView(b.buffer, b.byteOffset, b.byteLength);
    const body = [], found = new Set();
    let i = 12;
    while (i + 8 <= b.length) {
      const type = ascii(b, i, 4), len = dv.getUint32(i + 4, true), pad = len & 1, end = i + 8 + len + pad;
      if (type === "EXIF") found.add("EXIF");
      else if (type === "XMP ") found.add("XMP");
      else {
        const chunk = b.slice(i, Math.min(end, b.length));
        if (type === "VP8X") chunk[8] &= ~(0x08 | 0x04);
        body.push(chunk);
      }
      i = end;
    }
    const payload = concat(body), head = new Uint8Array(12);
    head.set(b.subarray(0, 4)); new DataView(head.buffer).setUint32(4, payload.length + 4, true); head.set(b.subarray(8, 12), 8);
    return { bytes: concat([head, payload]), found: [...found] };
  }

  /* ---------- PDF ---------- */
  let pdfLibReady = null;
  const loadPdfLib = () => window.PDFLib ? Promise.resolve() : (pdfLibReady = pdfLibReady || new Promise((ok, fail) => {
    const s = document.createElement("script");
    s.src = "/tools/odds-vault/vendor/pdf-lib.min.js";
    s.onload = ok;
    s.onerror = () => { pdfLibReady = null; fail(new Error("PDF engine failed to load")); };
    document.head.appendChild(s);
  }));
  async function stripPdf(b) {
    await loadPdfLib();
    const { PDFDocument, PDFName } = PDFLib;
    const doc = await PDFDocument.load(b, { updateMetadata: false });
    const found = [];
    const infoRef = doc.context.trailerInfo.Info;
    const info = infoRef && doc.context.lookup(infoRef);
    if (info && info.delete) {
      for (const k of ["Title", "Author", "Subject", "Keywords", "Creator", "Producer", "CreationDate", "ModDate"]) {
        if (info.get(PDFName.of(k))) { found.push(k); info.delete(PDFName.of(k)); }
      }
    }
    const xmp = doc.catalog.get(PDFName.of("Metadata"));
    if (xmp) {
      found.push("XMP"); doc.catalog.delete(PDFName.of("Metadata"));
      // Integration fix: pdf-lib still writes unreferenced objects, so the XMP stream itself stayed in the file. Drop it.
      if (xmp instanceof PDFLib.PDFRef) doc.context.delete(xmp);
    }
    const bytes = await doc.save({ updateFieldAppearances: false });
    return { bytes, found };
  }

  /* ---------- Office (docx / xlsx / pptx) ---------- */
  const CORE = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"/>';
  const APP = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"/>';
  async function stripOffice(file) {
    const reader = new zip.ZipReader(new zip.BlobReader(file));
    const entries = await reader.getEntries();
    const writer = new zip.ZipWriter(new zip.BlobWriter("application/zip"));
    const found = new Set();
    for (const e of entries) {
      if (e.directory) continue;
      const n = e.filename;
      if (/^docProps\/thumbnail\./i.test(n)) { found.add("Preview thumbnail"); continue; }
      let data;
      if (n === "docProps/core.xml") {
        const t = await e.getData(new zip.TextWriter());
        if (/<dc:creator>[^<]+/.test(t)) found.add("Author");
        if (/<cp:lastModifiedBy>[^<]+/.test(t)) found.add("Last modified by");
        if (/<dc:title>[^<]+/.test(t)) found.add("Title");
        found.add("Dates");
        data = new zip.TextReader(CORE);
      } else if (n === "docProps/app.xml") {
        const t = await e.getData(new zip.TextWriter());
        if (/<Company>[^<]+/.test(t)) found.add("Company");
        if (/<Manager>[^<]+/.test(t)) found.add("Manager");
        found.add("App details");
        data = new zip.TextReader(APP);
      } else if (n === "_rels/.rels") {
        const t = await e.getData(new zip.TextWriter());
        data = new zip.TextReader(t.replace(/<Relationship\b[^>]*thumbnail[^>]*\/>/gi, ""));
      } else {
        data = new zip.BlobReader(await e.getData(new zip.BlobWriter()));
      }
      await writer.add(n, data, { lastModDate: EPOCH, level: 6 });
    }
    await reader.close();
    const blob = await writer.close();
    return { bytes: new Uint8Array(await blob.arrayBuffer()), found: [...found] };
  }

  /* ---------- pipeline ---------- */
  async function clean(file, kind) {
    if (kind === "office") return stripOffice(file);
    const b = new Uint8Array(await file.arrayBuffer());
    if (kind === "jpeg") return stripJpeg(b);
    if (kind === "png") return stripPng(b);
    if (kind === "webp") return stripWebp(b);
    if (kind === "pdf") return stripPdf(b);
  }

  /* ---------- UI: files ---------- */
  const drop = $("drop"), picker = $("picker");
  drop.addEventListener("click", () => picker.click());
  drop.addEventListener("keydown", e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); picker.click(); } });
  ["dragenter", "dragover"].forEach(t => drop.addEventListener(t, e => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach(t => drop.addEventListener(t, e => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", e => addFiles(e.dataTransfer.files));
  picker.addEventListener("change", () => { addFiles(picker.files); picker.value = ""; });

  let started = false;
  function addFiles(list) {
    for (const f of list) state.files.push(f);
    if (!started && state.files.length) { started = true; document.dispatchEvent(new CustomEvent("vault:started")); }
    renderFiles();
  }
  function renderFiles() {
    const ul = $("files"); ul.innerHTML = "";
    state.files.forEach((f, idx) => {
      const k = kindOf(f), li = document.createElement("li");
      li.innerHTML = `<span class="n">${esc(f.name)}</span><span class="s">${fmt(f.size)}</span>
        <span class="t ${k ? "" : "no"}">${k ? "can clean" : "can't clean"}</span>
        <button class="x" aria-label="Remove ${esc(f.name)}">&times;</button>`;
      li.querySelector("button").onclick = () => { state.files.splice(idx, 1); renderFiles(); };
      ul.appendChild(li);
    });
    validate();
  }

  /* ---------- UI: password ---------- */
  const pw = $("pw"), pw2 = $("pw2");
  function entropy(s) {
    let pool = 0;
    if (/[a-z]/.test(s)) pool += 26; if (/[A-Z]/.test(s)) pool += 26;
    if (/\d/.test(s)) pool += 10; if (/[^A-Za-z0-9]/.test(s)) pool += 32;
    let bits = s.length * Math.log2(pool || 1);
    if (/^(.)\1+$/.test(s) || /(password|123456|qwerty|letmein)/i.test(s)) bits = Math.min(bits, 20);
    return bits;
  }
  function validate() {
    const s = pw.value, bits = entropy(s);
    const lvl = !s ? [0, "&nbsp;", "#c8402f"] : bits < 40 ? [18, "Weak", "#c8402f"] : bits < 60 ? [45, "Fair", "#e8b64c"] : bits < 80 ? [72, "Good", "#b6d68a"] : [100, "Strong", "#8fd19e"];
    $("bar").style.width = lvl[0] + "%"; $("bar").style.background = lvl[2]; $("strength").innerHTML = lvl[1];
    const mismatch = pw2.value && pw.value !== pw2.value;
    if (mismatch) $("strength").innerHTML = "Passwords don't match";
    const usable = state.files.some(f => kindOf(f) || $("incUnsupported").checked);
    $("go").disabled = !(usable && s.length >= 10 && s === pw2.value);
  }
  [pw, pw2, $("incUnsupported")].forEach(el => el.addEventListener("input", validate));
  $("incUnsupported").addEventListener("change", validate);
  $("show").onclick = () => {
    const showing = pw.type === "text";
    pw.type = pw2.type = showing ? "password" : "text";
    $("show").textContent = showing ? "Show" : "Hide";
  };
  $("gen").onclick = async () => {
    const chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%^&*-_=+";
    const r = new Uint32Array(22); crypto.getRandomValues(r);
    const p = [...r].map(v => chars[v % chars.length]).join("");
    pw.value = pw2.value = p; pw.type = pw2.type = "text"; $("show").textContent = "Hide";
    try { await navigator.clipboard.writeText(p); $("status").textContent = "Password generated and copied. Save it somewhere safe before you continue."; } catch (e) { $("status").textContent = "Password generated. Save it somewhere safe before you continue."; }
    validate();
  };

  /* ---------- run ---------- */
  $("go").addEventListener("click", async () => {
    const btn = $("go"), status = $("status"), rows = $("rows");
    btn.disabled = true; rows.innerHTML = ""; $("report").classList.add("hidden");
    const results = [], toZip = [], used = new Set();
    const uniq = name => {
      if (!used.has(name)) { used.add(name); return name; }
      const dot = name.lastIndexOf("."), base = dot > 0 ? name.slice(0, dot) : name, x = dot > 0 ? name.slice(dot) : "";
      let n = 2; while (used.has(`${base} (${n})${x}`)) n++;
      const u = `${base} (${n})${x}`; used.add(u); return u;
    };
    try {
      for (let i = 0; i < state.files.length; i++) {
        const f = state.files[i], kind = kindOf(f);
        status.textContent = `Cleaning ${f.name} (${i + 1} of ${state.files.length})…`;
        if (!kind) {
          if ($("incUnsupported").checked) {
            toZip.push({ name: uniq(f.name), blob: f });
            results.push({ name: f.name, msg: "Added unchanged. Can't clean this file type.", cls: "bad", size: fmt(f.size) });
          } else results.push({ name: f.name, msg: "Skipped. Can't clean this file type.", cls: "bad", size: fmt(f.size) });
          continue;
        }
        try {
          const r = await clean(f, kind);
          toZip.push({ name: uniq(f.name), blob: new Blob([r.bytes]) });
          results.push({ name: f.name, msg: r.found.length ? "Removed: " + r.found.join(", ") : "Clean. No common metadata found.", cls: "ok", size: `${fmt(f.size)} → ${fmt(r.bytes.length)}` });
        } catch (err) {
          results.push({ name: f.name, msg: "Left out. Couldn't be cleaned (" + (err.message || "unreadable or encrypted") + ").", cls: "bad", size: fmt(f.size) });
        }
        await new Promise(r => setTimeout(r));
      }
      if (!toZip.length) throw new Error("No files were left to zip. See the report below.");

      status.textContent = "Encrypting…";
      const opts = { password: pw.value, encryptionStrength: 3, lastModDate: EPOCH };
      let outer;
      if ($("hide").checked) {
        const inner = new zip.ZipWriter(new zip.BlobWriter("application/zip"));
        for (const t of toZip) await inner.add(t.name, new zip.BlobReader(t.blob), { lastModDate: EPOCH });
        const innerBlob = await inner.close();
        outer = new zip.ZipWriter(new zip.BlobWriter("application/zip"), opts);
        await outer.add("contents.zip", new zip.BlobReader(innerBlob), { lastModDate: EPOCH });
      } else {
        outer = new zip.ZipWriter(new zip.BlobWriter("application/zip"), opts);
        for (const t of toZip) await outer.add(t.name, new zip.BlobReader(t.blob), { lastModDate: EPOCH });
      }
      const blob = await outer.close();

      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "odds-vault-" + new Date().toISOString().slice(0, 10) + ".zip";
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 30000);
      document.dispatchEvent(new CustomEvent("vault:success", { detail: { files: toZip.length } }));
      status.textContent = `Done. Downloaded ${a.download} (${fmt(blob.size)}). To open it, use 7-Zip, WinRAR or Keka; the built-in Windows extractor can't open AES zips.`;
    } catch (err) {
      status.textContent = "Something went wrong: " + (err.message || err);
    }
    rows.innerHTML = results.map(r => `<tr><td>${esc(r.name)}</td><td class="${r.cls}">${esc(r.msg)}</td><td class="found">${esc(r.size)}</td></tr>`).join("");
    $("report").classList.toggle("hidden", !results.length);
    validate();
  });

  validate();
})();
