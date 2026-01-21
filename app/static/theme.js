const THEME_KEY = "theme";

function getPreferredTheme() {
  if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) {
    return "dark";
  }
  return "light";
}

function applyTheme(theme) {
  const resolved = theme === "dark" ? "dark" : "light";
  document.documentElement.setAttribute("data-theme", resolved);
  document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
    button.textContent = resolved === "dark" ? "Light mode" : "Dark mode";
  });
}

const storedTheme = localStorage.getItem(THEME_KEY);
applyTheme(storedTheme || getPreferredTheme());

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const current = document.documentElement.getAttribute("data-theme") || "light";
      const next = current === "dark" ? "light" : "dark";
      localStorage.setItem(THEME_KEY, next);
      applyTheme(next);
    });
  });
});
