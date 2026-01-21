const authPill = document.getElementById("auth-pill");
const usernameDisplay = document.getElementById("username-display");
const logoutBtn = document.getElementById("logout-btn");
const ringGrid = document.getElementById("ring-grid");
const sparkline = document.getElementById("sparkline");
const petList = document.getElementById("pet-list");
const petStatus = document.getElementById("pet-status");
const petCreated = document.getElementById("pet-created");
const petMessageCard = document.getElementById("pet-message-card");
const petSearch = document.getElementById("pet-search");
const loginStatus = document.getElementById("login-status");
const signupStatus = document.getElementById("signup-status");
const signupCard = document.getElementById("signup-card");
const petPhotoInput = document.getElementById("pet_photo");
const petBreed = document.getElementById("pet_breed");
const petWeight = document.getElementById("pet_weight");
const pageLinks = document.getElementById("page-links");
const authPanel = document.getElementById("auth-panel");
const dashboardPanel = document.getElementById("dashboard-panel");
const contentPanels = ["status-panel", "pets-panel"];
const statsStart = document.getElementById("stats-start");
const statsEnd = document.getElementById("stats-end");
const statsPet = document.getElementById("stats-pet");
const statsApply = document.getElementById("stats-apply");
const statsExport = document.getElementById("stats-export");
const statsEmpty = document.getElementById("stats-empty");
const lastUpdated = document.getElementById("last-updated");
const pushCard = document.getElementById("push-card");
const pushEnable = document.getElementById("push-enable");
const pushDisable = document.getElementById("push-disable");
const pushStatus = document.getElementById("push-status");
let petsCache = [];
const tips = [
  "Tip: Log feedings from each pet profile.",
  "Tip: Use the pet photo field to spot the right cat fast.",
  "Tip: Set daily limits per pet in Admin to prevent overfeeding.",
  "Tip: Check Status for today's totals at a glance.",
  "Tip: Export CSVs from Admin for backups."
];
let tipIndex = 0;
const tipText = document.getElementById("tip-text");
const activityList = document.getElementById("activity-list");
const dashboardTotalFeedings = document.getElementById("dashboard-total-feedings");
const dashboardTotalGrams = document.getElementById("dashboard-total-grams");
const dashboardRemainingFeedings = document.getElementById("dashboard-remaining-feedings");
const dashboardPetsCount = document.getElementById("dashboard-pets-count");
const dashboardPetList = document.getElementById("dashboard-pet-list");
const dashboardAlerts = document.getElementById("dashboard-alerts");
let petPhotoData = null;

function setPetMessage(target, message, isError = false) {
  if (!target) {
    return;
  }
  target.textContent = message;
  target.classList.remove("success", "error");
  if (message) {
    target.classList.add(isError ? "error" : "success");
  }
  target.style.display = message ? "block" : "none";
  if (petMessageCard) {
    const hasMessage = !!message || (petCreated && petCreated.textContent);
    petMessageCard.classList.toggle("hidden", !hasMessage);
  }
}

function setAuthMessage(target, message, isError = false) {
  if (!target) {
    return;
  }
  target.textContent = message;
  target.classList.remove("success", "error");
  if (message) {
    target.classList.add(isError ? "error" : "success");
  }
  target.style.display = message ? "block" : "none";
}

function setPushMessage(message, isError = false) {
  if (!pushStatus) {
    return;
  }
  pushStatus.textContent = message;
  pushStatus.classList.remove("success", "error");
  if (message) {
    pushStatus.classList.add(isError ? "error" : "success");
  }
  pushStatus.style.display = message ? "block" : "none";
}

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const outputArray = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i += 1) {
    outputArray[i] = raw.charCodeAt(i);
  }
  return outputArray;
}

async function getPushRegistration() {
  if (!("serviceWorker" in navigator)) {
    return null;
  }
  return navigator.serviceWorker.ready;
}

async function getPushSubscription() {
  const registration = await getPushRegistration();
  if (!registration || !registration.pushManager) {
    return null;
  }
  return registration.pushManager.getSubscription();
}

async function updatePushUI() {
  if (!pushCard) {
    return;
  }
  if (!("Notification" in window) || !("serviceWorker" in navigator)) {
    pushCard.classList.add("hidden");
    return;
  }
  const subscription = await getPushSubscription();
  if (subscription) {
    setPushMessage("Notifications enabled.");
  } else {
    setPushMessage("Notifications disabled.");
  }
}

async function enablePush() {
  if (!("Notification" in window) || !("serviceWorker" in navigator)) {
    setPushMessage("Push notifications not supported.", true);
    return;
  }
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    setPushMessage("Permission denied.", true);
    return;
  }
  const keyRes = await fetch("/push/vapid-public-key", { credentials: "include" });
  if (!keyRes.ok) {
    setPushMessage("Push not configured on server.", true);
    return;
  }
  const data = await keyRes.json();
  const registration = await getPushRegistration();
  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(data.public_key),
  });
  const response = await fetch("/push/subscribe", {
    method: "POST",
    headers: headers(),
    credentials: "include",
    body: JSON.stringify(subscription),
  });
  if (response.ok) {
    setPushMessage("Notifications enabled.");
  } else {
    const error = await response.json();
    setPushMessage(error.detail || "Failed to enable.", true);
  }
}

async function disablePush() {
  const subscription = await getPushSubscription();
  if (!subscription) {
    setPushMessage("Notifications already disabled.");
    return;
  }
  await fetch("/push/unsubscribe", {
    method: "POST",
    headers: headers(),
    credentials: "include",
    body: JSON.stringify(subscription),
  });
  await subscription.unsubscribe();
  setPushMessage("Notifications disabled.");
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

function showPanel(panelId) {
  contentPanels.forEach(id => {
    document.getElementById(id).classList.toggle("hidden", id !== panelId);
  });
}

function formatLastFed(value) {
  if (!value) {
    return "Never";
  }
  const when = new Date(value);
  return Number.isNaN(when.getTime()) ? "Unknown" : when.toLocaleString();
}

function setDashboardText(target, value) {
  if (target) {
    target.textContent = value;
  }
}

function renderSparkline(items, hasData) {
  if (!sparkline) {
    return;
  }
  if (!hasData) {
    sparkline.innerHTML = "";
    return;
  }
  const values = items.map(item => item.grams);
  const max = Math.max(1, ...values);
  const points = values.map((v, i) => {
    const x = (i / Math.max(1, values.length - 1)) * 100;
    const y = 36 - (v / max) * 32;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(" ");
  const moving = values.map((_, i) => {
    const start = Math.max(0, i - 2);
    const slice = values.slice(start, i + 1);
    const avg = slice.reduce((a, b) => a + b, 0) / slice.length;
    const x = (i / Math.max(1, values.length - 1)) * 100;
    const y = 36 - (avg / max) * 32;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(" ");
  sparkline.innerHTML = `
    <polyline fill="none" stroke="#b5633f" stroke-width="2" points="${points}" />
    <polyline fill="none" stroke="#6c6058" stroke-width="1.5" points="${moving}" />
  `;
}

function renderRingSummary(items, limitGrams) {
  const ring = document.getElementById("ring-summary");
  const totalEl = document.getElementById("ring-total");
  const subEl = document.getElementById("ring-sub");
  const total = items.reduce((sum, item) => sum + item.grams, 0);
  const days = Math.max(1, items.length);
  const avg = Math.round(total / days);
  const limitTotal = limitGrams ? limitGrams * days : null;
  const hasData = items.some(item => item.grams > 0 || item.count > 0);
  const percent = limitTotal ? Math.min(100, Math.round((total / limitTotal) * 100)) : 0;
  ring.style.setProperty("--percent", percent);
  totalEl.textContent = `${total}g`;
  if (!hasData) {
    subEl.textContent = "No data yet";
    return false;
  }
  if (limitTotal) {
    subEl.textContent = `${avg}g/day - ${percent}% of limit`;
  } else {
    subEl.textContent = `${avg}g/day - no limit`;
  }
  return true;
}

function updateStatsExport(params) {
  statsExport.href = "/stats/export" + params;
}

function petLimitGrams(petId) {
  if (!petId) return null;
  const pet = petsCache.find(item => String(item.id) === String(petId));
  return pet && pet.daily_grams_limit ? pet.daily_grams_limit : null;
}

function updateStatsPetSelect() {
  if (!statsPet) {
    return;
  }
  statsPet.innerHTML = '<option value="">All pets</option>';
  petsCache.forEach(pet => {
    const option = document.createElement("option");
    option.value = pet.id;
    option.textContent = pet.name;
    statsPet.appendChild(option);
  });
}

async function fetchStatus(petId) {
  const url = petId ? `/pets/${petId}/status` : "/status";
  const statusRes = await fetch(url, { headers: headers(), credentials: "include" });
  if (!statusRes.ok) {
    return;
  }
  const data = await statusRes.json();
  const lastFed = document.getElementById("last-fed-at");
  const lastDiet = document.getElementById("last-diet-type");
  const dailyCount = document.getElementById("daily-count");
  const remaining = document.getElementById("remaining-feedings");
  lastFed.textContent = data.last_fed_at || "Never";
  lastDiet.textContent = data.last_diet_type || "Unknown";
  dailyCount.textContent = data.daily_count;
  remaining.textContent = data.remaining_feedings;
  lastFed.classList.toggle("highlight-green", !!data.last_fed_at);
}

async function refreshStats() {
  const petId = statsPet ? statsPet.value : "";
  const startVal = statsStart && statsStart.value ? statsStart.value : "";
  const endVal = statsEnd && statsEnd.value ? statsEnd.value : "";
  let params = "";
  if (startVal && endVal) {
    params = `?start=${startVal}&end=${endVal}`;
  }
  if (petId) {
    params += params ? `&pet_id=${petId}` : `?pet_id=${petId}`;
  }
  const statsUrl = "/stats/daily" + (params || "?days=7");
  const chartRes = await fetch(statsUrl, { headers: headers(), credentials: "include" });
  if (chartRes.ok) {
    const chartData = await chartRes.json();
    const limitGrams = petLimitGrams(petId);
    const hasData = renderRingSummary(chartData.items, limitGrams);
    renderSparkline(chartData.items, hasData);
    if (statsEmpty) {
      statsEmpty.classList.toggle("hidden", hasData);
    }
    updateStatsExport(params || "?days=7");
  }
  await fetchStatus(petId);
  if (lastUpdated) {
    const now = new Date();
    lastUpdated.textContent = `Last updated: ${now.toLocaleTimeString()}`;
  }
}

async function loadActivity() {
  if (!activityList) {
    return;
  }
  const response = await fetch("/activity?limit=5", { credentials: "include" });
  if (!response.ok) {
    activityList.textContent = "";
    return;
  }
  const items = await response.json();
  activityList.innerHTML = "";
  if (!items.length) {
    activityList.innerHTML = "<div class='activity-item'>No recent feedings.</div>";
    return;
  }
  items.forEach(entry => {
    const item = document.createElement("div");
    item.className = "activity-item";
    const when = new Date(entry.created_at).toLocaleString();
    item.textContent = `${when} - ${entry.details || "Feeding logged"}`;
    activityList.appendChild(item);
  });
}

async function refreshAll() {
  const meRes = await fetch("/me", { credentials: "include" });
  if (!meRes.ok) {
    authPill.textContent = "Signed out";
    usernameDisplay.textContent = "";
    logoutBtn.style.display = "none";
    authPanel.classList.remove("hidden");
    dashboardPanel.classList.add("hidden");
    pageLinks.style.display = "none";
    contentPanels.forEach(id => document.getElementById(id).classList.add("hidden"));
    return;
  }
  const me = await meRes.json();
  authPill.textContent = "Signed in";
  usernameDisplay.textContent = me.username || "";
  logoutBtn.style.display = "inline-flex";
  authPanel.classList.add("hidden");
  pageLinks.style.display = "flex";
  updatePushUI();
  if (document.body.dataset.mode === "dashboard") {
    dashboardPanel.classList.remove("hidden");
    contentPanels.forEach(id => document.getElementById(id).classList.add("hidden"));
    await loadPets();
    await refreshDashboard();
    await loadActivity();
    return;
  }
  dashboardPanel.classList.add("hidden");
  const hash = window.location.hash.replace("#", "") || "status";
  const panelByHash = {
    status: "status-panel",
    pets: "pets-panel",
  };
  showPanel(panelByHash[hash] || "status-panel");
  await loadPets();
  await refreshStats();
  await loadActivity();
}

async function loadDashboardStats() {
  const statusRes = await fetch("/status", { headers: headers(), credentials: "include" });
  if (statusRes.ok) {
    const status = await statusRes.json();
    setDashboardText(dashboardTotalFeedings, status.daily_count);
    setDashboardText(dashboardRemainingFeedings, status.remaining_feedings);
  }
  const statsRes = await fetch("/stats/daily?days=1", { headers: headers(), credentials: "include" });
  if (statsRes.ok) {
    const data = await statsRes.json();
    const grams = data.items.reduce((sum, item) => sum + item.grams, 0);
    setDashboardText(dashboardTotalGrams, `${grams}g`);
  }
  setDashboardText(dashboardPetsCount, petsCache.length);
}

async function loadDashboardPets() {
  if (!dashboardPetList || !dashboardAlerts) {
    return;
  }
  dashboardPetList.innerHTML = "";
  dashboardAlerts.innerHTML = "";
  if (!petsCache.length) {
    const empty = document.createElement("div");
    empty.className = "note";
    empty.textContent = "No pets yet. Add one to start tracking.";
    dashboardPetList.appendChild(empty);
    return;
  }
  const results = await Promise.all(petsCache.map(async pet => {
    const res = await fetch(`/pets/${pet.id}/status`, {
      headers: headers(),
      credentials: "include"
    });
    if (!res.ok) {
      return null;
    }
    const status = await res.json();
    return { pet, status };
  }));
  const entries = results.filter(Boolean);
  entries.forEach(({ pet, status }) => {
    const card = document.createElement("div");
    card.className = "pet-card";
    const link = document.createElement("a");
    link.href = `/pets/${pet.id}/profile`;
    link.textContent = pet.name;
    const lastFed = document.createElement("div");
    lastFed.className = "meta";
    lastFed.textContent = `Last fed: ${formatLastFed(status.last_fed_at)}`;
    const remaining = document.createElement("div");
    remaining.className = "meta";
    remaining.textContent = `Remaining feedings: ${status.remaining_feedings}`;
    card.appendChild(link);
    card.appendChild(lastFed);
    card.appendChild(remaining);
    dashboardPetList.appendChild(card);
  });
  const alerts = entries.filter(({ status }) => status.remaining_feedings <= 1);
  if (!alerts.length) {
    const ok = document.createElement("div");
    ok.className = "alert-item ok";
    ok.textContent = "All pets are within their daily limits.";
    dashboardAlerts.appendChild(ok);
    return;
  }
  alerts.forEach(({ pet, status }) => {
    const item = document.createElement("div");
    item.className = "alert-item";
    const remaining = status.remaining_feedings;
    const label = remaining === 0 ? "no feedings left" : "only 1 feeding left";
    item.textContent = `${pet.name} has ${label} today.`;
    dashboardAlerts.appendChild(item);
  });
}

async function refreshDashboard() {
  await loadDashboardStats();
  await loadDashboardPets();
}

function renderPetList() {
  if (!petList) {
    return;
  }
  const query = petSearch ? petSearch.value.trim().toLowerCase() : "";
  petList.innerHTML = "";
  const filtered = petsCache.filter(pet => pet.name.toLowerCase().includes(query));
  if (!filtered.length) {
    petList.innerHTML = "<li class='pet-item'>No pets found.</li>";
    return;
  }
  filtered.forEach(pet => {
    const item = document.createElement("li");
    item.className = "pet-item";
    const link = document.createElement("a");
    link.href = "/pets/" + pet.id + "/profile";
    link.textContent = pet.name;
    const view = document.createElement("span");
    view.textContent = "View";
    item.appendChild(link);
    item.appendChild(view);
    petList.appendChild(item);
  });
}

async function loadPets() {
  const response = await fetch("/pets", { headers: headers(), credentials: "include" });
  if (!response.ok) {
    return;
  }
  const pets = await response.json();
  petsCache = pets;
  updateStatsPetSelect();
  renderPetList();
}

if (petSearch) {
  petSearch.addEventListener("input", renderPetList);
}

petPhotoInput.addEventListener("change", () => {
  const file = petPhotoInput.files[0];
  if (!file) {
    petPhotoData = null;
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    petPhotoData = reader.result;
  };
  reader.readAsDataURL(file);
});

document.getElementById("pet-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  setPetMessage(petStatus, "Creating...");
  if (petCreated) {
    petCreated.textContent = "";
    petCreated.style.display = "none";
  }
  const payload = {
    name: document.getElementById("pet_name").value.trim(),
    breed: petBreed.value || null,
    age_years: document.getElementById("pet_age").value
      ? parseInt(document.getElementById("pet_age").value, 10)
      : null,
    sex: document.getElementById("pet_sex").value.trim() || null,
    estimated_weight_kg: petWeight.value ? parseFloat(petWeight.value) : null,
    diet_type: document.getElementById("pet_diet").value.trim() || null,
    photo_base64: petPhotoData,
    last_vet_visit: document.getElementById("pet_vet").value || null
  };
  const response = await fetch("/pets", {
    method: "POST",
    headers: headers(),
    credentials: "include",
    body: JSON.stringify(payload)
  });
  if (response.ok) {
    const created = await response.json();
    setPetMessage(petStatus, "Pet created.");
    if (petCreated) {
      petCreated.innerHTML = `Open profile: <a href="/pets/${created.id}/profile">${created.name}</a>`;
      petCreated.classList.remove("error");
      petCreated.classList.add("success");
      petCreated.style.display = "block";
      if (petMessageCard) {
        petMessageCard.classList.remove("hidden");
      }
    }
    document.getElementById("pet_name").value = "";
    petBreed.value = "";
    document.getElementById("pet_age").value = "";
    document.getElementById("pet_sex").value = "";
    petWeight.value = "";
    document.getElementById("pet_diet").value = "";
    document.getElementById("pet_photo").value = "";
    document.getElementById("pet_vet").value = "";
    petPhotoData = null;
    loadPets();
  } else {
    const error = await response.json();
    setPetMessage(petStatus, error.detail || "Failed to create pet.", true);
  }
});

document.getElementById("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  setAuthMessage(loginStatus, "Signing in...");
  const payload = {
    username: document.getElementById("login_user").value.trim(),
    password: document.getElementById("login_pass").value
  };
  const response = await fetch("/login", {
    method: "POST",
    headers: headers(),
    credentials: "include",
    body: JSON.stringify(payload)
  });
  if (response.ok) {
    await response.json();
    setAuthMessage(loginStatus, "Signed in.");
    refreshAll();
  } else {
    setAuthMessage(loginStatus, "Invalid credentials.", true);
  }
});

document.getElementById("signup-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  setAuthMessage(signupStatus, "Creating...");
  const payload = {
    username: document.getElementById("signup_user").value.trim(),
    password: document.getElementById("signup_pass").value
  };
  const response = await fetch("/signup", {
    method: "POST",
    headers: headers(),
    credentials: "include",
    body: JSON.stringify(payload)
  });
  if (response.ok) {
    await response.json();
    setAuthMessage(signupStatus, "Account created.");
    refreshAll();
  } else {
    const error = await response.json();
    setAuthMessage(signupStatus, error.detail || "Signup failed.", true);
  }
});

logoutBtn.addEventListener("click", () => {
  fetch("/logout", { method: "POST", headers: headers(), credentials: "include" }).finally(() => {
    refreshAll();
  });
});

if (statsApply) {
  statsApply.addEventListener("click", () => {
    refreshStats();
  });
}

async function checkAuthStatus() {
  const response = await fetch("/auth/status", { credentials: "include" });
  if (response.ok) {
    const data = await response.json();
    signupCard.style.display = data.has_users ? "none" : "block";
  }
}

checkAuthStatus();
if (document.body.dataset.mode !== "dashboard") {
  if (!window.location.hash && document.body.dataset.initial) {
    window.location.hash = document.body.dataset.initial;
  }
}
if (statsStart && statsEnd) {
  const today = new Date();
  const end = new Date(today.getTime() - today.getTimezoneOffset() * 60000);
  const start = new Date(end);
  start.setDate(start.getDate() - 6);
  statsEnd.value = end.toISOString().slice(0, 10);
  statsStart.value = start.toISOString().slice(0, 10);
}
refreshAll();
updatePushUI();
setInterval(refreshAll, 30000);
setInterval(() => {
  if (!tipText) {
    return;
  }
  tipIndex = (tipIndex + 1) % tips.length;
  tipText.textContent = tips[tipIndex];
}, 10000);

if (pushEnable) {
  pushEnable.addEventListener("click", () => {
    enablePush();
  });
}

if (pushDisable) {
  pushDisable.addEventListener("click", () => {
    disablePush();
  });
}
