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
  } else {
    const error = await response.json();
    setFeedStatus(error.detail || "Failed to save.", true);
  }
}

loadFeedings();
setFedAtNow();
loadLastAmount();

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

const img = document.getElementById("pet-photo");
if (img && img.dataset.photo === "blob") {
  img.src = `/pets/${petId}/photo`;
}
