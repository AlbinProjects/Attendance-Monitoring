import api from "../services/api";

/**
 * Downloads a CSV export. A plain <a href="..."> can't carry the
 * Authorization header these endpoints require, so this fetches via the
 * authenticated axios instance as a blob and triggers the download
 * manually.
 */
export async function downloadCsv(path, params, fallbackFilename) {
  const res = await api.get(path, { params, responseType: "blob" });

  const disposition = res.headers?.["content-disposition"] || "";
  const match = disposition.match(/filename="?([^"]+)"?/);
  const filename = match?.[1] || fallbackFilename;

  const url = window.URL.createObjectURL(new Blob([res.data], { type: "text/csv" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}
