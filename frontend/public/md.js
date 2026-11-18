/* md.js — 极简安全 Markdown 渲染器（P2 Task 6）。
 *
 * 安全模型（Review Focus #5）：先把整段输入做 HTML 转义（& < > " '），
 * 之后的一切解析都在"已转义文本"上进行，最终经 innerHTML 组装——
 * 因为原始输入里的标签早已变成 &lt; 实体，浏览器不可能把它当标签执行，
 * 所以不产生任何来自用户/LLM 输入的裸 HTML 标签。
 *
 * 支持子集：# 标题、**粗***斜* 行内强调、`code` 行内代码、``` 代码围栏、
 * 无序/有序列表、Markdown 表格（含对齐行；单元格内 LLM 的转义竖线
 * "\\|" 会在渲染前还原成显示用的 "|"，见 splitRow）、[文本](http链接)。
 * 不支持的语法一律按普通段落文本展示，绝不放行原始 HTML。
 *
 * 用法：mdRender(src) → 一个 <div class="md"> 元素（appendChild 即可）。
 */
"use strict";

(() => {
  /* 先整体转义：这是本渲染器安全性的根。 */
  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  /* 行内代码占位（先摘出，其它行内规则不碰其内容，最后还原为 <code>） */
  const codeSpans = [];
  function stashCodeSpan(match) {
    codeSpans.push(match);
    return `\u0000${codeSpans.length - 1}\u0000`;
  }

  /* 行内格式：code → 链接 → 粗体 → 斜体。
   * 输入已是转义文本，产出的 <strong>/<em>/<a> 是我们自己写的标签。 */
  function inline(text) {
    let out = text.replace(/`([^`\n]+)`/g, stashCodeSpan);
    // 链接 [文本](url)：仅放行 http(s)，其余按原样展示（防止 javascript: 等）
    out = out.replace(
      /\[([^\][\n]+)\]\(([^()\s]+)\)/g,
      (match, label, url) =>
        /^https?:\/\//i.test(url)
          ? `<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`
          : match
    );
    out = out.replace(/\*\*([^\n*]+)\*\*/g, "<strong>$1</strong>");
    out = out.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
    // 下划线斜体要求两侧是词边界，避免把 snake_case / chat_summary 误斜体化
    out = out.replace(
      /(^|[^\w\\])_([^_\n]+)_(?=$|[^\w])/g,
      "$1<em>$2</em>"
    );
    out = out.replace(
      /\u0000(\d+)\u0000/g,
      (_, index) => `<code>${codeSpans[Number(index)]}</code>`
    );
    return out;
  }

  /* 表格行 → 单元格：按"未转义的 |"切分，再把 \| 还原为显示用竖线
   * （LLM 在表格单元格内写 [P1\|3]，切分时不能把它当列分隔）。 */
  function splitRow(line) {
    let body = line.trim();
    if (body.startsWith("|")) body = body.slice(1);
    if (body.endsWith("|") && !body.endsWith("\\|")) body = body.slice(0, -1);
    const cells = [];
    let current = "";
    for (let i = 0; i < body.length; i += 1) {
      const ch = body[i];
      if (ch === "\\" && body[i + 1] === "|") {
        current += "|";
        i += 1;
      } else if (ch === "|") {
        cells.push(current.trim());
        current = "";
      } else {
        current += ch;
      }
    }
    cells.push(current.trim());
    return cells;
  }

  /* 对齐行：| :--- | :---: | ---: | → ["left","center","right",…]；非对齐行 → null */
  function parseAlign(line) {
    if (!line.includes("-") || !line.includes("|")) return null;
    const cells = splitRow(line);
    if (cells.length < 2) return null;
    const aligns = [];
    for (const cell of cells) {
      const m = /^\s*(:?)(-{1,})(:?)\s*$/.exec(cell);
      if (!m) return null;
      aligns.push(
        m[1] && m[3] ? "center" : m[3] ? "right" : "left"
      );
    }
    return aligns;
  }

  /* 块级解析：逐行扫描 → HTML 片段数组（片段内容已全部转义并 inline） */
  function blocksToHtml(lines) {
    const html = [];
    let i = 0;

    while (i < lines.length) {
      const line = lines[i];

      if (!line.trim()) {
        i += 1;
        continue;
      }

      /* 代码围栏 ``` */
      if (/^\s*```/.test(line)) {
        const fence = lines
          .slice(i + 1)
          .findIndex((rest) => /^\s*```/.test(rest));
        const end = fence === -1 ? lines.length : i + 1 + fence;
        html.push(
          `<pre><code>${lines.slice(i + 1, end).join("\n")}</code></pre>`
        );
        i = end + 1;
        continue;
      }

      /* 标题 # */
      const heading = /^(#{1,6})\s+(.*)$/.exec(line);
      if (heading) {
        const level = heading[1].length;
        html.push(`<h${level}>${inline(heading[2].trim())}</h${level}>`);
        i += 1;
        continue;
      }

      /* 表格：含 | 的行 + 下一行是对齐行 */
      if (line.includes("|") && i + 1 < lines.length) {
        const aligns = parseAlign(lines[i + 1]);
        if (aligns) {
          const head = splitRow(line);
          html.push("<table><thead><tr>");
          head.forEach((cell, c) => {
            html.push(
              `<th style="text-align:${aligns[c] || "left"}">${inline(cell)}</th>`
            );
          });
          html.push("</tr></thead><tbody>");
          i += 2;
          while (i < lines.length && lines[i].includes("|") && lines[i].trim()) {
            const row = splitRow(lines[i]);
            html.push("<tr>");
            head.forEach((_, c) => {
              html.push(
                `<td style="text-align:${aligns[c] || "left"}">${inline(
                  row[c] || ""
                )}</td>`
              );
            });
            html.push("</tr>");
            i += 1;
          }
          html.push("</tbody></table>");
          continue;
        }
      }

      /* 列表：连续同类型项 */
      const ul = /^\s*[-*]\s+/;
      const ol = /^\s*\d+[.)]\s+/;
      if (ul.test(line)) {
        html.push("<ul>");
        while (i < lines.length && ul.test(lines[i])) {
          html.push(`<li>${inline(lines[i].replace(ul, "").trim())}</li>`);
          i += 1;
        }
        html.push("</ul>");
        continue;
      }
      if (ol.test(line)) {
        html.push("<ol>");
        while (i < lines.length && ol.test(lines[i])) {
          html.push(`<li>${inline(lines[i].replace(ol, "").trim())}</li>`);
          i += 1;
        }
        html.push("</ol>");
        continue;
      }

      /* 段落：直到空行或下一个块级开头，内部换行转 <br> */
      const paragraph = [line];
      i += 1;
      while (
        i < lines.length &&
        lines[i].trim() &&
        !/^\s*```/.test(lines[i]) &&
        !/^(#{1,6})\s+/.test(lines[i]) &&
        !ul.test(lines[i]) &&
        !ol.test(lines[i]) &&
        !(lines[i].includes("|") && i + 1 < lines.length && parseAlign(lines[i + 1]))
      ) {
        paragraph.push(lines[i]);
        i += 1;
      }
      html.push(`<p>${paragraph.map(inline).join("<br>")}</p>`);
    }
    return html;
  }

  function mdRender(src) {
    codeSpans.length = 0;
    const escaped = escapeHtml(src == null ? "" : src);
    const container = document.createElement("div");
    container.className = "md";
    container.innerHTML = blocksToHtml(escaped.split(/\r?\n/)).join("\n");
    return container;
  }

  window.mdRender = mdRender;
})();
