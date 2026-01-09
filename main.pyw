import socket, time, os, threading, json, queue
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

# --- CONFIG ---
PORT = 8000
RAZER_PORT = 10003
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR) 

CONFIG_FILE = os.path.join(BASE_DIR, "dual_settings.json")
HTML_FILE = os.path.join(BASE_DIR, "index.html")

# We use a Lock to ensure only one light is being talked to at a exact millisecond
hardware_lock = threading.Lock()
latest_states, cmd_queue = {}, queue.Queue()

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads, allow_reuse_address = True, True

def load_mem():
    data = {"lights": {}, "presets": {}}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                for lid in data.get("lights", {}):
                    l = data["lights"][lid]
                    for k, v in [("b", 50), ("t", 5000), ("cb", 50), ("chx", "#00ff41"), ("con", False), ("on", True), ("order", 0)]:
                        if k not in l: l[k] = v
                return data
        except: pass
    return data

def save_mem(data):
    try:
        with open(CONFIG_FILE, "w") as f: json.dump(data, f, indent=4)
    except: pass

def build_pkt(cmd, val=0, rgb=None):
    h = bytearray.fromhex("aa00005f000000000000")
    if cmd == "REG": p = bytearray.fromhex("48004901d45d645125220853796e6170736533")
    elif cmd == "BRIGHT": p = bytearray.fromhex(f"0303030020{int(val):02x}")
    elif cmd == "TEMP": p = bytearray.fromhex(f"0403010020{int(val):04x}")
    elif cmd == "C_BRIGHT": p = bytearray.fromhex(f"030f040000{int(val):02x}")
    elif cmd == "C_RGB":
        r, g, b = rgb
        p = bytearray.fromhex(f"0c0f02010501000001{r:02x}{g:02x}{b:02x}")
    pkt = h + p + bytearray(93 - len(p))
    chk = 0
    for i in range(2, len(pkt)): chk ^= pkt[i]
    pkt.extend([chk, 0x00])
    return pkt

def worker():
    while True:
        tid = cmd_queue.get()
        l = latest_states.get(tid)
        if not l or 'ip' not in l: 
            cmd_queue.task_done(); continue
        
        # Use the lock to prevent overlapping socket connections
        with hardware_lock:
            try:
                m_b = min(l['b'], 15) if l['con'] else l['b']
                main_v, chr_v = (m_b * 2.55) if l['on'] else 0, (l['cb'] * 2.55) if l['con'] else 0
                rgb = tuple(int(l['chx'].lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
                
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(1.5) # Increased timeout for reliability
                    s.connect((l['ip'], RAZER_PORT))
                    s.sendall(bytearray.fromhex("aa000013020912022026010900110000401500")); s.recv(64)
                    s.sendall(build_pkt("REG")); s.recv(64)
                    s.sendall(build_pkt("BRIGHT", main_v)); time.sleep(0.06) # Slightly longer breathers
                    s.sendall(build_pkt("TEMP", l.get('t', 5000))); time.sleep(0.06)
                    s.sendall(build_pkt("C_BRIGHT", chr_v)); time.sleep(0.06)
                    s.sendall(build_pkt("C_RGB", rgb=rgb))
                    time.sleep(0.1) # Cool-down period for the hardware
            except: pass
            
        cmd_queue.task_done()
        time.sleep(0.05)

threading.Thread(target=worker, daemon=True).start()

class Server(BaseHTTPRequestHandler):
    def do_GET(self):
        mem = load_mem(); p = urlparse(self.path); q = parse_qs(p.query)
        if p.path == '/':
            self.send_response(200); self.send_header("Content-type", "text/html"); self.end_headers()
            content = '<div class="lights-container">'
            sorted_l = sorted(mem["lights"].items(), key=lambda x: x[1].get('order', 0))
            for tid, l in sorted_l:
                is_c = l.get('con', False); h = l['chx'].lstrip('#'); rgb = [int(h[i:i+2], 16) for i in (0, 2, 4)]
                content += f'''<div class="box {'is-off' if not l['on'] else ''} {'is-chroma-off' if not is_c else ''}" id="box{tid}">
                    <h3 style="margin:0 0 15px 0">{l['name']}</h3>
                    <div class="ctrl-main">
                        <span class="section-label">Main LED</span>
                        <label>Brightness <b id="bv{tid}" style="float:right">{l['b']}%</b></label>
                        <input type="range" id="b{tid}" min="1" max="100" value="{l['b']}" oninput="updateUI('{tid}',{str(is_c).lower()})" onchange="transmit('{tid}','main')">
                        <label>Temp <b id="tv{tid}" style="float:right; font-size:9px">{l['t']}K</b></label>
                        <input type="range" id="t{tid}" min="3000" max="7000" step="100" value="{l['t']}" oninput="updateUI('{tid}',{str(is_c).lower()})" onchange="transmit('{tid}','main')">
                    </div>
                    <div class="btn-group"><button class="btn-on {'active-on' if l['on'] else ''}" onclick="transmit('{tid}','main',true)">ON</button><button class="btn-on {'active-off' if not l['on'] else ''}" onclick="transmit('{tid}','main',false)">OFF</button></div>
                    <div class="chroma-area">
                        <span class="section-label">Chroma RGB</span>
                        <div class="ctrl-chroma">
                            <div class="rgb-row"><div class="rgb-sliders">
                                <input type="range" id="r{tid}" min="0" max="255" value="{rgb[0]}" style="accent-color:#f44" oninput="updateUI('{tid}',true)" onchange="transmit('{tid}','chroma')">
                                <input type="range" id="g{tid}" min="0" max="255" value="{rgb[1]}" style="accent-color:#4f4" oninput="updateUI('{tid}',true)" onchange="transmit('{tid}','chroma')">
                                <input type="range" id="bl{tid}" min="0" max="255" value="{rgb[2]}" style="accent-color:#44f" oninput="updateUI('{tid}',true)" onchange="transmit('{tid}','chroma')">
                            </div><div class="swatch" id="swatch{tid}" style="background:#{h}"></div></div>
                            <label style="font-size:10px; margin-top:10px; display:block">Brightness <b id="cbv{tid}" style="float:right">{l['cb']}%</b></label>
                            <input type="range" id="cb{tid}" min="1" max="100" value="{l['cb']}" oninput="updateUI('{tid}',true)" onchange="transmit('{tid}','chroma')">
                        </div>
                        <div class="btn-group"><button class="btn-on {'active-chroma-on' if is_c else ''}" onclick="transmit('{tid}','chroma',true)">ON</button><button class="btn-on {'active-off' if not is_c else ''}" onclick="transmit('{tid}','chroma',false)">OFF</button></div>
                    </div>
                </div><script>updateUI('{tid}', {str(is_c).lower()});</script>'''
            content += '</div>'
            if mem["lights"]:
                content += '<div class="preset-container"><h3>Studio Scenes</h3>'
                for pn, pd in mem["presets"].items():
                    content += f'<div class="preset-card"><div style="flex:1"><strong style="color:#00ff41; display:block; margin-bottom:5px;">{pn.replace("_"," ")}</strong>'
                    for lid, s in pd.items():
                        ln = mem["lights"].get(lid, {}).get("name", "?")
                        content += f'<div class="badge"><span class="diode {"on" if s.get("on") else "off"}"></span> <b>{ln}</b> {s.get("b")}% | {s.get("t")}K <span style="color:#444">|</span> <span class="diode {"on" if s.get("con") else "off"}"></span> {s.get("cb")}% <span style="color:{s.get("chx")}; font-family:monospace;">{s.get("chx","").upper()}</span></div>'
                    content += f'</div><div style="display:flex; gap:5px;"><button onclick="copyUrl(\'{pn}\')" style="background:#222;color:#00ff41;width:35px">📋</button><button onclick="location.href=\'/apply_preset?name={pn}\'" style="background:#00ff41;color:#000;width:60px">GO</button><button onclick="location.href=\'/del_preset?name={pn}\'" style="background:#411;color:#f44;width:30px">×</button></div></div>'
                content += f'<div class="preset-card" style="background:transparent;border:1px dashed #444"><input type="text" id="nP" placeholder="Name..." style="flex:1"><button onclick="location.href=\'/add_preset?name=\'+document.getElementById(\'nP\').value" style="background:#00ff41;color:#000;width:120px">+ SAVE</button></div></div>'
            content += '<div class="setup-area"><span class="section-label">Setup (IP Management)</span>'
            for tid, l in sorted_l:
                content += f'''<div style="display:flex;gap:5px;margin-bottom:8px">
                    <button onclick="location.href='/move?id={tid}&dir=up'" style="width:30px;background:#333;color:#fff">←</button>
                    <button onclick="location.href='/move?id={tid}&dir=down'" style="width:30px;background:#333;color:#fff">→</button>
                    <input type="text" value="{l["name"]}" onchange="location.href='/ren?id={tid}&n='+this.value" style="flex:1">
                    <div style="background:#000; padding:10px; border-radius:4px; font-size:10px; color:#555; min-width:100px; text-align:center;">{l['ip']}</div>
                    <button onclick="location.href='/del?id={tid}'" style="background:#411;color:#f44;width:30px">×</button>
                </div>'''
            content += f'<div style="display:flex;gap:10px;margin-top:20px"><input type="text" id="aN" placeholder="Name" style="flex:1"><input type="text" id="aI" placeholder="IP" style="flex:1"><button onclick="location.href=\'/add?n=\'+document.getElementById(\'aN\').value+\'&ip=\'+document.getElementById(\'aI\').value" style="background:#333;color:#fff;width:80px">ADD</button></div>'
            content += '<center style="margin-top:30px"><a href="/kill" style="color:#444;text-decoration:none;font-size:10px">EXIT APPLICATION</a></center></div>'
            with open(HTML_FILE, 'r', encoding='utf-8') as f:
                template = f.read()
            self.wfile.write(template.replace("{{CONTENT}}", content).encode())

        elif p.path == '/set':
            tid = q['id'][0]; l = mem["lights"][tid]; ic = q['cpwr'][0]=='true' if 'cpwr' in q else l['con']
            l.update({"b": min(int(q['b'][0]), 15) if ic else int(q['b'][0]), "t":int(q['t'][0]), "cb":int(q['cb'][0]), "chx":"#"+q['hex'][0]})
            if 'pwr' in q: l['on'] = q['pwr'][0] == 'true'
            if 'cpwr' in q: l['con'] = q['cpwr'][0] == 'true'
            save_mem(mem); latest_states[tid] = l.copy(); cmd_queue.put(tid); self.send_response(200); self.end_headers()
        elif p.path == '/add_preset':
            n = q.get('name',[''])[0].strip().replace(' ','_') or f"Scene_{len(mem['presets'])+1}"; mem["presets"][n] = {lid: {k:v for k,v in l.items() if k not in ['ip','name','order']} for lid,l in mem["lights"].items()}; save_mem(mem); self.redirect()
        elif p.path == '/apply_preset':
            n = q.get('name',[''])[0]
            if n in mem["presets"]:
                for lid, s in mem["presets"][n].items():
                    if lid in mem["lights"]: 
                        mem["lights"][lid].update(s); latest_states[lid]=mem["lights"][lid].copy(); cmd_queue.put(lid)
                save_mem(mem)
            self.redirect()
        elif p.path == '/del_preset':
            n = q.get('name',[''])[0]; (mem["presets"].pop(n, None) if n in mem["presets"] else None); save_mem(mem); self.redirect()
        elif p.path == '/move':
            tid = q['id'][0]; d = q['dir'][0]; lights = sorted(mem["lights"].items(), key=lambda x: x[1].get('order', 0)); idx = next(i for i, v in enumerate(lights) if v[0] == tid)
            if d=='up' and idx>0: lights[idx][1]['order'], lights[idx-1][1]['order'] = lights[idx-1][1]['order'], lights[idx][1]['order']
            elif d=='down' and idx<len(lights)-1: lights[idx][1]['order'], lights[idx+1][1]['order'] = lights[idx+1][1]['order'], lights[idx][1]['order']
            save_mem(mem); self.redirect()
        elif p.path == '/ren': mem["lights"][q['id'][0]]['name'] = q['n'][0]; save_mem(mem); self.redirect()
        elif p.path == '/del': del mem["lights"][q['id'][0]]; save_mem(mem); self.redirect()
        elif p.path == '/add':
            tid = str(int(time.time()))
            mem["lights"][tid] = {"name":q.get('n',[''])[0] or f"L{len(mem['lights'])+1}","ip":q.get('ip',[''])[0],"b":50,"t":5000,"on":True,"cb":50,"chx":"#00ff41","con":False,"order":len(mem['lights'])}
            latest_states[tid] = mem["lights"][tid].copy(); save_mem(mem); self.redirect()
        elif p.path == '/kill': os._exit(0)

    def redirect(self): self.send_response(302); self.send_header('Location','/'); self.end_headers()
    def log_message(self, format, *args): return

if __name__ == '__main__':
    ThreadedHTTPServer(('0.0.0.0', PORT), Server).serve_forever()