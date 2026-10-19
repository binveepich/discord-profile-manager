import assert from "node:assert/strict";
import test from "node:test";
import {
  importResultNotificationType,
  launchBatchOutcome,
  launchPollFailureState,
} from "../src/jobOutcome.js";

test("partial batch launch is presented as a failure with counts", () => {
  const outcome = launchBatchOutcome({
    status: "completed",
    result: {
      requested: 3,
      completed: 3,
      succeeded: 2,
      failed: 1,
      results: [{ status: "launched" }, { status: "error" }, { status: "launched" }],
    },
  });

  assert.equal(outcome.type, "error");
  assert.equal(outcome.label, "Có lỗi");
  assert.match(outcome.message, /2\/3/);
  assert.match(outcome.message, /1 hồ sơ thất bại/);
});

test("fully handled batch launch is presented as complete", () => {
  const outcome = launchBatchOutcome({
    status: "completed",
    result: { requested: 2, completed: 2, succeeded: 2, failed: 0 },
  });

  assert.equal(outcome.type, "success");
  assert.equal(outcome.label, "Đã hoàn tất");
});

test("import with failed rows uses an error notification", () => {
  assert.equal(importResultNotificationType({ created: 2, failed: 1 }), "error");
  assert.equal(importResultNotificationType({ created: 2, failed: 0 }), "success");
});

test("a failed status poll terminates only the matching launch job", () => {
  const current = { jobId: "current", status: "running" };
  assert.deepEqual(launchPollFailureState(current, "current"), {
    jobId: "current",
    status: "failed",
  });
  assert.equal(launchPollFailureState(current, "stale"), current);
});
