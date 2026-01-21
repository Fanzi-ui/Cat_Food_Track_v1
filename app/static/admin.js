const userList = document.getElementById("user-list");
const petList = document.getElementById("pet-list");
const auditList = document.getElementById("audit-list");
const maintenanceStatus = document.getElementById("maintenance-status");
const userStatus = document.getElementById("user-status");
const petStatus = document.getElementById("pet-status");
const adminUserCount = document.getElementById("admin-user-count");
const adminPetCount = document.getElementById("admin-pet-count");
const adminAuditCount = document.getElementById("admin-audit-count");
const confirmBackdrop = document.getElementById("confirm-backdrop");
const confirmTitle = document.getElementById("confirm-title");
const confirmMessage = document.getElementById("confirm-message");
const confirmOk = document.getElementById("confirm-ok");
const confirmCancel = document.getElementById("confirm-cancel");

let confirmResolver = null;

function confirmAction(title, message, okText = "Confirm") {
  if (!confirmBackdrop) {
    return Promise.resolve(window.confirm(message));
  }
  confirmTitle.textContent = title;
  confirmMessage.textContent = message;
  confirmOk.textContent = okText;
  confirmBackdrop.classList.remove("hidden");
  return new Promise(resolve => {
    confirmResolver = resolve;
  });
}

function closeConfirm(result) {
  if (!confirmBackdrop) {
    return;
  }
  confirmBackdrop.classList.add("hidden");
  if (confirmResolver) {
    confirmResolver(result);
    confirmResolver = null;
  }
}

if (confirmOk) {
  confirmOk.addEventListener("click", () => closeConfirm(true));
}
if (confirmCancel) {
  confirmCancel.addEventListener("click", () => closeConfirm(false));
}
if (confirmBackdrop) {
  confirmBackdrop.addEventListener("click", (event) => {
    if (event.target === confirmBackdrop) {
      closeConfirm(false);
    }
  });
}

function setCardStatus(target, message, isError = false) {
  if (!target) {
    return;
  }
  target.textContent = message;
  target.classList.remove("success", "error");
  target.classList.add(isError ? "error" : "success");
  target.style.display = "block";
}

function setUserStatus(message, isError = false) {
  setCardStatus(userStatus, message, isError);
}

function setPetStatus(message, isError = false) {
  setCardStatus(petStatus, message, isError);
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

function userRow(user) {
  const wrapper = document.createElement("div");
  wrapper.className = "user-row";
  const name = document.createElement("div");
  name.textContent = user.username + (user.is_active ? "" : " (disabled)");
  const controls = document.createElement("div");
  controls.className = "user-controls";
  const toggleBtn = document.createElement("button");
  toggleBtn.textContent = user.is_active ? "Disable" : "Enable";
  toggleBtn.addEventListener("click", () => toggleUser(user.id, !user.is_active));
  const emailField = document.createElement("div");
  emailField.className = "user-field";
  const emailLabel = document.createElement("label");
  emailLabel.textContent = "Notification emails (max 3)";
  const emailInput1 = document.createElement("input");
  emailInput1.type = "email";
  emailInput1.placeholder = "Primary email";
  emailInput1.value = user.notify_email_1 || "";
  const emailInput2 = document.createElement("input");
  emailInput2.type = "email";
  emailInput2.placeholder = "Secondary email (optional)";
  emailInput2.value = user.notify_email_2 || "";
  const emailInput3 = document.createElement("input");
  emailInput3.type = "email";
  emailInput3.placeholder = "Third email (optional)";
  emailInput3.value = user.notify_email_3 || "";
  emailField.appendChild(emailLabel);
  emailField.appendChild(emailInput1);
  emailField.appendChild(emailInput2);
  emailField.appendChild(emailInput3);
  const smtpField = document.createElement("div");
  smtpField.className = "user-field";
  const smtpLabel = document.createElement("label");
  smtpLabel.textContent = "SMTP settings";
  const smtpHost = document.createElement("input");
  smtpHost.type = "text";
  smtpHost.placeholder = "smtp.example.com";
  smtpHost.value = user.smtp_host || "";
  const smtpPort = document.createElement("input");
  smtpPort.type = "number";
  smtpPort.placeholder = "587";
  smtpPort.value = user.smtp_port || "";
  const smtpUser = document.createElement("input");
  smtpUser.type = "text";
  smtpUser.placeholder = "user@example.com";
  smtpUser.value = user.smtp_user || "";
  const smtpPass = document.createElement("input");
  smtpPass.type = "password";
  smtpPass.placeholder = "app password";
  const smtpFrom = document.createElement("input");
  smtpFrom.type = "email";
  smtpFrom.placeholder = "from@example.com";
  smtpFrom.value = user.smtp_from || "";
  smtpField.appendChild(smtpLabel);
  smtpField.appendChild(smtpHost);
  smtpField.appendChild(smtpPort);
  smtpField.appendChild(smtpUser);
  smtpField.appendChild(smtpPass);
  smtpField.appendChild(smtpFrom);
  const notifyWrap = document.createElement("label");
  notifyWrap.style.display = "flex";
  notifyWrap.style.alignItems = "center";
  notifyWrap.style.gap = "0.4rem";
  const notifyCheckbox = document.createElement("input");
  notifyCheckbox.type = "checkbox";
  notifyCheckbox.checked = !!user.notify_email;
  const notifyText = document.createElement("span");
  notifyText.textContent = "Email me on feedings";
  notifyWrap.appendChild(notifyCheckbox);
  notifyWrap.appendChild(notifyText);
  const passField = document.createElement("div");
  passField.className = "user-field";
  const passLabel = document.createElement("label");
  passLabel.textContent = "Reset password";
  const resetInput = document.createElement("input");
  resetInput.type = "password";
  resetInput.placeholder = "New password";
  passField.appendChild(passLabel);
  passField.appendChild(resetInput);
  const actions = document.createElement("div");
  actions.className = "user-actions";
  const saveBtn = document.createElement("button");
  saveBtn.textContent = "Save Email Settings";
  saveBtn.addEventListener("click", () => {
    updateUserEmail(
      user.id,
      notifyCheckbox.checked,
      emailInput1.value,
      emailInput2.value,
      emailInput3.value,
      smtpHost.value,
      smtpPort.value,
      smtpUser.value,
      smtpPass.value,
      smtpFrom.value
    );
  });
  const resetBtn = document.createElement("button");
  resetBtn.textContent = "Reset Password";
  resetBtn.addEventListener("click", () => resetPassword(user.id, resetInput.value));
  actions.appendChild(toggleBtn);
  actions.appendChild(saveBtn);
  actions.appendChild(resetBtn);
  controls.appendChild(emailField);
  controls.appendChild(notifyWrap);
  controls.appendChild(smtpField);
  controls.appendChild(passField);
  controls.appendChild(actions);
  wrapper.appendChild(name);
  wrapper.appendChild(controls);
  return wrapper;
}

async function loadUsers() {
  const response = await fetch("/admin/users", { credentials: "include" });
  if (!response.ok) {
    userList.textContent = "Unable to load users.";
    setUserStatus("Could not load users.", true);
    return;
  }
  const users = await response.json();
  if (adminUserCount) {
    adminUserCount.textContent = users.length;
  }
  userList.innerHTML = "";
  users.forEach(user => userList.appendChild(userRow(user)));
}

function petRow(pet) {
  const wrapper = document.createElement("div");
  wrapper.className = "pet-row";
  const title = document.createElement("div");
  title.textContent = pet.name + " (" + pet.feedings_count + " feedings)";
  const meta = document.createElement("div");
  meta.className = "note";
  const bits = [];
  if (pet.breed) bits.push(pet.breed);
  if (pet.diet_type) bits.push(pet.diet_type);
  meta.textContent = bits.join(" - ") || "No extra details";
  const controls = document.createElement("div");
  controls.className = "pet-controls";
  const limitCount = document.createElement("input");
  limitCount.type = "number";
  limitCount.min = "1";
  limitCount.placeholder = "Daily limit (count)";
  limitCount.value = pet.daily_limit_count || "";
  const limitGrams = document.createElement("input");
  limitGrams.type = "number";
  limitGrams.min = "1";
  limitGrams.placeholder = "Daily grams limit";
  limitGrams.value = pet.daily_grams_limit || "";
  const saveBtn = document.createElement("button");
  saveBtn.textContent = "Save Limits";
  saveBtn.addEventListener("click", () => {
    updatePetLimits(pet.id, limitCount.value, limitGrams.value);
  });
  const deleteBtn = document.createElement("button");
  deleteBtn.textContent = "Delete Pet + Feedings";
  deleteBtn.addEventListener("click", () => deletePet(pet.id, pet.name));
  controls.appendChild(limitCount);
  controls.appendChild(limitGrams);
  controls.appendChild(saveBtn);
  controls.appendChild(deleteBtn);
  wrapper.appendChild(title);
  wrapper.appendChild(meta);
  wrapper.appendChild(controls);
  return wrapper;
}

async function loadPets() {
  const response = await fetch("/admin/pets", { credentials: "include" });
  if (!response.ok) {
    petList.textContent = "Unable to load pets.";
    setPetStatus("Could not load pets.", true);
    return;
  }
  const pets = await response.json();
  if (adminPetCount) {
    adminPetCount.textContent = pets.length;
  }
  petList.innerHTML = "";
  pets.forEach(pet => petList.appendChild(petRow(pet)));
}

async function deletePet(petId, petName) {
  const ok = await confirmAction(
    "Delete pet",
    `Delete ${petName}? This also deletes its feedings.`,
    "Delete"
  );
  if (!ok) {
    return;
  }
  const response = await fetch(`/admin/pets/${petId}` , {
    method: "DELETE",
    headers: headers(),
    credentials: "include"
  });
  if (response.ok) {
    setPetStatus("Pet deleted.");
    loadPets();
  } else {
    const error = await response.json();
    setPetStatus(error.detail || "Delete failed.", true);
  }
}

async function updatePetLimits(petId, limitCount, limitGrams) {
  const payload = {
    daily_limit_count: limitCount ? parseInt(limitCount, 10) : null,
    daily_grams_limit: limitGrams ? parseInt(limitGrams, 10) : null
  };
  const response = await fetch(`/admin/pets/${petId}` , {
    method: "PATCH",
    headers: headers(),
    credentials: "include",
    body: JSON.stringify(payload)
  });
  if (response.ok) {
    setPetStatus("Pet limits updated.");
    loadPets();
  } else {
    const error = await response.json();
    setPetStatus(error.detail || "Update failed.", true);
  }
}

async function loadAudit() {
  const response = await fetch("/admin/audit?limit=30", { credentials: "include" });
  if (!response.ok) {
    auditList.textContent = "Unable to load audit log.";
    return;
  }
  const logs = await response.json();
  if (adminAuditCount) {
    adminAuditCount.textContent = logs.length;
  }
  auditList.innerHTML = "";
  if (!logs.length) {
    auditList.textContent = "No audit entries yet.";
    return;
  }
  logs.forEach(entry => {
    const item = document.createElement("div");
    item.className = "audit-item";
    const when = new Date(entry.created_at).toLocaleString();
    const who = entry.actor_user_id ? "user " + entry.actor_user_id : "system";
    const details = entry.details ? " - " + entry.details : "";
    item.textContent = `${when} - ${entry.action} (${who})${details}`;
    auditList.appendChild(item);
  });
}

async function toggleUser(userId, isActive) {
  const response = await fetch(`/admin/users/${userId}` , {
    method: "PATCH",
    headers: headers(),
    credentials: "include",
    body: JSON.stringify({ is_active: isActive })
  });
  if (response.ok) {
    setUserStatus("User updated.");
    loadUsers();
  } else {
    const error = await response.json();
    setUserStatus(error.detail || "Update failed.", true);
  }
}

async function resetPassword(userId, newPassword) {
  if (!newPassword) {
    setUserStatus("Enter a new password.", true);
    return;
  }
  const response = await fetch(`/admin/users/${userId}/reset-password` , {
    method: "POST",
    headers: headers(),
    credentials: "include",
    body: JSON.stringify({ new_password: newPassword })
  });
  if (response.ok) {
    setUserStatus("Password reset.");
    loadUsers();
  } else {
    const error = await response.json();
    setUserStatus(error.detail || "Reset failed.", true);
  }
}

async function updateUserEmail(
  userId,
  notifyEmail,
  email1,
  email2,
  email3,
  smtpHost,
  smtpPort,
  smtpUser,
  smtpPass,
  smtpFrom
) {
  const payload = {
    notify_email: !!notifyEmail,
    notify_email_1: email1 ? email1.trim() : null,
    notify_email_2: email2 ? email2.trim() : null,
    notify_email_3: email3 ? email3.trim() : null,
    smtp_host: smtpHost ? smtpHost.trim() : null,
    smtp_port: smtpPort ? parseInt(smtpPort, 10) : null,
    smtp_user: smtpUser ? smtpUser.trim() : null,
    smtp_from: smtpFrom ? smtpFrom.trim() : null,
  };
  if (smtpPass) {
    payload.smtp_pass = smtpPass.trim();
  }
  const response = await fetch(`/admin/users/${userId}` , {
    method: "PATCH",
    headers: headers(),
    credentials: "include",
    body: JSON.stringify(payload)
  });
  if (response.ok) {
    setUserStatus("User email settings saved.");
    loadUsers();
  } else {
    const error = await response.json();
    setUserStatus(error.detail || "Update failed.", true);
  }
}

document.getElementById("change-pass-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const status = document.getElementById("change-pass-status");
  status.textContent = "Updating...";
  const payload = {
    current_password: document.getElementById("current_pass").value,
    new_password: document.getElementById("new_pass").value
  };
  const response = await fetch("/change-password", {
    method: "POST",
    headers: headers(),
    credentials: "include",
    body: JSON.stringify(payload)
  });
  if (response.ok) {
    status.textContent = "Password updated.";
    document.getElementById("current_pass").value = "";
    document.getElementById("new_pass").value = "";
  } else {
    const error = await response.json();
    status.textContent = error.detail || "Update failed.";
  }
});

document.getElementById("clear-data-btn").addEventListener("click", async () => {
  const ok = await confirmAction(
    "Clear data",
    "Clear all pets and feedings? This cannot be undone.",
    "Clear"
  );
  if (!ok) {
    return;
  }
  maintenanceStatus.textContent = "Clearing...";
  const response = await fetch("/admin/maintenance/clear", {
    method: "POST",
    headers: headers(),
    credentials: "include"
  });
  if (response.ok) {
    maintenanceStatus.textContent = "Data cleared.";
    setPetStatus("Data cleared.");
    loadPets();
    loadAudit();
  } else {
    const error = await response.json();
    maintenanceStatus.textContent = error.detail || "Clear failed.";
    setPetStatus(error.detail || "Clear failed.", true);
  }
});

document.getElementById("seed-data-btn").addEventListener("click", async () => {
  const ok = await confirmAction(
    "Seed sample data",
    "Seed sample pets and feedings into the database?",
    "Seed"
  );
  if (!ok) {
    return;
  }
  maintenanceStatus.textContent = "Seeding...";
  const response = await fetch("/admin/maintenance/seed", {
    method: "POST",
    headers: headers(),
    credentials: "include"
  });
  if (response.ok) {
    maintenanceStatus.textContent = "Seeded sample data.";
    setPetStatus("Sample data seeded.");
    loadPets();
    loadAudit();
  } else {
    const error = await response.json();
    maintenanceStatus.textContent = error.detail || "Seed failed.";
    setPetStatus(error.detail || "Seed failed.", true);
  }
});

loadUsers();
loadPets();
loadAudit();
