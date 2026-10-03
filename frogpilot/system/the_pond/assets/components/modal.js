export function openDialog(title, body) {
  const dialog = document.createElement("dialog");
  dialog.className = "modal";
  dialog.setAttribute("aria-label", title);

  const heading = document.createElement("h2");
  heading.className = "modal-header";
  heading.textContent = title;

  const content = document.createElement("div");
  content.className = "dialog-content modal-body";
  if (typeof body === "function") {
    body(content);
  } else {
    content.append(body);
  }

  const close = document.createElement("button");
  close.type = "button";
  close.className = "dialog-close";
  close.setAttribute("aria-label", "Close dialog");
  close.textContent = "×";
  close.addEventListener("click", () => dialog.close());

  dialog.append(close, heading, content, document.getElementById("snackbar_wrapper"));
  dialog.addEventListener("click", event => {
    if (event.target !== dialog) {
      return;
    }

    const bounds = dialog.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) {
      dialog.close();
    }
  });

  dialog.addEventListener("close", () => {
    for (const media of dialog.querySelectorAll("video, audio")) {
      media.pause();
      media.removeAttribute("src");
      media.load();
    }

    const target = [...document.querySelectorAll("dialog[open]")].at(-1) || document.body;
    target.append(document.getElementById("snackbar_wrapper"));
    dialog.remove();
  }, { once: true });

  document.body.append(dialog);
  dialog.showModal();

  return dialog;
}

export function confirmDialog(title, message, options = {}) {
  const content = document.createElement("form");
  content.method = "dialog";

  const description = document.createElement("p");
  description.textContent = message;
  content.append(description);

  let input;
  if (options.inputValue !== undefined) {
    input = document.createElement("input");
    input.className = "modal-input";
    input.type = "text";
    input.value = options.inputValue;
    input.required = true;
    input.setAttribute("aria-label", title);
    content.append(input);
  }

  const actions = document.createElement("div");
  actions.className = "modal-actions";

  const cancel = document.createElement("button");
  cancel.className = "btn";
  cancel.textContent = "Cancel";
  cancel.type = "button";

  const confirm = document.createElement("button");
  confirm.className = "btn btn-primary";
  if (options.danger) {
    confirm.className = "btn btn-danger";
  }
  confirm.textContent = options.confirmText || "Confirm";
  confirm.value = "confirm";

  actions.append(cancel, confirm);
  content.append(actions);

  const dialog = openDialog(title, content);
  cancel.addEventListener("click", () => dialog.close());
  if (input) {
    input.focus();
    input.select();
  } else {
    cancel.focus();
  }

  return new Promise(resolve => {
    dialog.addEventListener("close", () => {
      if (dialog.returnValue !== "confirm") {
        resolve(null);
      } else if (input) {
        resolve(input.value.trim());
      } else {
        resolve(true);
      }
    }, { once: true });
  });
}
