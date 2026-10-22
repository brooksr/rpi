// BabySteps sidebar panel for Home Assistant (panel_custom). Shows the app the
// Pi serves on port 8080 in a full-height iframe, with HA's menu button on
// phones so the sidebar can still be opened. Override the address with
// `config: { url: ... }` in configuration.yaml.
class BabyStepsPanel extends HTMLElement {
  set hass(hass) {
    this._hass = hass;
    if (this._menu) this._menu.hass = hass;
  }

  set narrow(narrow) {
    this._narrow = narrow;
    this._render();
  }

  set panel(panel) {
    this._panel = panel;
    this._render();
  }

  connectedCallback() {
    this._render();
  }

  _render() {
    if (!this.isConnected) return;

    if (!this.shadowRoot) {
      const root = this.attachShadow({ mode: 'open' });
      root.innerHTML = `
        <style>
          :host { display: flex; flex-direction: column; height: 100%; background: var(--primary-background-color); }
          .toolbar { display: none; align-items: center; height: var(--header-height, 56px); padding: 0 4px;
                     background: var(--app-header-background-color, var(--primary-color));
                     color: var(--app-header-text-color, #fff); font-size: 20px; }
          :host([narrow]) .toolbar { display: flex; }
          .title { margin-left: 8px; }
          iframe { flex: 1; width: 100%; border: 0; }
        </style>
        <div class="toolbar"><ha-menu-button></ha-menu-button><span class="title">BabySteps</span></div>
        <iframe title="BabySteps" allow="clipboard-write; fullscreen"></iframe>`;
      this._menu = root.querySelector('ha-menu-button');
      this._frame = root.querySelector('iframe');
    }

    const url = this._panel?.config?.url || `${location.protocol}//${location.hostname}:8080/`;
    if (this._frame.getAttribute('src') !== url) this._frame.setAttribute('src', url);

    this.toggleAttribute('narrow', Boolean(this._narrow));
    this._menu.hass = this._hass;
    this._menu.narrow = this._narrow;
  }
}

customElements.define('babysteps-panel', BabyStepsPanel);
