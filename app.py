import os, threading, time, datetime, json, subprocess
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
from scanner import DiskScanner

import pygal
from pygal.style import DarkStyle

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")
RESULTS_DIR = "results"
CONFIG_FILE = "config.json"
os.makedirs(RESULTS_DIR, exist_ok=True)

tests_store = {}

def load_all_data():
    # Charger l'historique des scans
    for filename in os.listdir(RESULTS_DIR):
        if filename.endswith(".json"):
            try:
                with open(os.path.join(RESULTS_DIR, filename), 'r') as f:
                    data = json.load(f)
                    tests_store[data['id']] = data
            except: pass


def get_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except: pass
    # Valeurs par défaut si le fichier n'existe pas ou est corrompu
    return {"disks": [], "tests": ["smart"], "duration": 5}

load_all_data()

def save_test(tid):
    with open(os.path.join(RESULTS_DIR, f"{tid}.json"), 'w') as f:
        json.dump(tests_store[tid], f)

def run_benchmark_thread(tid, devices, tests, duration):
    t_obj = tests_store[tid]
    total_steps = len(devices) * len(tests)
    current_step = 0

    for dev in devices:
        t_obj["data"][dev] = {}
        for tk in tests:
            t_obj["current_op"] = f"{tk} sur {dev}"
            socketio.emit('progress_update', t_obj)
            
            res = {}
            try:
                if tk == "read":
                    cmd = ["sudo", "fio", "--name=read", f"--filename=/dev/{dev}", "--rw=read", "--bs=1M", "--direct=1", f"--runtime={duration}", "--time_based", "--output-format=json"]
                    out = json.loads(subprocess.check_output(cmd))
                    res = {"value": round(out['jobs'][0]['read']['bw_bytes']/1024/1024, 2), "unit": "Mo/s"}
                
                elif tk == "latency":
                    cmd = ["sudo", "fio", "--name=lat", f"--filename=/dev/{dev}", "--rw=randread", "--bs=4k", "--direct=1", f"--runtime={duration}", "--time_based", "--output-format=json"]
                    out = json.loads(subprocess.check_output(cmd))
                    res = {"value": round(out['jobs'][0]['read']['clat_ns']['mean']/1000000, 3), "unit": "ms"}
                
                elif tk == "smart":
                    res = DiskScanner.get_smart_data(dev)
                    # Pour le graph Pygal, on extrait une valeur numérique (ex: Temp ou Nb secteurs réalloués)
                    res["value"] = res.get("temp", 0) 
            
            except Exception as e: res["error"] = str(e)
            
            t_obj["data"][dev][tk] = res
            current_step += 1
            t_obj["progress"] = int((current_step / total_steps) * 100)
            socketio.emit('progress_update', t_obj)

    t_obj["status"] = "Finished"
    t_obj["progress"] = 100
    save_test(tid)
    socketio.emit('progress_update', t_obj)

@app.route("/")
def index():
    # On récupère la config pour pré-remplir le formulaire DailyCheck
    current_config = get_config()
    
    # On trie les tests par date décroissante pour l'affichage
    sorted_tests = dict(sorted(tests_store.items(), 
                              key=lambda x: x[1].get('timestamp', 0), 
                              reverse=True))
    return render_template("index.html", 
        disks=DiskScanner.get_topology(), 
        zfs=DiskScanner.get_zfs_details(),
        tests=sorted_tests,
        config=current_config)


@app.route("/start_test", methods=['POST'])
def start_test():
    req = request.json
    tid = f"scan_{int(time.time())}"
    tests_store[tid] = {
        "id": tid,
        "name": req.get('name') or tid,
        "status": "Running",
        "progress": 0,
        "data": {},
        "timestamp": time.time(),
        "date": datetime.datetime.now().strftime("%d/%m %H:%M"),
        "params": req # On garde les params pour savoir ce qu'on a testé
    }
    threading.Thread(target=run_benchmark_thread, 
                     args=(tid, req['disks'], req['tests'], int(req['duration']))).start()
    return jsonify({"id": tid})

@app.route("/get_charts")
def get_charts():
    """Génère les graphiques pour les tests cochés."""
    selected_ids = request.args.getlist('ids')
    chart_type = request.args.get('type', 'read') # 'read', 'latency' ou 'smart'
    
    line_chart = pygal.Line(style=DarkStyle, height=300, x_label_rotation=20)
    line_chart.title = f"Historique: {chart_type}"
    
    # On filtre les tests stockés
    active_tests = [tests_store[tid] for tid in selected_ids if tid in tests_store]
    active_tests.sort(key=lambda x: x.get('timestamp', 0))
    
    line_chart.x_labels = [t['date'] for t in active_tests]
    
    # On regroupe par disque
    disks = set()
    for t in active_tests: disks.update(t['data'].keys())
    
    for d in disks:
        values = []
        for t in active_tests:
            val = t['data'].get(d, {}).get(chart_type, {}).get('value', None)
            values.append(val)
        line_chart.add(d, values)
    
    return line_chart.render_response()


@app.route("/save_daily_config", methods=['POST'])
def save_daily_config():
    config = request.json
    with open(CONFIG_FILE, 'w') as f: json.dump(config, f)
    return jsonify({"status": "ok"})

@app.route("/get_config")
def route_get_config():
    return jsonify(get_config())

@app.route("/test_detail/<tid>")
def test_detail(tid):
    # 1. On cherche en mémoire (rapide)
    test = tests_store.get(tid)
    
    # 2. Si pas en mémoire, on tente de le charger depuis le disque (secours)
    if not test:
        file_path = os.path.join(RESULTS_DIR, f"{tid}.json")
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r') as f:
                    test = json.load(f)
                    tests_store[tid] = test  # On le remet en mémoire pour la prochaine fois
            except Exception as e:
                return f"Erreur de lecture du fichier : {e}", 500
    
    if not test:
        return "⚠️ Rapport introuvable. Il a peut-être été supprimé.", 404
    
    # Génération des graphiques Pygal spécifiques à ce test (Bar Chart)
    charts = {}
    if test.get('status') == 'Finished':
        for metric in ['read', 'latency']:
            chart = pygal.Bar(height=300, show_legend=False)
            chart.title = f"{metric.capitalize()} par disque"
            has_data = False
            for dev, res in test['data'].items():
                if metric in res and 'value' in res[metric]:
                    chart.add(dev, res[metric]['value'])
                    has_data = True
            if has_data:
                charts[metric] = chart.render_data_uri()

    return render_template("test_detail.html", test=test, charts=charts)

@app.route("/delete_test/<tid>", methods=['POST'])
def delete_test(tid):
    # Supprimer du dictionnaire en mémoire
    if tid in tests_store:
        del tests_store[tid]
    
    # Supprimer le fichier sur le disque
    file_path = os.path.join(RESULTS_DIR, f"{tid}.json")
    if os.path.exists(file_path):
        os.remove(file_path)
        
    return jsonify({"status": "deleted"})

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0')

