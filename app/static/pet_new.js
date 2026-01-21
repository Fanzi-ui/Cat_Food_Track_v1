const petStatus = document.getElementById("pet-status");
const petCreated = document.getElementById("pet-created");
const petMessageCard = document.getElementById("pet-message-card");
const petPhotoInput = document.getElementById("pet_photo");
const petBreed = document.getElementById("pet_breed");
const petWeight = document.getElementById("pet_weight");
let petPhotoData = null;

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

if (petPhotoInput) {
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
}

const petForm = document.getElementById("pet-form");
if (petForm) {
  petForm.addEventListener("submit", async (event) => {
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
      feed_time_1: document.getElementById("pet_feed_time_1").value || null,
      feed_time_2: document.getElementById("pet_feed_time_2").value || null,
      photo_base64: petPhotoData,
      last_vet_visit: document.getElementById("pet_vet").value || null
    };
    try {
      const response = await fetch("/pets", {
        method: "POST",
        headers: headers(),
        credentials: "include",
        body: JSON.stringify(payload)
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || "Failed to create pet.");
      }
      setPetMessage(petStatus, "Pet created.");
      if (petCreated) {
        petCreated.innerHTML = `Open profile: <a href="/pets/${data.id}/profile">${data.name}</a>`;
        petCreated.classList.remove("error");
        petCreated.classList.add("success");
        petCreated.style.display = "block";
      }
      document.getElementById("pet_name").value = "";
      petBreed.value = "";
      document.getElementById("pet_age").value = "";
      document.getElementById("pet_sex").value = "";
      petWeight.value = "";
      document.getElementById("pet_diet").value = "";
      document.getElementById("pet_feed_time_1").value = "";
      document.getElementById("pet_feed_time_2").value = "";
      document.getElementById("pet_photo").value = "";
      document.getElementById("pet_vet").value = "";
      petPhotoData = null;
    } catch (error) {
      setPetMessage(petStatus, error.message || "Failed to create pet.", true);
    }
  });
}
