(() => {
  const sidebar = document.querySelector("#sidebar");
  const menuButton = document.querySelector(".menu-button");
  document.querySelector("#role-select")?.addEventListener("change", (event) => {
    event.currentTarget.form?.requestSubmit();
  });

  if (sidebar && menuButton) {
    menuButton.addEventListener("click", () => {
      const isOpen = sidebar.classList.toggle("is-open");
      menuButton.setAttribute("aria-expanded", String(isOpen));
      menuButton.setAttribute("aria-label", isOpen ? "Close navigation" : "Open navigation");
    });

    document.addEventListener("click", (event) => {
      if (
        sidebar.classList.contains("is-open") &&
        !sidebar.contains(event.target) &&
        !menuButton.contains(event.target)
      ) {
        sidebar.classList.remove("is-open");
        menuButton.setAttribute("aria-expanded", "false");
        menuButton.setAttribute("aria-label", "Open navigation");
      }
    });
  }

  const search = document.querySelector("[data-report-search]");
  const statusFilter = document.querySelector("[data-status-filter]");
  const placeFilter = document.querySelector("[data-place-filter]");
  const densityToggle = document.querySelector("[data-density-toggle]");
  const rows = [...document.querySelectorAll("[data-report-row]")];
  const emptyFilter = document.querySelector("[data-filter-empty]");

  const filterReports = () => {
    const query = search?.value.trim().toLocaleLowerCase() ?? "";
    const status = statusFilter?.value ?? "";
    const place = placeFilter?.value ?? "";
    let visible = 0;
    rows.forEach((row) => {
      const [placeType, placeValue] = place.split(":");
      const matches =
        (!query || row.dataset.search.includes(query)) &&
        (!status || row.dataset.status === status) &&
        (!place ||
          (placeType === "category" && row.dataset.category === placeValue) ||
          (placeType === "location" && row.dataset.location === placeValue));
      row.hidden = !matches;
      if (matches) visible += 1;
    });
    if (emptyFilter) emptyFilter.hidden = visible !== 0;
  };

  search?.addEventListener("input", filterReports);
  statusFilter?.addEventListener("change", filterReports);
  placeFilter?.addEventListener("change", filterReports);

  densityToggle?.addEventListener("click", () => {
    const isCompact = densityToggle.getAttribute("aria-pressed") !== "true";
    document.querySelector("[data-report-list]")?.classList.toggle("is-compact", isCompact);
    densityToggle.setAttribute("aria-pressed", String(isCompact));
    densityToggle.textContent = isCompact ? "Comfortable list" : "Compact list";
  });

  const description = document.querySelector("#description");
  const charCount = document.querySelector("[data-char-count]");
  const updateCount = () => {
    if (description && charCount) charCount.textContent = `${description.value.length} / 3,000`;
  };
  description?.addEventListener("input", updateCount);
  updateCount();

  const fileInput = document.querySelector("#photo");
  const fileName = document.querySelector("[data-file-name]");
  const uploadZone = document.querySelector(".upload-zone");
  const showFileName = (file) => {
    if (fileName && file) fileName.textContent = file.name;
  };
  fileInput?.addEventListener("change", () => showFileName(fileInput.files?.[0]));

  if (uploadZone && fileInput) {
    ["dragenter", "dragover"].forEach((eventName) => {
      uploadZone.addEventListener(eventName, (event) => {
        event.preventDefault();
        uploadZone.classList.add("is-dragging");
      });
    });
    ["dragleave", "drop"].forEach((eventName) => {
      uploadZone.addEventListener(eventName, (event) => {
        event.preventDefault();
        uploadZone.classList.remove("is-dragging");
      });
    });
    uploadZone.addEventListener("drop", (event) => {
      const [file] = event.dataTransfer?.files ?? [];
      if (!file) return;
      const transfer = new DataTransfer();
      transfer.items.add(file);
      fileInput.files = transfer.files;
      showFileName(file);
    });
  }

  document.querySelectorAll(".flash-close").forEach((button) => {
    button.addEventListener("click", () => button.closest(".flash")?.remove());
  });
})();
