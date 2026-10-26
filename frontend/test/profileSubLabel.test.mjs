import assert from "node:assert/strict";
import test from "node:test";
import { formatProfileSttSubLabel } from "../src/profileSubLabel.js";

test("formats the API STT value as the profile sub-label", () => {
  assert.equal(formatProfileSttSubLabel("0001"), "STT 0001");
  assert.equal(formatProfileSttSubLabel(48), "STT 0048");
  assert.equal(formatProfileSttSubLabel("10000"), "STT 10000");
  assert.equal(formatProfileSttSubLabel(null), "");
});
