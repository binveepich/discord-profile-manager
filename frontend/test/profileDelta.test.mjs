import assert from "node:assert/strict";
import test from "node:test";
import { applyProfileDeltaToRows } from "../src/profileDelta.js";

function rows(count) {
  return Array.from({ length: count }, (_, index) => ({
    profile_id: `profile_${String(index + 1).padStart(4, "0")}`,
    stt: String(index + 1).padStart(4, "0"),
    name: `Profile ${index + 1}`,
  }));
}

test("single delete compacts STT from the first remaining row", () => {
  const result = applyProfileDeltaToRows(rows(10), [], ["profile_0001"]);
  assert.deepEqual(result.map((row) => row.stt), [
    "0001", "0002", "0003", "0004", "0005",
    "0006", "0007", "0008", "0009",
  ]);
});

test("middle delete compacts the tail without changing stable IDs", () => {
  const original = rows(100);
  const result = applyProfileDeltaToRows(original, [], ["profile_0067"]);
  assert.equal(result.length, 99);
  assert.equal(result[65].stt, "0066");
  assert.equal(result[66].stt, "0067");
  assert.equal(result[66].profile_id, "profile_0068");
  assert.equal(result[98].stt, "0099");
});

test("deleting the last profile leaves no STT gap", () => {
  const result = applyProfileDeltaToRows(rows(3), [], ["profile_0003"]);
  assert.deepEqual(result.map((row) => row.stt), ["0001", "0002"]);
});

test("bulk delete renumbers once across all successful IDs", () => {
  const result = applyProfileDeltaToRows(rows(100), [], [
    "profile_0010", "profile_0020", "profile_0030",
  ]);
  assert.equal(result.length, 97);
  assert.equal(result[9].stt, "0010");
  assert.equal(result[9].profile_id, "profile_0011");
  assert.equal(result[96].stt, "0097");
});

test("partial bulk delete removes only successful IDs", () => {
  const result = applyProfileDeltaToRows(rows(3), [], ["profile_0001", "profile_0003"]);
  assert.deepEqual(result.map((row) => row.profile_id), ["profile_0002"]);
  assert.deepEqual(result.map((row) => row.stt), ["0001"]);
});

test("compaction never changes surviving profile IDs", () => {
  const originalIds = rows(5).map((row) => row.profile_id);
  const result = applyProfileDeltaToRows(rows(5), [], ["profile_0002"]);
  assert.deepEqual(result.map((row) => row.profile_id), [
    "profile_0001", "profile_0003", "profile_0004", "profile_0005",
  ]);
  assert.equal(originalIds[2], result[1].profile_id);
});
