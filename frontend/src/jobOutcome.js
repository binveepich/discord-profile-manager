export function launchBatchOutcome(state = {}) {
  const result = state.result || {};
  const results = Array.isArray(result.results) ? result.results : [];
  const failed = Number.isFinite(Number(result.failed))
    ? Math.max(0, Number(result.failed))
    : results.filter((item) => item?.status === "error").length;
  const requested = Number(result.requested ?? result.total ?? state.progress?.total ?? 0);
  const completed = Number(
    result.completed ?? (results.length || state.progress?.completed) ?? 0,
  );
  const succeeded = Number(result.succeeded ?? Math.max(0, completed - failed));

  if (state.status === "completed" && failed > 0) {
    return {
      label: "Có lỗi",
      message: `Đã xử lý ${succeeded}/${requested} hồ sơ; ${failed} hồ sơ thất bại.`,
      type: "error",
    };
  }
  if (state.status === "completed") {
    return {
      label: "Đã hoàn tất",
      message: "Đã xử lý xong các hồ sơ đã chọn.",
      type: "success",
    };
  }
  if (state.status === "cancelled") {
    return {
      label: failed > 0 ? "Đã hủy · có lỗi" : "Đã hủy",
      message: `Đã hủy thao tác mở (${completed}/${requested}).`,
      type: "error",
    };
  }
  return { label: "Có lỗi", message: "Không thể hoàn tất thao tác mở hồ sơ.", type: "error" };
}

export function importResultNotificationType(result) {
  return Number(result?.failed || 0) > 0 ? "error" : "success";
}

export function launchPollFailureState(current, jobId) {
  return current?.jobId === jobId ? { ...current, status: "failed" } : current;
}
