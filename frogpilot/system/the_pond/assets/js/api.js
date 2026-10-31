export async function fetchResponse(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const data = await response.json();
      message = data.error || data.message || message;
    } catch {}

    const error = new Error(message);
    error.status = response.status;
    throw error;
  }

  return response;
}

export async function fetchJson(url, options = {}) {
  const response = await fetchResponse(url, options);
  if (response.status === 204) {
    return null;
  }

  return response.json();
}

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.download = filename;
  link.href = url;

  document.body.append(link);
  link.click();
  link.remove();

  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
