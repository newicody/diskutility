import os
import threading
import time
import datetime
import json
import subprocess
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
from scanner import DiskScanner
import pygal
import psutil
from pygal.style import LightStyle
import logging

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

RESULTS_DIR = "results"
CONFIG_FILE = "config.json"
NOTES_FILE = "disk_notes.json"

os.makedirs(RESULTS_DIR, exist_ok=True)

tests_store = {}
zfs_tests_store = {}
parity_store = {}
snapshot_store = {}

# Configuration du logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_last_health_status():
    """Analyse les tests existants pour définir l'état actuel des disques"""
    health_map = {}
    sorted_tests = sorted(tests_store.values(), key=lambda x: x['timestamp'], reverse=True)
    
    for test in sorted_tests:
        if 'data' in test:
            for dev, results in test['data'].items():
                if dev not in health_map:
                    has_error = results.get('smart', {}).get('critical_alerts', [])
                    health_map[dev] = "🔴" if has_error else "🟢"
    return health_map

def emit_sys_stats():
    """Émet les statistiques système en temps réel"""
    while True:
        try:
            io = psutil.disk_io_counters()
            if io:
                stats = {
                    "users": len(psutil.users()),
                    "io": f"{(io.read_bytes + io.write_bytes) / 1024 / 1024:.1f} MB/s",
                    "sessions": len(tests_store)
                }
            else:
                stats = {"users": 0, "io": "0.0 MB/s", "sessions": 0}
            socketio.emit('sys_stats', stats)
        except Exception as e:
            logger.error(f"Erreur stats système: {e}")
        time.sleep(2)

threading.Thread(target=emit_sys_stats, daemon=True).start()

def save_stores():
    """Sauvegarde tous les stores dans des fichiers JSON"""
    try:
        with open('tests_store.json', 'w') as f:
            json.dump(tests_store, f, indent=2)
        with open('zfs_tests_store.json', 'w') as f:
            json.dump(zfs_tests_store, f, indent=2)
    except Exception as e:
        logger.error(f"Erreur sauvegarde stores: {e}")

def finalize_test(test_id, report, is_zfs):
    """Finalise un test et sauvegarde les résultats"""
    if is_zfs:
        zfs_tests_store[test_id] = report
        logger.info(f"Rapport ZFS enregistré: {test_id}")
    else:
        tests_store[test_id] = report
        logger.info(f"Rapport Disque enregistré: {test_id}")
    
    save_stores()
    socketio.emit('progress_update', {
        'id': test_id,
        'status': 'Finished',
        'progress': 100
    })

def load_all_data():
    """Charge tous les tests depuis les fichiers"""
    tests_store.clear()
    for filename in os.listdir(RESULTS_DIR):
        if filename.endswith(".json"):
            try:
                with open(os.path.join(RESULTS_DIR, filename), 'r') as f:
                    data = json.load(f)
                    tests_store[data['id']] = data
            except Exception as e:
                logger.error(f"Erreur chargement {filename}: {e}")

def get_config():
    """Récupère la configuration DailyCheck"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {"disks": [], "tests": ["smart"], "duration": 30, "zfs_scrub": False, "zfs_perf": False}

load_all_data()

def save_test(tid):
    """Sauvegarde un test spécifique"""
    if tid in tests_store:
        try:
            with open(os.path.join(RESULTS_DIR, f"{tid}.json"), 'w') as f:
                json.dump(tests_store[tid], f, indent=2)
        except Exception as e:
            logger.error(f"Erreur sauvegarde test {tid}: {e}")

def run_smart_scan(dev):
    """Exécute un scan SMART sur un périphérique"""
    return DiskScanner.get_smart_data(dev)

def run_read_benchmark(dev, duration, is_zfs=False):
    """Exécute un benchmark de lecture"""
    try:
        if is_zfs:
            cmd = ["fio", "--name=read_test", f"--directory={dev}", "--size=1G", 
                   "--rw=read", "--bs=1M", "--iodepth=32", "--output-format=json"]
        else:
            cmd = ["sudo", "fio", "--name=read_test", f"--filename=/dev/{dev}", 
                   "--rw=read", "--bs=1M", "--direct=1", f"--runtime={duration}", 
                   "--time_based", "--output-format=json"]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=duration+120)
        if result.returncode != 0:
            return {"error": f"FIO error: {result.stderr}"}
        
        out = json.loads(result.stdout)
        bw = out['jobs'][0]['read']['bw_bytes'] / 1024 / 1024
        return {"value": round(bw, 2), "unit": "Mo/s"}
    except Exception as e:
        return {"error": str(e)}

def run_latency_benchmark(dev, duration, is_zfs=False):
    """Exécute un benchmark de latence"""
    try:
        if is_zfs:
            cmd = ["fio", "--name=latency_test", f"--directory={dev}", "--size=1G",
                   "--rw=randread", "--bs=4k", "--iodepth=1", "--output-format=json"]
        else:
            cmd = ["sudo", "fio", "--name=latency_test", f"--filename=/dev/{dev}",
                   "--rw=randread", "--bs=4k", "--direct=1", f"--runtime={duration}",
                   "--time_based", "--output-format=json"]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=duration+120)
        if result.returncode != 0:
            return {"error": f"FIO error: {result.stderr}"}
        
        out = json.loads(result.stdout)
        latency = out['jobs'][0]['read']['clat_ns']['mean'] / 1000000  # Conversion en ms
        return {"value": round(latency, 3), "unit": "ms"}
    except Exception as e:
        return {"error": str(e)}

def run_zfs_scrub(pool_name):
    """Exécute un scrub ZFS"""
    try:
        result = subprocess.run(["sudo", "zpool", "scrub", pool_name], 
                               capture_output=True, text=True)
        if result.returncode == 0:
            return {"status": "started", "message": f"Scrub démarré sur {pool_name}"}
        else:
            return {"error": result.stderr}
    except Exception as e:
        return {"error": str(e)}

def run_benchmark_thread(tid, payload):
    """Thread principal d'exécution des benchmarks"""
    try:
        t_obj = tests_store[tid]
        devices = payload.get('targets') or payload.get('disks', [])
        tests = payload.get('test_types') or payload.get('tests', [])
        duration = int(payload.get('duration', 30))
        is_zfs = payload.get('is_zfs', False)
        
        total_steps = len(devices) * len(tests)
        current_step = 0

        for dev in devices:
            t_obj["data"][dev] = {}
            
            # Nettoyer le nom du périphérique
            if dev.startswith('/dev/'):
                dev_clean = dev.replace('/dev/', '')
            else:
                dev_clean = dev

            for test_type in tests:
                t_obj["current_op"] = f"{test_type} sur {dev_clean}"
                socketio.emit('progress_update', t_obj)

                try:
                    if test_type == "smart":
                        result = run_smart_scan(dev_clean)
                        # Ajouter une valeur numérique pour les graphiques
                        if 'temp' in result and result['temp'] != 'N/A':
                            result["value"] = float(result['temp'])
                        else:
                            result["value"] = 0

                    elif test_type == "read":
                        result = run_read_benchmark(dev_clean, duration, is_zfs)

                    elif test_type == "latency":
                        result = run_latency_benchmark(dev_clean, duration, is_zfs)

                    elif test_type == "zfs_scrub" and is_zfs:
                        pool_name = dev_clean.split('/')[0] if '/' in dev_clean else dev_clean
                        result = run_zfs_scrub(pool_name)

                    elif test_type == "zfs_perf" and is_zfs:
                        result = run_read_benchmark(dev_clean, duration, True)

                    else:
                        result = {"error": f"Type de test inconnu: {test_type}"}

                except Exception as e:
                    result = {"error": str(e)}
                    logger.error(f"Erreur benchmark {dev_clean}/{test_type}: {e}")

                t_obj["data"][dev][test_type] = result
                current_step += 1
                t_obj["progress"] = int((current_step / total_steps) * 100)
                socketio.emit('progress_update', t_obj)

        t_obj["status"] = "Finished"
        t_obj["progress"] = 100
        save_test(tid)
        socketio.emit('progress_update', t_obj)

    except Exception as e:
        logger.error(f"Erreur thread benchmark: {e}")
        t_obj["status"] = "Error"
        t_obj["error"] = str(e)
        socketio.emit('progress_update', t_obj)

@app.route("/")
def index():
    """Page d'accueil"""
    health_map = get_last_health_status()
    current_config = get_config()
    
    sorted_tests = dict(sorted(tests_store.items(),
                              key=lambda x: x[1].get('timestamp', 0),
                              reverse=True))
    sorted_zfs_tests = dict(sorted(zfs_tests_store.items(),
                                  key=lambda x: x[1].get('timestamp', 0),
                                  reverse=True))
    
    return render_template("index.html",
        disks=DiskScanner.get_topology(),
        partitions=DiskScanner.get_partitions(),
        zfs=DiskScanner.get_zfs_details(),
        tests=sorted_tests,
        zfs_tests=sorted_zfs_tests,
        config=current_config,
        health_map=health_map)

@app.route("/start_test", methods=["POST"])
def start_test():
    """Démarre un nouveau test"""
    try:
        data = request.json
        test_id = f"test_{int(time.time())}"
        
        tests_store[test_id] = {
            "id": test_id,
            "name": data.get('name', 'Manual Test'),
            "status": "Running",
            "progress": 0,
            "date": datetime.datetime.now().strftime("%d/%m %H:%M"),
            "timestamp": time.time(),
            "data": {}
        }
        
        thread = threading.Thread(target=run_benchmark_thread, args=(test_id, data))
        thread.daemon = True
        thread.start()
        
        return jsonify({"status": "started", "id": test_id})
    except Exception as e:
        logger.error(f"Erreur démarrage test: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/get_charts")
def get_charts():
    """Génère les graphiques pour les tests sélectionnés"""
    try:
        selected_ids = request.args.getlist('ids')
        chart_type = request.args.get('type', 'read')
        
        # Filtrer les tests existants
        active_tests = []
        for tid in selected_ids:
            if tid in tests_store:
                active_tests.append(tests_store[tid])
        
        if not active_tests:
            return "Aucun test sélectionné", 400
        
        active_tests.sort(key=lambda x: x.get('timestamp', 0))
        
        # Créer le graphique
        line_chart = pygal.Line(
            style=LightStyle,
            fill=True,
            x_label_rotation=20,
            show_legend=True,
            legend_at_bottom=True,
            interpolate='cubic',
            width=800,
            height=400
        )
        line_chart.title = f"Historique - {chart_type}"
        line_chart.x_labels = [t['date'] for t in active_tests]
        
        # Regrouper par disque
        disks = set()
        for t in active_tests:
            disks.update(t['data'].keys())
        
        for disk in sorted(disks):
            values = []
            for test in active_tests:
                val = test['data'].get(disk, {}).get(chart_type, {}).get('value')
                if val is not None:
                    try:
                        values.append(float(val))
                    except (ValueError, TypeError):
                        values.append(None)
                else:
                    values.append(None)
            line_chart.add(disk, values)
        
        # Ajouter les tooltips avec lien
        chart_html = line_chart.render()
        return chart_html
        
    except Exception as e:
        logger.error(f"Erreur génération graphique: {e}")
        return f"Erreur: {e}", 500

@app.route("/save_config", methods=['POST'])
def save_config():
    """Sauvegarde la configuration DailyCheck"""
    try:
        config = request.json
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        return jsonify({"status": "ok", "message": "Configuration sauvegardée"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/get_config")
def route_get_config():
    """Récupère la configuration"""
    return jsonify(get_config())

@app.route("/test_detail/<tid>")
def test_detail(tid):
    """Page de détail d'un test"""
    test = tests_store.get(tid)
    
    if not test:
        file_path = os.path.join(RESULTS_DIR, f"{tid}.json")
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r') as f:
                    test = json.load(f)
                    tests_store[tid] = test
            except Exception as e:
                return f"Erreur de lecture: {e}", 500
    
    if not test:
        return "Rapport introuvable", 404
    
    # Générer les graphiques
    charts = {}
    if test.get('status') == 'Finished':
        for metric in ['read', 'latency']:
            if any(metric in data for data in test['data'].values()):
                chart = pygal.Bar(
                    height=300,
                    show_legend=False,
                    title=f"{metric.capitalize()} par disque",
                    width=600
                )
                has_data = False
                for dev, res in test['data'].items():
                    if metric in res and 'value' in res[metric]:
                        try:
                            val = float(res[metric]['value'])
                            chart.add(dev, val)
                            has_data = True
                        except (ValueError, TypeError):
                            pass
                if has_data:
                    charts[metric] = chart.render_data_uri()
    
    return render_template("test_detail.html", test=test, charts=charts)

@app.route("/delete_test/<tid>", methods=['POST'])
def delete_test(tid):
    """Supprime un test"""
    try:
        if tid in tests_store:
            del tests_store[tid]
        
        file_path = os.path.join(RESULTS_DIR, f"{tid}.json")
        if os.path.exists(file_path):
            os.remove(file_path)
        
        save_stores()
        return jsonify({"status": "deleted"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/get_disk_notes/<device>")
def get_disk_note(device):
    """Récupère les notes d'un disque"""
    notes = {}
    if os.path.exists(NOTES_FILE):
        try:
            with open(NOTES_FILE, 'r') as f:
                notes = json.load(f)
        except:
            pass
    return jsonify({"note": notes.get(device, "")})

@app.route("/save_disk_note", methods=['POST'])
def save_disk_note():
    """Sauvegarde une note de disque"""
    try:
        data = request.json
        notes = {}
        if os.path.exists(NOTES_FILE):
            with open(NOTES_FILE, 'r') as f:
                notes = json.load(f)
        
        notes[data['device']] = data['note']
        
        with open(NOTES_FILE, 'w') as f:
            json.dump(notes, f, indent=2)
        
        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/get_active_tasks")
def get_active_tasks():
    """Récupère la liste des tâches actives"""
    active = []
    for tid, test in tests_store.items():
        if test.get('status') == 'Running':
            active.append({
                'id': tid,
                'name': test.get('name'),
                'progress': test.get('progress', 0),
                'current_op': test.get('current_op', '')
            })
    return jsonify(active)

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
