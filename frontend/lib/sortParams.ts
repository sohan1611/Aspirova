export type UiSort = "newest" | "deadline" | "pay";

interface SortParamReader {
  get(name: string): string | null;
}

export function sortApiParams(uiSort: UiSort, forStudents: boolean): {
  sort: "student" | "recent" | "deadline" | "pay";
  students?: boolean;
} {
  if (uiSort === "newest") {
    return { sort: forStudents ? "student" : "recent" };
  }
  return forStudents ? { sort: uiSort, students: true } : { sort: uiSort };
}

export function parseSortParams(params: SortParamReader) {
  const value = params.get("sort");
  const uiSort: UiSort = value === "deadline" || value === "pay" ? value : "newest";
  const forStudents = params.get("students") !== "0";
  return { uiSort, forStudents, ...sortApiParams(uiSort, forStudents) };
}

export function writeSortParams(params: URLSearchParams, uiSort: UiSort, forStudents: boolean) {
  if (uiSort === "newest") params.delete("sort");
  else params.set("sort", uiSort);
  if (forStudents) params.delete("students");
  else params.set("students", "0");
}
