// A delta only merges rows. STT is the backend's table position, so it is never renumbered here: a change that moves
// rows is followed by applyProfileOrder with the order from the backend.
export function applyProfileDeltaToRows(currentRows, updates = [], removedIds = []) {
  if (!Array.isArray(currentRows) || !Array.isArray(updates) || !updates.every((row) => (
    row && typeof row.profile_id === "string" && typeof row.name === "string"
  ))) return null;

  const removals = new Set((Array.isArray(removedIds) ? removedIds : []).map(String));
  const byId = new Map(currentRows.map((row) => [row.profile_id, row]));
  updates.forEach((row) => byId.set(row.profile_id, row));
  removals.forEach((profileId) => byId.delete(profileId));
  return [...byId.values()];
}

// Copies the backend's STT onto the rows it names. A row missing from the order keeps the STT it has.
export function applyProfileOrder(rows, order) {
  const sttById = new Map(order.map((item) => [item.profile_id, item.stt]));
  return rows.map((row) => (sttById.has(row.profile_id) ? { ...row, stt: sttById.get(row.profile_id) } : row));
}

// A delta moves rows when it adds a profile, renames one or removes one. Launches and edits to other fields do not.
export function deltaMovesRows(knownRows, updates = [], removedIds = []) {
  const knownNames = new Map(knownRows.map((row) => [row.profile_id, row.name]));
  const removals = Array.isArray(removedIds) ? removedIds : [];
  return removals.length > 0 || updates.some((row) => knownNames.get(row.profile_id) !== row.name);
}
