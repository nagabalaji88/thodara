import { useQuery } from "@tanstack/react-query";
import { FlaskConical } from "lucide-react";
import { api } from "./api";
import { useSyncExternalStore } from "react";
import { language, onLanguageChange, t } from "./i18n";

/** On a demo server (ADR-0016), every page says the data is fictional. */
export function DemoBanner() {
  const meta = useQuery({ queryKey: ["meta"], queryFn: () => api<{ demo: boolean }>("/api/v1/meta"), staleTime: Infinity, retry: 0 });
  useSyncExternalStore(onLanguageChange, language);
  if (!meta.data?.demo) return null;
  return <div className="demo-banner" role="note"><FlaskConical size={15} /><span><b>{t("Demo")}</b> · {t("Fictional company and data. Do not enter real customer, supplier or personal information; the demo is reset often.")}</span></div>;
}
