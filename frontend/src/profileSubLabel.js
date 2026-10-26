export function formatProfileSttSubLabel(stt) {
  if (stt == null || stt === "") return "";
  return `STT ${String(stt).padStart(4, "0")}`;
}
