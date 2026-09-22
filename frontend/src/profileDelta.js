export function compactProfileRows(rows) {
  return rows.map((row, index) => ({
    ...row,
    stt: String(index + 1).padStart(4, "0"),
  }));
}

export function applyProfileDeltaToRows(currentRows, updates = [], removedIds = []) {
  if (!Array.isArray(currentRows) || !Array.isArray(updates) || !updates.every((row) => (
    row && typeof row.profile_id === "string" && typeof row.name === "string"
  ))) return null;

  const removals = new Set((Array.isArray(removedIds) ? removedIds : []).map(String));
  const byId = new Map(currentRows.map((row) => [row.profile_id, row]));
  updates.forEach((row) => byId.set(row.profile_id, row));
  removals.forEach((profileId) => byId.delete(profileId));
  return compactProfileRows([...byId.values()]);
}
