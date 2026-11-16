const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface ProgrammeWatch {
  id: number;
  programme_slug: string;
  programme_name: string;
  programme_url: string;
  created_at: string;
  notified_at: string | null;
}

export const WATCH_UPDATES_COPY = "Get notified when a window becomes official, opens, changes its deadline or closes. Email updates join your daily digest when enabled.";
export const WATCH_LIMIT_COPY = "You can watch up to 50 programmes. Stop watching one to add another.";

async function watchRequest(path: string, accessToken: string, method = "GET", signal?: AbortSignal): Promise<Response> {
  const response = await fetch(`${API_URL}/calendar/${path}`, {
    method,
    headers: { Authorization: `Bearer ${accessToken}` },
    cache: "no-store",
    signal,
  });
  if (response.status === 401 || response.status === 403) {
    throw new Error("Your session has expired. Sign in again to manage programme watches.");
  }
  if (response.status === 409) throw new Error(WATCH_LIMIT_COPY);
  if (response.status === 404) throw new Error("This programme is no longer available to watch.");
  if (!response.ok) throw new Error("Couldn't update your programme watches. Please try again.");
  return response;
}

export async function getProgrammeWatches(accessToken: string, signal?: AbortSignal): Promise<ProgrammeWatch[]> {
  return (await watchRequest("watches", accessToken, "GET", signal)).json();
}

export async function addProgrammeWatch(slug: string, accessToken: string): Promise<ProgrammeWatch> {
  return (await watchRequest(`${encodeURIComponent(slug)}/watch`, accessToken, "PUT")).json();
}

export async function removeProgrammeWatch(slug: string, accessToken: string): Promise<void> {
  await watchRequest(`${encodeURIComponent(slug)}/watch`, accessToken, "DELETE");
}
