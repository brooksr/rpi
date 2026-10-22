// Load the local LCARS font on built-in dashboards and Settings as well.
if (!document.getElementById("lcars-antonio-font")) {
  const style = document.createElement("style");
  style.id = "lcars-antonio-font";
  style.textContent = `
    @font-face {
      font-family: Antonio;
      font-style: normal;
      font-weight: 400;
      font-display: swap;
      src: url('/local/community/lcars/antonio-400.ttf') format('truetype');
    }
    @font-face {
      font-family: Antonio;
      font-style: normal;
      font-weight: 700;
      font-display: swap;
      src: url('/local/community/lcars/antonio-700.ttf') format('truetype');
    }
  `;
  document.head.appendChild(style);
}
