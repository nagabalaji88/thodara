// Every phrase shown on screen must have a Tamil translation (slice G4, ADR-0012).
// Collects the English keys passed to t() and tk() and compares them with src/ta.ts.
// Usage: node scripts/check-i18n.mjs [--missing]   (--missing prints untranslated keys as JSON)
import { parseSync } from "rolldown/experimental";
import fs from "node:fs";

const keys = new Set();
const dynamic = [];
for (const file of fs.readdirSync("src").filter((f) => /\.tsx?$/.test(f) && f !== "ta.ts")) {
  const src = fs.readFileSync(`src/${file}`, "utf8");
  const { program, errors } = parseSync(file, src, { lang: "tsx" });
  if (errors.length) throw new Error(`${file}: ${errors[0].message}`);
  const literals = (e) => {
    if (!e) return [];
    if (e.type === "Literal" && typeof e.value === "string") return [e.value];
    if (e.type === "ConditionalExpression") return [...literals(e.consequent), ...literals(e.alternate)];
    if (e.type === "LogicalExpression" && e.operator === "??") return literals(e.right);
    return null;
  };
  const visit = (n) => {
    if (!n || typeof n !== "object") return;
    if (Array.isArray(n)) return n.forEach(visit);
    if (n.type === "CallExpression" && (n.callee?.name === "t" || n.callee?.name === "tk") && n.arguments.length) {
      const found = literals(n.arguments[0]);
      if (found) found.filter((k) => /[A-Za-z]/.test(k)).forEach((k) => keys.add(k));
      else if (n.callee.name === "tk") dynamic.push(`${file}: tk() needs a literal`);
    }
    for (const k in n) if (k !== "type") visit(n[k]);
  };
  visit(program);
}
const ta = fs.readFileSync("src/ta.ts", "utf8");
const translated = new Set([...ta.matchAll(/^\s*("(?:[^"\\]|\\.)*"):/gm)].map((m) => JSON.parse(m[1])));
const missing = [...keys].filter((k) => !translated.has(k)).sort();
const unused = [...translated].filter((k) => !keys.has(k)).sort();
if (process.argv.includes("--missing")) { console.log(JSON.stringify(missing, null, 1)); process.exit(0); }
console.log(`${keys.size} phrases, ${translated.size} translated, ${missing.length} missing, ${unused.length} unused`);
if (dynamic.length) console.log(dynamic.join("\n"));
if (missing.length) console.log("Missing Tamil:\n  " + missing.slice(0, 40).join("\n  "));
if (unused.length) console.log("Unused Tamil entries:\n  " + unused.slice(0, 40).join("\n  "));
process.exit(missing.length || dynamic.length ? 1 : 0);
