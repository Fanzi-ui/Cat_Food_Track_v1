const feedList = document.getElementById("feed-list");
const feedStatus = document.getElementById("feed-status");
const petId = document.body.dataset.petId;
const petName = document.body.dataset.petName;
const logNowBtn = document.getElementById("log-now-btn");
const useLastAmountBtn = document.getElementById("use-last-amount-btn");
const lastAmountDisplay = document.getElementById("last-amount-display");
const amountInput = document.getElementById("amount_grams");
const fedAtInput = document.getElementById("fed_at");
const dietInput = document.getElementById("diet_type");
const lastAmountKey = `lastAmount-${petId}`;
const inventoryForm = document.getElementById("inventory-form");
const inventoryFood = document.getElementById("inventory-food");
const inventorySachetCount = document.getElementById("inventory-sachet-count");
const inventoryTotalGrams = document.getElementById("inventory-total-grams");
const inventoryStatus = document.getElementById("inventory-status");
const inventoryRemaining = document.getElementById("inventory-remaining");
const inventorySachets = document.getElementById("inventory-sachets");
const inventoryUpdated = document.getElementById("inventory-updated");
const weightList = document.getElementById("weight-list");
const weightForm = document.getElementById("weight-form");
const weightRecordedAt = document.getElementById("weight-recorded-at");
const weightInput = document.getElementById("weight-kg");
const weightStatus = document.getElementById("weight-status");
const reportStart = document.getElementById("report-start");
const reportEnd = document.getElementById("report-end");
const reportLink = document.getElementById("report-link");
const SACHET_SIZE_GRAMS = 85;

function setFeedStatus(message, isError = false) {
  if (!feedStatus) {
    return;
  }
  feedStatus.textContent = message;
  feedStatus.classList.remove("success", "error");
  if (message) {
    feedStatus.classList.add(isError ? "error" : "success");
  }
  feedStatus.style.display = message ? "block" : "none";
}

function setInventoryStatus(message, isError = false) {
  if (!inventoryStatus) {
    return;
  }
  inventoryStatus.textContent = message;
  inventoryStatus.classList.remove("success", "error");
  if (message) {
    inventoryStatus.classList.add(isError ? "error" : "success");
  }
  inventoryStatus.style.display = message ? "block" : "none";
}

function setWeightStatus(message, isError = false) {
  if (!weightStatus) {
    return;
  }
  weightStatus.textContent = message;
  weightStatus.classList.remove("success", "error");
  if (message) {
    weightStatus.classList.add(isError ? "error" : "success");
  }
  weightStatus.style.display = message ? "block" : "none";
}

function getCookie(name) {
  const cookie = document.cookie
    .split("; ")
    .find(row => row.startsWith(`${name}=`));
  return cookie ? cookie.split("=").slice(1).join("=") : "";
}

function headers() {
  const headerMap = { "Content-Type": "application/json" };
  const csrfToken = getCookie("csrf");
  if (csrfToken) {
    headerMap["X-CSRF-Token"] = csrfToken;
  }
  return headerMap;
}

function setFedAtNow() {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
  fedAtInput.value = local.toISOString().slice(0, 16);
}

function setWeightRecordedAtNow() {
  if (!weightRecordedAt) {
    return;
  }
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60000);
  weightRecordedAt.value = local.toISOString().slice(0, 16);
}

function updateInventoryTotal() {
  if (!inventorySachetCount || !inventoryTotalGrams) {
    return;
  }
  const count = parseInt(inventorySachetCount.value || "0", 10);
  const total = Math.max(0, count) * SACHET_SIZE_GRAMS;
  inventoryTotalGrams.textContent = `${total}g`;
}

function loadLastAmount() {
  const stored = localStorage.getItem(lastAmountKey);
  if (stored) {
    lastAmountDisplay.textContent = stored;
    amountInput.value = stored;
  }
}

async function loadFeedings() {
  const response = await fetch(`/pets/${petId}/feedings?limit=20`, {
    headers: headers(),
    credentials: "include",
  });
  if (!response.ok) {
    if (response.status === 401) {
      feedList.innerHTML = "<li class='feed-item'>Sign in to view feedings.</li>";
      return;
    }
    feedList.innerHTML = "<li class='feed-item'>Unable to load feedings.</li>";
    return;
  }
  const data = await response.json();
  if (!data.length) {
    feedList.innerHTML = "<li class='feed-item'>No feedings yet.</li>";
    return;
  }
  feedList.innerHTML = "";
  data.forEach(item => {
    const li = document.createElement("li");
    li.className = "feed-item";
    const when = new Date(item.fed_at).toLocaleString();
    const diet = item.diet_type ? " - " + item.diet_type : "";
    li.textContent = when + " - " + item.amount_grams + "g" + diet;
    feedList.appendChild(li);
  });
}

async function loadInventory() {
  if (!inventoryRemaining || !inventorySachets || !inventoryFood) {
    return;
  }
  const response = await fetch(`/pets/${petId}/inventory`, {
    headers: headers(),
    credentials: "include",
  });
  if (!response.ok) {
    return;
  }
  const data = await response.json();
  inventoryRemaining.textContent = data.remaining_grams;
  inventorySachets.textContent = data.sachet_count;
  if (inventoryFood && data.food_name) {
    inventoryFood.value = data.food_name;
  }
  if (inventorySachetCount) {
    inventorySachetCount.value = data.sachet_count;
  }
  if (inventoryUpdated) {
    inventoryUpdated.textContent = data.updated_at
      ? `Last updated: ${new Date(data.updated_at).toLocaleString()}`
      : "Last updated: --";
  }
  updateInventoryTotal();
}

async function submitInventory() {
  setInventoryStatus("Saving...");
  const payload = {
    food_name: inventoryFood.value.trim(),
    sachet_count: parseInt(inventorySachetCount.value || "0", 10),
  };
  const response = await fetch(`/pets/${petId}/inventory`, {
    method: "PUT",
    headers: headers(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  if (response.ok) {
    setInventoryStatus("Inventory saved.");
    await loadInventory();
  } else {
    const error = await response.json();
    setInventoryStatus(error.detail || "Failed to save inventory.", true);
  }
}

async function loadWeights() {
  if (!weightList) {
    return;
  }
  const response = await fetch(`/pets/${petId}/weights?limit=20`, {
    headers: headers(),
    credentials: "include",
  });
  if (!response.ok) {
    weightList.innerHTML = "<li class='feed-item'>Unable to load weights.</li>";
    return;
  }
  const data = await response.json();
  if (!data.length) {
    weightList.innerHTML = "<li class='feed-item'>No weights yet.</li>";
    return;
  }
  weightList.innerHTML = "";
  data.forEach(item => {
    const li = document.createElement("li");
    li.className = "feed-item";
    const when = new Date(item.recorded_at).toLocaleString();
    li.textContent = `${when} - ${item.weight_kg}kg`;
    weightList.appendChild(li);
  });
}

async function submitWeight() {
  setWeightStatus("Saving...");
  const recordedAt = weightRecordedAt.value
    ? new Date(weightRecordedAt.value).toISOString()
    : null;
  const payload = {
    weight_kg: parseFloat(weightInput.value),
    recorded_at: recordedAt,
  };
  const response = await fetch(`/pets/${petId}/weights`, {
    method: "POST",
    headers: headers(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  if (response.ok) {
    setWeightStatus("Weight saved.");
    weightInput.value = "";
    setWeightRecordedAtNow();
    await loadWeights();
  } else {
    const error = await response.json();
    setWeightStatus(error.detail || "Failed to save weight.", true);
  }
}

function updateReportLink() {
  if (!reportLink) {
    return;
  }
  const start = reportStart && reportStart.value ? reportStart.value : "";
  const end = reportEnd && reportEnd.value ? reportEnd.value : "";
  const params = [];
  if (start) params.push(`start=${start}`);
  if (end) params.push(`end=${end}`);
  const suffix = params.length ? `?${params.join("&")}` : "";
  reportLink.href = `/pets/${petId}/report.pdf${suffix}`;
}

function setReportDates() {
  if (!reportStart || !reportEnd) {
    return;
  }
  const today = new Date();
  const end = new Date(today.getTime() - today.getTimezoneOffset() * 60000);
  const start = new Date(end);
  start.setDate(start.getDate() - 6);
  reportEnd.value = end.toISOString().slice(0, 10);
  reportStart.value = start.toISOString().slice(0, 10);
}

async function submitFeeding() {
  setFeedStatus("Saving...");
  const payload = {
    fed_at: new Date(fedAtInput.value).toISOString(),
    amount_grams: parseInt(amountInput.value, 10),
    diet_type: dietInput.value || null,
    pet_id: parseInt(petId, 10),
  };
  const response = await fetch("/feedings", {
    method: "POST",
    headers: headers(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  if (response.ok) {
    setFeedStatus(`Saved for ${petName}.`);
    localStorage.setItem(lastAmountKey, payload.amount_grams.toString());
    lastAmountDisplay.textContent = payload.amount_grams.toString();
    loadFeedings();
    loadInventory();
  } else {
    const error = await response.json();
    setFeedStatus(error.detail || "Failed to save.", true);
  }
}

loadFeedings();
setFedAtNow();
loadLastAmount();
loadInventory();
loadWeights();
setWeightRecordedAtNow();
setReportDates();
updateInventoryTotal();
updateReportLink();

logNowBtn.addEventListener("click", () => {
  setFedAtNow();
  submitFeeding();
});

useLastAmountBtn.addEventListener("click", () => {
  const stored = localStorage.getItem(lastAmountKey);
  if (!stored) {
    setFeedStatus("No last amount yet.", true);
    return;
  }
  amountInput.value = stored;
  setFeedStatus("Last amount applied.");
});

document.getElementById("feed-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  submitFeeding();
});

if (inventorySachetCount) {
  inventorySachetCount.addEventListener("input", updateInventoryTotal);
}

if (inventoryForm) {
  inventoryForm.addEventListener("submit", (event) => {
    event.preventDefault();
    submitInventory();
  });
}

if (weightForm) {
  weightForm.addEventListener("submit", (event) => {
    event.preventDefault();
    submitWeight();
  });
}

if (reportStart) {
  reportStart.addEventListener("change", updateReportLink);
}

if (reportEnd) {
  reportEnd.addEventListener("change", updateReportLink);
}

const img = document.getElementById("pet-photo");
if (img && img.dataset.photo === "blob") {
  img.src = `/pets/${petId}/photo`;
}
