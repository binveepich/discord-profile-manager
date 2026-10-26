import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const editor = readFileSync(new URL("../src/dialogs/ProfileEditorModal.jsx", import.meta.url), "utf8");

test("profile editor exposes proxy endpoints without credential inputs or payload fields", () => {
  assert.doesNotMatch(editor, /proxyCredentialsDirty|proxy_password|form\.username|proxyPayload\.(?:username|password)/);
  assert.match(editor, /scheme: form\.scheme/);
  assert.match(editor, /host: form\.host/);
  assert.match(editor, /port: Number\(form\.port\)/);
  assert.doesNotMatch(editor, /http:\/\/[^\s"']*@[^\s"']*/);
});
