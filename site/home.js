"use strict";

const sources = {
  phone: ["Телефон или гарнитура", "Открой приложение и нажми «Начать запись». Перед стартом проверь выбранный микрофон, а во время записи следи за уровнем входа."],
  device: ["Подключённый диктофон", "Сопряги совместимый диктофон с телефоном по Bluetooth. На Mac можно выбрать USB или Wi-Fi. Источник и состояние соединения видны на экране записи."],
  file: ["Уже есть аудиофайл", "На Mac перетащи запись в окно приложения. На телефоне выбери импорт из файлов. Исходное аудио можно открыть из библиотеки."]
};
const panel = document.querySelector(".source-panel");
const choices = Array.from(document.querySelectorAll("[data-source]"));
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");
for (const choice of choices) {
  choice.addEventListener("click", () => {
    const mode = choice.dataset.source;
    if (panel.dataset.mode === mode) return;
    const [title, copy] = sources[mode];
    panel.dataset.mode = mode;
    document.getElementById("source-title").textContent = title;
    document.getElementById("source-copy").textContent = copy;
    for (const item of choices) item.setAttribute("aria-pressed", String(item === choice));
    if (!reduceMotion.matches) {
      panel.querySelector(".source-description").animate([{opacity: .3, transform: "translateY(6px)"}, {opacity: 1, transform: "none"}], {duration: 240, easing: "ease-out"});
    }
  });
}
