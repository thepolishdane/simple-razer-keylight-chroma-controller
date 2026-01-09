import socket
import time
import webbrowser
import os
import threading
import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

# --- CONFIG ---
PORT = 8000
RAZER_PORT = 10003
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "dual_settings.json")

def save_mem(data):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except: pass

def load_mem():
    """Robust loader: Handles old files or starts fresh if empty."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                # Fail-safe: If it's an old file format, migrate it once
                if "lights" not in data:
                    lights = {k: v for k, v in data.items() if k != "presets"}
                    data = {"lights": lights, "presets": data.get("presets", {})}
                return data
        except: pass
    return {"lights": {}, "presets": {}}

def build_packet(cmd_type, val1=0):
    header = bytearray.fromhex("aa00005f000000000000")
    if cmd_type == "REG": 
        payload = bytearray.fromhex("48004901d45d645125220853796e6170736533")
    elif cmd_type == "BRIGHT": 
        payload = bytearray.fromhex(f"0303030020{int(val1):02x}")
    elif cmd_type == "TEMP": 
        payload = bytearray.fromhex(f"0403010020{int(val1):04x}")
    
    packet = header + payload + bytearray(93 - len(payload))
    chk = 0
    for i in range(2, len(packet)): chk ^= packet[i]
    packet.extend([chk, 0x00])
    return packet

def talk_async(ip, b, t, on_state):
    try:
        target_b = b if on_state else 0
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5) 
            s.connect((ip, RAZER_PORT))
            s.sendall(bytearray.fromhex("aa000013020912022026010900110000401500"))
            s.recv(64)
            s.sendall(build_packet("REG"))
            s.recv(128)
            s.sendall(build_packet("BRIGHT", target_b * 2.55))
            time.sleep(0.04) 
            s.sendall(build_packet("TEMP", t))
    except: pass

HTML_HEAD = """
<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Studio Master V1.0</title>
<style>
    body { background: #0b0b0b; color: #00ff41; font-family: 'Segoe UI', sans-serif; display: flex; flex-direction: column; align-items: center; padding: 20px; }
    .lights-container { display: flex; justify-content: center; gap: 20px; flex-wrap: wrap; width: 100%; max-width: 1200px; margin-bottom: 40px; }
    .box { background: #1a1a1a; padding: 20px; border-radius: 12px; border: 1px solid #333; width: 280px; box-shadow: 0 8px 24px rgba(0,0,0,0.5); position: relative; }
    input[type=range] { width: 100%; accent-color: #00ff41; margin: 12px 0; cursor: pointer; }
    .is-off .sliders { opacity: 0.1; pointer-events: none; }
    label { font-size: 10px; color: #555; text-transform: uppercase; display: block; text-align: left; }
    .btn-group { display: flex; gap: 8px; margin-top: 15px; }
    button { padding: 10px; border: none; border-radius: 4px; cursor: pointer; font-weight: bold; transition: 0.1s; outline: none; }
    .btn-on { background: #00ff41; color: #000; flex: 1; }
    .btn-off { background: #444; color: #fff; flex: 1; }
    .is-off .btn-on { background: #222; color: #00ff41; border: 1px solid #333; }
    .is-off .btn-off { background: #ff4141; color: #fff; }
    .edit-row { margin-top: 15px; display: flex; gap: 5px; border-top: 1px solid #222; padding-top: 10px; align-items: center; }
    .edit-row input { background: #111; border: 1px solid #333; color: #888; padding: 6px; border-radius: 3px; font-size: 11px; }
    .preset-container { background: #111; border: 1px solid #222; border-radius: 12px; padding: 20px; width: 100%; max-width: 900px; }
    .preset-card { background: #1a1a1a; padding: 15px; border-radius: 8px; margin-bottom: 10px; display: flex; align-items: center; gap: 20px; position: relative; }
    .preset-info { flex: 1; }
    .preset-info strong { color: #00ff41; display: block; margin-bottom: 5px; text-transform: uppercase; font-size: 14px; letter-spacing: 1px; }
    .light-spec { font-size: 9px; color: #666; margin-bottom: 2px; }
    .del-btn { position: absolute; top: 10px; right: 10px; background: transparent; color: #333; font-size: 12px; border: none; cursor: pointer; }
    .copy-btn { background: #222; color: #00ff41; border: 1px solid #333; padding: 8px; border-radius: 4px; }
    .setup-area { margin-top: 50px; border-top: 1px solid #222; padding-top: 30px; display: flex; flex-direction: column; gap: 15px; align-items: center; }
    .status-dot { height: 6px; width: 6px; border-radius: 50%; display: inline-block; margin-right: 6px; }
</style></head><body>
<script>
    function updateUI(id) {
        document.getElementById('bv'+id).innerText = document.getElementById('b'+id).value+'%';
        document.getElementById('tv'+id).innerText = document.getElementById('t'+id).value+'K';
    }
    function transmit(id, pwr=null) {
        let b = document.getElementById('b'+id).value;
        let t = document.getElementById('t'+id).value;
        if(pwr !== null) document.getElementById('box'+id).classList.toggle('is-off', !pwr);
        fetch(`/set?id=${id}&b=${b}&t=${t}${pwr!==null?'&pwr='+pwr:''}`);
    }
    function copyUrl(name) {
        navigator.clipboard.writeText(window.location.origin + '/apply_preset?name=' + name);
        alert('Scene URL Copied');
    }
    function runPreset(name) { fetch('/apply_preset?name='+name).then(() => location.reload()); }
</script>
"""

class Server(BaseHTTPRequestHandler):
    def do_GET(self):
        mem = load_mem()
        if self.path == '/':
            self.send_response(200); self.send_header("Content-type", "text/html"); self.end_headers()
            html = HTML_HEAD
            if mem["lights"]:
                html += '<div class="lights-container">'
                sorted_keys = sorted(mem["lights"].keys(), key=lambda k: int(mem["lights"][k].get('order', 99)))
                for tid in sorted_keys:
                    l = mem["lights"][tid]; cls = "" if l['on'] else "is-off"
                    html += f'''<div class="box {cls}" id="box{tid}">
                        <button class="del-btn" onclick="if(confirm('Delete?')) location.href='/del?id={tid}'">✕</button>
                        <h3>{l['name']}</h3>
                        <div class="sliders">
                        <label>Brightness <span id="bv{tid}" style="color:#fff;font-weight:bold;float:right">{l['b']}%</span></label>
                        <input type="range" id="b{tid}" min="1" max="100" value="{l['b']}" oninput="updateUI('{tid}')" onchange="transmit('{tid}')">
                        <label>Warmth <span id="tv{tid}" style="color:#fff;font-weight:bold;float:right">{l['t']}K</span></label>
                        <input type="range" id="t{tid}" min="3000" max="7000" step="100" value="{l['t']}" oninput="updateUI('{tid}')" onchange="transmit('{tid}')">
                        </div><div class="btn-group">
                        <button class="btn-on" onclick="transmit('{tid}', true)">ON</button>
                        <button class="btn-off" onclick="transmit('{tid}', false)">OFF</button>
                        </div><div class="edit-row">
                        <input type="text" id="n{tid}" value="{l['name']}" style="flex:1;min-width:0">
                        <input type="number" id="o{tid}" value="{l['order']}" style="width:35px;text-align:center">
                        <button onclick="location.href='/meta?id={tid}&name='+encodeURIComponent(document.getElementById('n{tid}').value)+'&order='+document.getElementById('o{tid}').value" style="font-size:9px;background:#333;color:#fff;padding:6px 8px;border-radius:4px;">SET</button>
                        </div></div>'''
                html += '</div>'
                html += '<div class="preset-container"><h3>STUDIO SCENES</h3>'
                for p_name, p_data in mem["presets"].items():
                    html += f'''<div class="preset-card">
                        <button class="copy-btn" onclick="copyUrl('{p_name}')">📋</button>
                        <div class="preset-info"><strong>{p_name}</strong>'''
                    for lid, s in p_data.items():
                        lname = mem["lights"].get(lid, {}).get("name", "??")
                        dot = "#00ff41" if s.get('on', True) else "#ff4141"
                        html += f'<div class="light-spec"><span class="status-dot" style="background:{dot}"></span>{lname}: {s["b"]}% | {s["t"]}K</div>'
                    html += f'''</div><button onclick="runPreset('{p_name}')" style="background:#00ff41;color:#000;padding:10px 20px">GO</button>
                        <button onclick="if(confirm('Delete?')) location.href='/del_preset?name={p_name}'" style="background:#444;color:#fff;padding:10px">✕</button>
                    </div>'''
                html += f'''<div class="preset-card" style="border:1px dashed #333;background:transparent">
                    <input type="text" id="newP" placeholder="Snapshot Name..." style="background:#000;color:#fff;border:1px solid #333;padding:12px;border-radius:4px;flex:1">
                    <button onclick="location.href='/add_preset?name='+document.getElementById('newP').value" style="background:#00ff41;color:#000;padding:12px">+ SAVE CURRENT STATE</button>
                </div></div>'''
            html += '''<div class="setup-area">
                <div style="display:flex;gap:10px"><input type="text" id="newIp" placeholder="New Light IP..." style="background:#000;color:#00ff41;border:1px solid #333;padding:8px;border-radius:4px">
                <button onclick="location.href='/add?ip='+document.getElementById('newIp').value" style="background:#333;color:#fff">+ ADD LIGHT</button></div>
                <button onclick="if(confirm('Kill background process?')) fetch('/kill').then(()=>window.close())" style="background:transparent;color:#333;border:none;cursor:pointer;font-size:10px">KILL PY PROCESS</button>
            </div></body></html>'''
            self.wfile.write(html.encode())
        elif self.path.startswith('/add_preset'):
            q = parse_qs(urlparse(self.path).query); name = q.get('name', ['Scene'])[0].strip().replace(' ', '_')
            mem["presets"][name] = {lid: {"b": l["b"], "t": l["t"], "on": l["on"]} for lid, l in mem["lights"].items()}
            save_mem(mem); self.send_response(302); self.send_header('Location', '/'); self.end_headers()
        elif self.path.startswith('/apply_preset'):
            q = parse_qs(urlparse(self.path).query); p_name = q.get('name', [''])[0]
            if p_name in mem["presets"]:
                for lid, s in mem["presets"][p_name].items():
                    if lid in mem["lights"]:
                        threading.Thread(target=talk_async, args=(mem["lights"][lid]["ip"], s["b"], s["t"], s["on"])).start()
                        mem["lights"][lid].update({"on":s["on"], "b":s["b"], "t":s["t"]})
                save_mem(mem); self.send_response(200); self.end_headers()
        elif self.path.startswith('/set'):
            q = parse_qs(urlparse(self.path).query); tid, b, t, pwr = q.get('id',['1'])[0], int(q.get('b',[50])[0]), int(q.get('t',[5000])[0]), q.get('pwr', [None])[0]
            if pwr == 'false': mem["lights"][tid]['on'] = False
            elif pwr == 'true': mem["lights"][tid]['on'] = True
            threading.Thread(target=talk_async, args=(mem["lights"][tid]['ip'], b, t, mem["lights"][tid]['on'])).start()
            mem["lights"][tid].update({"b": b, "t": t}); save_mem(mem); self.send_response(200); self.end_headers()
        elif self.path.startswith('/add'):
            q = parse_qs(urlparse(self.path).query); ip = q.get('ip', [''])[0]
            if not any(l['ip'] == ip for l in mem["lights"].values()) and re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", ip):
                nid = str(max([int(k) for k in mem["lights"].keys()] + [0]) + 1)
                mem["lights"][nid] = {"ip":ip, "name":"New Light", "b":50, "t":5000, "on":True, "order":len(mem["lights"])+1}
                save_mem(mem)
            self.send_response(302); self.send_header('Location', '/'); self.end_headers()
        elif self.path.startswith('/del_preset'):
            q = parse_qs(urlparse(self.path).query); n = q.get('name', [''])[0]
            if n in mem["presets"]: del mem["presets"][n]; save_mem(mem)
            self.send_response(302); self.send_header('Location', '/'); self.end_headers()
        elif self.path.startswith('/meta'):
            q = parse_qs(urlparse(self.path).query); tid, name, order = q.get('id',['1'])[0], q.get('name',[''])[0], q.get('order',['1'])[0]
            mem["lights"][tid].update({"name": name, "order": int(order)}); save_mem(mem)
            self.send_response(302); self.send_header('Location', '/'); self.end_headers()
        elif self.path.startswith('/del'):
            q = parse_qs(urlparse(self.path).query); tid = q.get('id',[''])[0]
            if tid in mem["lights"]: del mem["lights"][tid]; save_mem(mem)
            self.send_response(302); self.send_header('Location', '/'); self.end_headers()
        elif self.path == '/kill': os._exit(0)
    def log_message(self, format, *args): return

if __name__ == '__main__':
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM); s.bind(('127.0.0.1', PORT))
        webbrowser.open(f'http://localhost:{PORT}'); HTTPServer(('0.0.0.0', PORT), Server).serve_forever()
    except: webbrowser.open(f'http://localhost:{PORT}'); os._exit(0)