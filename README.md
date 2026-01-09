# 💡 Simple Razer Keylight Chroma Controller (V1.0)

A lightweight, high-performance Python controller designed specifically for the **Razer Key Light Chroma**. This tool replaces Razer Synapse with a fast, web-based dashboard and seamless Stream Deck integration.

*Developed in partnership with Gemini AI.*

---

## 🚀 Why use this instead of Synapse?
* **Zero Bloat:** Uses almost 0% CPU and minimal RAM compared to the full Razer suite.
* **Fast:** Instant hardware response for brightness and warmth changes.
* **Room Snapshots:** Save your entire studio setup (Brightness, Warmth, and Power state) as a "Scene" and trigger it with one button.
* **Stream Deck Native:** Built-in "Copy URL" functionality for easy use with plugins like **BarRaider's API Ninja**.

---

## 🛠️ Setup Instructions

### 1. Get your Light IPs
Use the Razer software one last time to pair your lights with your Wi-Fi. Find the IP addresses assigned to your lights (usually found in your router settings or Razer's software). Once you have the IPs, you can uninstall Synapse.

### 2. Launch the Controller
1. **Install Python:** Make sure you have [Python](https://www.python.org/) installed on Windows.
2. **Run:** Double-click `light_control.pyw`. 
   * A background process will start.
   * A browser window will open automatically. 
   * *Tip: Bookmark `http://localhost:8000` to access the controls anytime.*

### 3. Windows Startup (Recommended)
To ensure your Stream Deck buttons always work:
1. Press `Win + R`, type `shell:startup`, and hit Enter.
2. Right-click your `light_control.pyw` file and select **Create Shortcut**.
3. Drag that shortcut into the Startup folder.

---

## ⌨️ Stream Deck Integration

1. Create a **Scene** in the dashboard (e.g., `Focus_Mode` or `Stream_Start`).
2. Click the 📋 **Copy** icon next to the Scene name to copy the API URL.
3. In your Stream Deck software, use a web request plugin (like **API Ninja**).
4. Paste the URL into the plugin settings. 

---

## 🏗️ Project Roadmap
- [x] Full Brightness & Warmth Control
- [x] Scene Snapshots (On/Off + Settings for all lights)
- [x] Duplicate IP Protection
- [x] Stream Deck Copy-to-Clipboard URL feature
- [ ] **Chroma RGB Panel Control** (Planned for next update)

---

### Credits
Created by the community for the community.
