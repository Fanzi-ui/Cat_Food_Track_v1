const statusEl = document.getElementById("status");
const photoFile = document.getElementById("photo_file");
const photoUrlInput = document.getElementById("photo_url");
const removePhotoBtn = document.getElementById("remove-photo-btn");
const petId = document.body.dataset.petId;
const petName = document.body.dataset.petName;
let photoData = null;
let removePhoto = false;

function setStatus(message, isError = false) {
  if (!statusEl) {
    return;
  }
  statusEl.textContent = message;
  statusEl.classList.remove("success", "error");
  if (message) {
    statusEl.classList.add(isError ? "error" : "success");
  }
  statusEl.style.display = message ? "block" : "none";
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

function hidePhoto() {
  const img = document.getElementById("pet-photo");
  if (img) {
    img.src = "";
    img.style.display = "none";
  }
}

photoFile.addEventListener("change", () => {
  const file = photoFile.files[0];
  if (!file) {
    photoData = null;
    return;
  }
  removePhoto = false;
  const reader = new FileReader();
  reader.onload = () => {
    photoData = reader.result;
    const img = document.getElementById("pet-photo");
    if (img) {
      img.src = photoData;
      img.style.display = "block";
    }
  };
  reader.readAsDataURL(file);
});

photoUrlInput.addEventListener("input", () => {
  removePhoto = false;
});

removePhotoBtn.addEventListener("click", () => {
  removePhoto = true;
  photoData = "";
  photoFile.value = "";
  photoUrlInput.value = "";
  hidePhoto();
  setStatus("Photo will be removed.");
});

document.getElementById("edit-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  setStatus("Saving...");
  const payload = {
    name: document.getElementById("name").value.trim(),
    breed: document.getElementById("breed").value.trim() || null,
    age_years: document.getElementById("age_years").value
      ? parseInt(document.getElementById("age_years").value, 10)
      : null,
    sex: document.getElementById("sex").value.trim() || null,
    estimated_weight_kg: document.getElementById("estimated_weight_kg").value
      ? parseFloat(document.getElementById("estimated_weight_kg").value)
      : null,
    diet_type: document.getElementById("diet_type").value.trim() || null,
    photo_url: photoUrlInput.value.trim() || null,
    photo_base64: photoData,
    last_vet_visit: document.getElementById("last_vet_visit").value || null,
  };
  if (removePhoto) {
    payload.photo_url = null;
    payload.photo_base64 = "";
  }
  if (photoData === null && !removePhoto) {
    delete payload.photo_base64;
  }
  const response = await fetch(`/pets/${petId}` , {
    method: "PATCH",
    headers: headers(),
    credentials: "include",
    body: JSON.stringify(payload),
  });
  if (response.ok) {
    setStatus("Saved.");
  } else {
    const error = await response.json();
    setStatus(error.detail || "Failed to save.", true);
  }
});

document.getElementById("delete-btn").addEventListener("click", async () => {
  if (!confirm(`Delete ${petName}? This also deletes its feedings.`)) {
    return;
  }
  setStatus("Deleting...");
  const response = await fetch(`/pets/${petId}` , {
    method: "DELETE",
    headers: headers(),
    credentials: "include",
  });
  if (response.ok) {
    setStatus("Deleted.");
    setTimeout(() => {
      window.location.href = "/";
    }, 800);
  } else {
    const error = await response.json();
    setStatus(error.detail || "Failed to delete.", true);
  }
});

const img = document.getElementById("pet-photo");
if (img && img.dataset.photo === "blob") {
  img.src = `/pets/${petId}/photo`;
}
