export function showSnackbar(message, level, timeout = 3500) {
  const wrapper = document.getElementById("snackbar_wrapper");
  while (wrapper.children.length >= 2) {
    wrapper.firstElementChild.remove();
  }

  const snackbar = document.createElement("div");
  snackbar.className = "snackbar show";
  snackbar.textContent = message;
  if (level === "error") {
    snackbar.style.backgroundColor = "#f44336";
    snackbar.setAttribute("role", "alert");
  } else if (level === "success") {
    snackbar.style.backgroundColor = "var(--success-bg)";
  }

  wrapper.append(snackbar);
  setTimeout(() => {
    snackbar.style.opacity = "0";
    setTimeout(() => snackbar.remove(), 500);
  }, timeout);
}
