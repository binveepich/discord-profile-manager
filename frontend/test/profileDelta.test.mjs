import assert from "node:assert/strict";
import test from "node:test";
import { applyProfileDeltaToRows, applyProfileOrder, deltaMovesRows } from "../src/profileDelta.js";

function rows(count) {
  return Array.from({ length: count }, (_, index) => ({
    profile_id: `profile_${String(index + 1).padStart(4, "0")}`,
    stt: String(index + 1).padStart(4, "0"),
    name: `Profile ${index + 1}`,
  }));
}

function idsFrom(count, skip = []) {
  return rows(count).map((row) => row.profile_id).filter((id) => !skip.includes(id));
}

// The order display_order returns: the given IDs numbered 1..N in that order.
function order(...profileIds) {
  return profileIds.map((profileId, index) => ({ profile_id: profileId, stt: String(index + 1).padStart(4, "0") }));
}

test("a delete removes the row and keeps the STT it had until the backend order arrives", () => {
  const result = applyProfileDeltaToRows(rows(10), [], ["profile_0001"]);
  assert.equal(result.length, 9);
  assert.equal(result[0].profile_id, "profile_0002");
  assert.equal(result[0].stt, "0002");
});

test("the backend order renumbers STT from the first remaining row", () => {
  const remaining = applyProfileDeltaToRows(rows(10), [], ["profile_0001"]);
  const numbered = applyProfileOrder(remaining, order(...idsFrom(10, ["profile_0001"])));
  assert.deepEqual(numbered.map((row) => row.stt), [
    "0001", "0002", "0003", "0004", "0005",
    "0006", "0007", "0008", "0009",
  ]);
});

test("a middle delete renumbers the tail from the backend order and never changes IDs", () => {
  const remaining = applyProfileDeltaToRows(rows(100), [], ["profile_0067"]);
  assert.equal(remaining.length, 99);
  const numbered = applyProfileOrder(remaining, order(...idsFrom(100, ["profile_0067"])));
  assert.equal(numbered[65].stt, "0066");
  assert.equal(numbered[66].stt, "0067");
  assert.equal(numbered[66].profile_id, "profile_0068");
  assert.equal(numbered[98].stt, "0099");
});

test("bulk delete removes every successful ID and the backend order leaves no gap", () => {
  const remaining = applyProfileDeltaToRows(rows(100), [], [
    "profile_0010", "profile_0020", "profile_0030",
  ]);
  assert.equal(remaining.length, 97);
  const numbered = applyProfileOrder(remaining, order(...idsFrom(100, ["profile_0010", "profile_0020", "profile_0030"])));
  assert.equal(numbered[9].stt, "0010");
  assert.equal(numbered[9].profile_id, "profile_0011");
  assert.equal(numbered[96].stt, "0097");
});

test("partial bulk delete removes only successful IDs", () => {
  const result = applyProfileDeltaToRows(rows(3), [], ["profile_0001", "profile_0003"]);
  assert.deepEqual(result.map((row) => row.profile_id), ["profile_0002"]);
});

test("a delete never changes surviving profile IDs", () => {
  const result = applyProfileDeltaToRows(rows(5), [], ["profile_0002"]);
  assert.deepEqual(result.map((row) => row.profile_id), [
    "profile_0001", "profile_0003", "profile_0004", "profile_0005",
  ]);
});

test("an appended row keeps the STT the backend sent with it", () => {
  const result = applyProfileDeltaToRows(rows(2), [{ profile_id: "profile_0003", stt: "0003", name: "x" }]);
  assert.deepEqual(result.map((row) => [row.profile_id, row.stt]), [
    ["profile_0001", "0001"],
    ["profile_0002", "0002"],
    ["profile_0003", "0003"],
  ]);
});

test("applyProfileOrder keeps the table order and copies only the STT", () => {
  const tableOrder = [
    { profile_id: "profile_0003", stt: "0003", name: "0001 | c" },
    { profile_id: "profile_0001", stt: "0001", name: "Profile 2" },
    { profile_id: "profile_0002", stt: "0002", name: "b" },
  ];
  const result = applyProfileOrder(tableOrder, order("profile_0001", "profile_0003", "profile_0002"));
  assert.deepEqual(result.map((row) => [row.profile_id, row.stt, row.name]), [
    ["profile_0003", "0002", "0001 | c"],
    ["profile_0001", "0001", "Profile 2"],
    ["profile_0002", "0003", "b"],
  ]);
});

test("a row missing from the backend order keeps the STT it has", () => {
  const result = applyProfileOrder(rows(2), order("profile_0002"));
  assert.deepEqual(result.map((row) => [row.profile_id, row.stt]), [
    ["profile_0001", "0001"],
    ["profile_0002", "0001"],
  ]);
});

test("a delta moves rows only when it adds, renames or removes a profile", () => {
  const known = rows(2);
  assert.equal(deltaMovesRows(known, [{ profile_id: "profile_0003", name: "New" }]), true);
  assert.equal(deltaMovesRows(known, [{ profile_id: "profile_0001", name: "Renamed" }]), true);
  assert.equal(deltaMovesRows(known, [], ["profile_0002"]), true);
  assert.equal(deltaMovesRows(known, [{ profile_id: "profile_0001", name: "Profile 1", status: "Running" }]), false);
});
