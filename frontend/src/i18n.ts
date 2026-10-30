/**
 * Screen language (slice G4, ADR-0012).
 *
 * English text is the key. t() returns the user's language, falling back to English, and fills
 * {0}, {1} … from args. tk() only marks text that is translated later (labels kept in maps), so
 * scripts/check-i18n.mjs can find every phrase. Numbers stay in 0-9 digits in both languages.
 */
import { TA } from "./ta";

export type Lang = "en" | "ta";
export const LANGUAGES: [Lang, string][] = [["en", "English"], ["ta", "தமிழ்"]];

let current: Lang = "en";

export function setLanguage(lang: Lang) {
  current = lang;
  document.documentElement.lang = lang;
}

export function language(): Lang {
  return current;
}

export function t(text: string | null | undefined, args?: (string | number | null | undefined)[]): string {
  if (text == null) return "";
  const template = current === "ta" ? (TA[text] ?? text) : text;
  return args ? template.replace(/\{(\d+)\}/g, (_, i: string) => String(args[Number(i)] ?? "")) : template;
}

/** Marks a phrase for translation where it is defined; translate it with t() where shown. */
export const tk = (text: string) => text;

/** Locale for dates and numbers: Tamil month names, 0-9 digits, Indian grouping. */
export const locale = () => (current === "ta" ? "ta-IN-u-nu-latn" : "en-IN");
