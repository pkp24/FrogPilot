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

export async function fetchEvents(url, onData, options = {}) {
  const response = await fetchResponse(url, options);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const messages = buffer.split(/\r?\n\r?\n/);
      buffer = messages.pop();

      for (const message of messages) {
        const data = message.split(/\r?\n/).filter(line => line.startsWith("data:")).map(line => line.slice(5).trimStart()).join("\n");
        if (data) {
          onData(JSON.parse(data));
        }
      }

      if (done) {
        break;
      }
    }
  } finally {
    try {
      await reader.cancel();
    } finally {
      reader.releaseLock();
    }
  }
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
