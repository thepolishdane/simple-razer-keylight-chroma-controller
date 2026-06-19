import socket, time, os, sys, threading, json, queue, logging
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, parse_qs

# --- CONFIG ---
PORT = 8000
HOST = "127.0.0.1"          # local-only: dashboard + Stream Deck both hit 127.0.0.1
RAZER_PORT = 10003
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

CONFIG_FILE = os.path.join(BASE_DIR, "dual_settings.json")
HTML_FILE = os.path.join(BASE_DIR, "index.html")
LOG_FILE = os.path.join(BASE_DIR, "razer_controller.log")

logging.basicConfig(
    filename=LOG_FILE, level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("razer")

# Serializes all config reads/writes so rapid Stream Deck presses can't
# interleave a load->mutate->save and clobber each other (lost update).
CONFIG_LOCK = threading.RLock()

# Global storage for per-light queues and threads
light_workers = {}

# Heartbeat: touch every light on this interval so its WiFi radio never drops
# into low-power sleep. A sleeping radio ignores the first connection, which is
# the root cause of "the light sometimes stops reacting / won't turn off".
# Keep this comfortably below the light's idle-sleep timeout (~60s observed).
HEARTBEAT_INTERVAL = 30  # seconds
# Per-attempt backoff for waking a sleeping light. A deep-asleep radio needs a
# few seconds to come up, so the gaps widen instead of three quick 0.2s tries.
RETRY_BACKOFF = (0.3, 0.6, 1.0, 1.5)  # len+1 == total attempts

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    # NOT allow_reuse_address: we WANT a second instance to fail to bind so it
    # can't run as a silent duplicate fighting over the same port.
    allow_reuse_address = False

def already_running():
    """True if another instance already owns the control port."""
    try:
        with socket.create_connection((HOST, PORT), timeout=0.5):
            return True
    except OSError:
        return False

def load_mem():
    with CONFIG_LOCK:
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
            except Exception:
                log.exception("Failed to load config; falling back to empty.")
        return data

def save_mem(data):
    with CONFIG_LOCK:
        try:
            # Atomic write: never leave a half-written config if killed mid-save.
            tmp = CONFIG_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f, indent=4)
            os.replace(tmp, CONFIG_FILE)
        except Exception:
            log.exception("Failed to save config.")

def build_pkt(cmd, val=0, rgb=None):
    h = bytearray.fromhex("aa00005f000000000000")
    p = bytearray()
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

def _send_state(ip, state):
    """Open one socket and push the full command set. Raises on any failure."""
    m_b = min(state['b'], 15) if state['con'] else state['b']
    main_v = (m_b * 2.55) if state['on'] else 0
    chr_v = (state['cb'] * 2.55) if state['con'] else 0
    rgb = tuple(int(state['chx'].lstrip('#')[i:i+2], 16) for i in (0, 2, 4))

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(2.0)
        s.connect((ip, RAZER_PORT))
        s.sendall(bytearray.fromhex("aa000013020912022026010900110000401500")); s.recv(64)
        s.sendall(build_pkt("REG")); s.recv(64)
        s.sendall(build_pkt("BRIGHT", main_v)); time.sleep(0.05)
        s.sendall(build_pkt("TEMP", state.get('t', 5000))); time.sleep(0.05)
        s.sendall(build_pkt("C_BRIGHT", chr_v)); time.sleep(0.05)
        s.sendall(build_pkt("C_RGB", rgb=rgb)); time.sleep(0.05)

def light_worker_thread(ip, q):
    """Dedicated thread for a single light IP."""
    while True:
        state = q.get()
        if state is None: break  # Shutdown signal
        # Retry: a WiFi keylight that has dropped into low-power sleep ignores
        # the first connection (and pings) but the attempt wakes its radio.
        # Without this the first button press silently does nothing and the
        # user has to press again -- the "not always responsive" bug.
        last_err = None
        for attempt in range(len(RETRY_BACKOFF) + 1):
            try:
                _send_state(ip, state)
                last_err = None
                break
            except Exception as e:
                last_err = e
                if attempt < len(RETRY_BACKOFF):
                    time.sleep(RETRY_BACKOFF[attempt])
        if last_err is not None:
            log.warning("Light %s unreachable after %d attempts: %s",
                        ip, len(RETRY_BACKOFF) + 1, last_err)
        q.task_done()
        time.sleep(0.02)  # Small internal cooldown for this specific light

def _poke(ip):
    """Gentle keep-warm on the control port. We complete a proper hello exchange
    (connect -> send the standard hello packet -> read the reply -> clean close)
    rather than a bare connect-and-drop: an abrupt half-open connection can wedge
    a fragile light's single-connection control server. Sends no state commands,
    so it never changes the light. Matches the handshake monitor_lights.py uses."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2.0)
            s.connect((ip, RAZER_PORT))
            s.sendall(bytearray.fromhex("aa000013020912022026010900110000401500"))
            s.recv(64)
        return True
    except Exception:
        return False

def heartbeat_thread():
    """Keep every configured light's radio awake on a fixed interval."""
    while True:
        time.sleep(HEARTBEAT_INTERVAL)
        try:
            for l in load_mem().get("lights", {}).values():
                ip = l.get("ip")
                if ip: _poke(ip)
        except Exception:
            log.exception("Heartbeat cycle failed")

def dispatch(light_id, state):
    """Send a state update to the correct light worker."""
    ip = state.get('ip')
    if not ip: return
    if ip not in light_workers:
        q = queue.Queue()
        t = threading.Thread(target=light_worker_thread, args=(ip, q), daemon=True)
        t.start()
        light_workers[ip] = q

    # Clear the queue of old pending actions for this specific light so it's snappy
    while not light_workers[ip].empty():
        try: light_workers[ip].get_nowait(); light_workers[ip].task_done()
        except queue.Empty: break

    light_workers[ip].put(state)

class Server(BaseHTTPRequestHandler):
    def do_GET(self):
        # One lock for the whole request: serializes config access, and a bad
        # query param logs + returns 500 instead of silently killing the thread.
        try:
            with CONFIG_LOCK:
                self.handle_request()
        except Exception:
            log.exception("Request failed: %s", self.path)
            try:
                self.send_response(500); self.end_headers()
            except Exception:
                pass

    def handle_request(self):
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
            tid = q['id'][0]; l = mem["lights"][tid]; ic = q['cpwr'][0]=='true' if 'cpwr' in q else l.get('con', False)
            l.update({"b": min(int(q['b'][0]), 15) if ic else int(q['b'][0]), "t":int(q['t'][0]), "cb":int(q['cb'][0]), "chx":"#"+q['hex'][0]})
            if 'pwr' in q: l['on'] = q['pwr'][0] == 'true'
            if 'cpwr' in q: l['con'] = q['cpwr'][0] == 'true'
            save_mem(mem); dispatch(tid, l.copy()); self.send_response(200); self.end_headers()
        elif p.path == '/add_preset':
            n = q.get('name',[''])[0].strip().replace(' ','_') or f"Scene_{len(mem['presets'])+1}"; mem["presets"][n] = {lid: {k:v for k,v in l.items() if k not in ['ip','name','order']} for lid,l in mem["lights"].items()}; save_mem(mem); self.redirect()
        elif p.path == '/apply_preset':
            n = q.get('name',[''])[0]
            if n in mem["presets"]:
                for lid, s in mem["presets"][n].items():
                    if lid in mem["lights"]:
                        mem["lights"][lid].update(s); dispatch(lid, mem["lights"][lid].copy())
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
            dispatch(tid, mem["lights"][tid].copy()); save_mem(mem); self.redirect()
        elif p.path == '/kill': os._exit(0)
        else:
            self.send_response(404); self.end_headers()

    def redirect(self): self.send_response(302); self.send_header('Location','/'); self.end_headers()
    def log_message(self, format, *args): return

if __name__ == '__main__':
    # Single-instance guard: if another copy already owns the port, quietly exit.
    # Stops a double-launch (or a login while an old copy lingers) from leaving
    # two servers fighting over the same lights.
    if already_running():
        log.info("Another instance already owns %s:%s -- exiting this one.", HOST, PORT)
        sys.exit(0)
    try:
        server = ThreadedHTTPServer((HOST, PORT), Server)
    except OSError as e:
        log.error("Could not bind %s:%s (%s) -- assuming another instance. Exiting.", HOST, PORT, e)
        sys.exit(0)
    log.info("Razer controller started on http://%s:%s", HOST, PORT)
    threading.Thread(target=heartbeat_thread, daemon=True).start()
    log.info("Heartbeat keep-alive running every %ss", HEARTBEAT_INTERVAL)
    server.serve_forever()
