# 💡 Simple Razer Keylight Chroma Controller

A professional-grade, lightweight, and background-running controller for Razer Keylights. This version features a modular architecture that separates the hardware engine from the visual dashboard, allowing for total UI customization and silent background operation.

---

### 🚀 Key Features

* **Modular Architecture:** UI is handled by `index.html`, Hardware Engine by `main.pyw`. Customize your dashboard look without touching the Python code.
* **Sequential Syncing:** Scenes apply to all lights reliably with a single click. No more "double-tapping" Stream Deck buttons.
* **Silent Startup:** Runs invisibly in the background via a `.vbs` script. No console windows or auto-opening browsers on boot.
* **Hardware Safety:** Strictly enforces a **15% Main LED cap** when the Chroma RGB panel is active to prevent hardware overheating.
* **High-Density Dashboard:** See status diodes, brightness, and Hex codes for all lights in a compact, single-line "Badge" view.

---

### 🛠 Installation & Setup

1.  **File Placement:** Place `main.pyw`, `index.html`, and `Silence.vbs` in the same project folder.
2.  **Startup Configuration:** * Press `Win + R`, type `shell:startup`, and hit **Enter**.
    * Right-click `Silence.vbs` in your project folder and select **Create Shortcut**.
    * Drag that shortcut into the opened Startup folder.
3.  **Manual Launch:** Double-click `Silence.vbs` to start the engine silently.
4.  **Dashboard Access:** Open your browser and go to `http://127.0.0.1:8000`.

---

### 🎮 Stream Deck Integration

1.  Set up your lights to your desired state and save a **Studio Scene**.
2.  Click the **📋 (Clipboard)** icon on the Scene card.
3.  In the Stream Deck software, add a **Website** or **Open URL** action.
4.  Paste the URL. It is hard-coded to `127.0.0.1` for maximum local reliability.

---

### 📂 File Overview

| File | Purpose |
| :--- | :--- |
| `main.pyw` | The Python Engine (Handles API & Hardware Communication) |
| `index.html` | The Dashboard UI (HTML/CSS/JS) |
| `dual_settings.json` | Local database for saved device IPs and Scenes |
| `Silence.vbs` | Truly invisible launcher script for background execution |

---

### ⚠️ Troubleshooting

* **White Screen on Load:** Ensure `index.html` is in the same folder as `main.pyw`.
* **Lights Not Responding:** Check the IP Management section at the bottom of the dashboard to ensure the IPs match your devices.
* **Port Conflict:** If port `8000` is used by another app, change the `PORT` variable at the top of `main.pyw`.

---
*Created with Google Gemini and ThePolishDane
