const petList = document.getElementById("pet-list");
const petSearch = document.getElementById("pet-search");
const petStatus = document.getElementById("pet-status");
let petsCache = [];

function setPetStatus(message, isError = false) {
  if (!petStatus) {
    return;
  }
  petStatus.textContent = message;
  petStatus.classList.toggle("error", isError);
  petStatus.style.display = message ? "block" : "none";
}

function makePlaceholder(name) {
  const placeholder = document.createElement("div");
  placeholder.className = "pet-photo";
  const initial = name && name.trim() ? name.trim()[0].toUpperCase() : "?";
  placeholder.textContent = initial;
  placeholder.style.display = "grid";
  placeholder.style.placeItems = "center";
  placeholder.style.fontWeight = "700";
  placeholder.style.color = "#6c6058";
  return placeholder;
}

function buildPhoto(pet) {
  const img = document.createElement("img");
  img.className = "pet-photo";
  img.alt = pet.name;
  img.loading = "lazy";
  img.src = pet.photo_url || `/pets/${pet.id}/photo`;
  img.addEventListener("error", () => {
    const placeholder = makePlaceholder(pet.name);
    img.replaceWith(placeholder);
  }, { once: true });
  return img;
}

function renderPetList() {
  if (!petList) {
    return;
  }
  const query = petSearch ? petSearch.value.trim().toLowerCase() : "";
  petList.innerHTML = "";
  const filtered = petsCache.filter(pet => pet.name.toLowerCase().includes(query));
  if (!filtered.length) {
    const empty = document.createElement("li");
    empty.className = "pet-item";
    empty.textContent = "No pets found.";
    petList.appendChild(empty);
    return;
  }
  filtered.forEach(pet => {
    const item = document.createElement("li");
    item.className = "pet-item";
    item.appendChild(buildPhoto(pet));

    const meta = document.createElement("div");
    meta.className = "pet-meta";
    const link = document.createElement("a");
    link.href = `/pets/${pet.id}/profile`;
    link.textContent = pet.name;
    meta.appendChild(link);

    const subtitleBits = [];
    if (pet.breed) subtitleBits.push(pet.breed);
    if (pet.diet_type) subtitleBits.push(pet.diet_type);
    if (pet.age_years !== null && pet.age_years !== undefined) {
      subtitleBits.push(`${pet.age_years} yrs`);
    }
    if (subtitleBits.length) {
      const subtitle = document.createElement("div");
      subtitle.className = "pet-subtitle";
      subtitle.textContent = subtitleBits.join(" · ");
      meta.appendChild(subtitle);
    }

    item.appendChild(meta);
    petList.appendChild(item);
  });
}

async function loadPets() {
  try {
    const response = await fetch("/pets", { credentials: "include" });
    if (!response.ok) {
      throw new Error("Unable to load pets.");
    }
    const pets = await response.json();
    petsCache = pets;
    renderPetList();
  } catch (error) {
    setPetStatus(error.message || "Unable to load pets.", true);
  }
}

if (petSearch) {
  petSearch.addEventListener("input", renderPetList);
}

loadPets();
