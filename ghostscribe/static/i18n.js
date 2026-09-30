// Translations for the web interface: one file per language in /static/locales/ with flat keys,
// {placeholder} parameters and _one/_other plural variants. Missing texts fall back to English.
const i18n = {
  language: "en",
  messages: {},
  fallback: {},

  async load(language) {
    const [messages, fallback] = await Promise.all(
      [language, "en"].map(async (code) => {
        const res = await fetch(`/static/locales/${code}.json`);
        return res.ok ? res.json() : {};
      })
    );
    this.language = language;
    this.messages = messages;
    this.fallback = fallback;
    document.documentElement.lang = language;
    this.apply(document);
    document.documentElement.classList.add("i18n-ready");
  },

  t(key, params = {}) {
    const lookup = (k) => this.messages[k] ?? this.fallback[k];
    let text = lookup(key);
    if ("count" in params) {
      const category = new Intl.PluralRules(this.language).select(params.count);
      text = lookup(`${key}_${category}`) ?? lookup(`${key}_other`) ?? text;
    }
    if (text === undefined) return key;
    return text.replace(/\{(\w+)\}/g, (match, name) => (name in params ? String(params[name]) : match));
  },

  // Translates every element with data-i18n (text), data-i18n-html (trusted markup) or data-i18n-<attribute>
  apply(root) {
    root.querySelectorAll("[data-i18n]").forEach((el) => {
      el.textContent = this.t(el.dataset.i18n);
    });
    root.querySelectorAll("[data-i18n-html]").forEach((el) => {
      el.innerHTML = DOMPurify.sanitize(this.t(el.dataset.i18nHtml));
    });
    for (const attr of ["placeholder", "title", "aria-label", "alt"]) {
      root.querySelectorAll(`[data-i18n-${attr}]`).forEach((el) => {
        el.setAttribute(attr, this.t(el.getAttribute(`data-i18n-${attr}`)));
      });
    }
    document.title = this.t("app.title");
  },

  date(value, options) {
    return new Date(value).toLocaleString(this.t("meta.locale"), options);
  },

  number(value, options) {
    return Number(value).toLocaleString(this.t("meta.locale"), options);
  },
};

const t = (key, params) => i18n.t(key, params);
