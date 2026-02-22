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
TOOLBOX_LOG_FILE = "toolbox.log"
TOOLBOX_HISTORY_FILE = "toolbox_history.json"

os.makedirs(RESULTS_DIR, exist_ok=True)

tests_store = {}
zfs_tests_store = {}
parity_store = {}
snapshot_store = {}
toolbox_history = []          # Entrées de log (format structuré)
toolbox_history_tasks = []    # Historique des tâches pour la page toolbox

# Configuration du logging structuré
LOG_FORMAT = '[%(asctime)s] [%(levelname)-5s] [%(name)-20s] %(message)s'
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    datefmt='%Y-%m-%dT%H:%M:%S'
)
logger = logging.getLogger(__name__)

# Handler fichier pour les logs applicatifs
try:
    file_handler = logging.FileHandler('storage_monitor.log')
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt='%Y-%m-%dT%H:%M:%S'))
    logging.getLogger().addHandler(file_handler)
except Exception:
    pass

def get_last_health_status():
    """
    Analyse les tests pour définir l'état : 🟢 OK, 🟡 Attention, 🔴 Critique.
    Pour chaque disque, cherche le test SMART le plus récent (pas forcément le test global
    le plus récent, qui peut être un test read/latency sans données SMART).
    """
    health_map = {}
    severe_keywords = [
        "Reallocated_Sector", "Current_Pending", "Offline_Uncorrectable",
        "Media Errors", "FAILED", "read failure", "SECTEURS PENDING",
        "secteurs défectueux", "perte de données"
    ]

    # Construire d'abord l'ensemble de tous les disques connus
    all_devs = set()
    for test in tests_store.values():
        all_devs.update(test.get('data', {}).keys())

    # Pour chaque disque, trouver le test SMART le plus récent
    sorted_tests = sorted(tests_store.values(), key=lambda x: x.get('timestamp', 0), reverse=True)
    for dev in all_devs:
        for test in sorted_tests:
            smart = test.get('data', {}).get(dev, {}).get('smart')
            if smart and 'critical_alerts' in smart:
                alerts = smart.get('critical_alerts', [])
                if not alerts:
                    health_map[dev] = "🟢"
                else:
                    has_severe = any(
                        any(kw in alert for kw in severe_keywords)
                        for alert in alerts
                    )
                    health_map[dev] = "🔴" if has_severe else "🟡"
                break  # Trouvé pour ce disque, passer au suivant
        if dev not in health_map:
            health_map[dev] = "🟢"  # Aucun test SMART → OK par défaut

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

        out = json.loads(subprocess.check_output(cmd))
        bw = out['jobs'][0]['read']['bw_bytes'] / 1024 / 1024
        return {"value": round(bw, 2), "unit": "Mo/s"}


    except subprocess.CalledProcessError as e:
        return {"error": f"FIO error: {e.output}"}
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

        # Utiliser check_output - PAS DE TIMEOUT
        out = json.loads(subprocess.check_output(cmd))
        latency = out['jobs'][0]['read']['clat_ns']['mean'] / 1000000
        return {"value": round(latency, 3), "unit": "ms"}
    except subprocess.CalledProcessError as e:
        return {"error": f"FIO error: {e.output}"}
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
    start_time = time.time()
    try:
        t_obj = tests_store[tid]
        devices = payload.get('targets') or payload.get('disks', [])
        tests = payload.get('test_types') or payload.get('tests', [])
        duration = int(payload.get('duration', 30))
        is_zfs = payload.get('is_zfs', False)
        
        logger.info(f"[{tid}] Démarrage benchmark: devices={devices}, tests={tests}, duration={duration}s")
        
        total_steps = len(devices) * len(tests)
        if total_steps == 0:
            total_steps = 1
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
                        result = DiskScanner.get_smart_data(dev_clean)
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
                
                # Sync progression dans toolbox
                for task in toolbox_history_tasks:
                    if task['id'] == tid:
                        task['progress'] = t_obj["progress"]
                        task['current_op'] = t_obj.get("current_op", "")
                        break
                
                socketio.emit('progress_update', t_obj)

        t_obj["status"] = "Finished"
        t_obj["progress"] = 100
        elapsed = round(time.time() - start_time, 1)
        logger.info(f"[{tid}] Benchmark terminé en {elapsed}s")
        
        # Mettre à jour l'historique toolbox
        for task in toolbox_history_tasks:
            if task['id'] == tid:
                task['status'] = 'Finished'
                task['progress'] = 100
                task['endTime'] = datetime.datetime.now().isoformat()
                task['duration'] = int(elapsed * 1000)
                break
        
        save_test(tid)
        socketio.emit('progress_update', t_obj)

    except Exception as e:
        elapsed = round(time.time() - start_time, 1)
        logger.error(f"[{tid}] Erreur thread benchmark après {elapsed}s: {e}")
        t_obj["status"] = "Error"
        t_obj["error"] = str(e)
        
        for task in toolbox_history_tasks:
            if task['id'] == tid:
                task['status'] = 'Error'
                task['endTime'] = datetime.datetime.now().isoformat()
                task['duration'] = int(elapsed * 1000)
                break
        
        socketio.emit('progress_update', t_obj)

def get_critical_errors(alerts):
    """
    Retourne uniquement les erreurs réellement critiques.
    """

    critical_keywords = [
        'SECTEURS PENDING',
        'Current_Pending_Sector',
        'Reallocated_Sector',
        'Offline_Uncorrectable',
        'SMART global: FAILED',
        'Self-test échoué',
        'Erreurs Média'
    ]

    filtered = []

    for alert in alerts:
        if any(keyword in alert for keyword in critical_keywords):
            filtered.append(alert)

    return filtered

def is_nvme_or_ssd(disk_name):
    """Détermine si un disque est NVMe/SSD d'après son nom"""
    name = disk_name.lower().lstrip('/dev/')
    return 'nvme' in name or 'nvme' in disk_name.lower()

def get_smart_for_disk(disk, test):
    """
    Retourne (alerts, is_fallback) pour un disque dans un test donné.
    Si le test ne contient pas de données SMART (ex: test read/latency seul),
    cherche dans tous les tests disponibles le plus récent avec SMART pour ce disque.
    """
    data = test.get('data', {}).get(disk, {})
    smart = data.get('smart')
    if smart and 'critical_alerts' in smart:
        return smart.get('critical_alerts', []), False

    # Fallback : test SMART le plus récent disponible pour ce disque
    candidates = sorted(
        [t for t in tests_store.values()
         if t.get('status') == 'Finished'
         and disk in t.get('data', {})
         and t['data'][disk].get('smart', {}).get('critical_alerts') is not None],
        key=lambda x: x.get('timestamp', 0),
        reverse=True
    )
    if candidates:
        return candidates[0]['data'][disk]['smart'].get('critical_alerts', []), True
    return [], False


def build_chart_svg(chart_type, disks, active_tests, title, colors, points_info_out):
    """
    Construit un graphique pygal pour un ensemble de disques donné.
    Pour 'errors' : utilise get_smart_for_disk avec fallback si le test sélectionné
    ne contient pas de données SMART.
    """
    style = pygal.style.Style(
        background='white',
        plot_background='#f8f9fa',
        foreground='#2c3e50',
        colors=colors
    )
    chart = pygal.Line(
        style=style, fill=False, x_label_rotation=20,
        show_legend=True, legend_at_bottom=True,
        width=780, height=380, show_dots=True, dots_size=4, title=title
    )
    chart.x_labels = [t['date'] for t in active_tests]
    threshold = 10
    has_data = False

    for disk in disks:
        values = []
        for test in active_tests:
            data = test['data'].get(disk, {})

            if chart_type == 'errors':
                alerts, is_fallback = get_smart_for_disk(disk, test)
                critical = get_critical_errors(alerts)
                count = len(critical)
                display = count if count <= threshold else threshold + (count - threshold) ** 0.5
                values.append(display)
                points_info_out.append({
                    'disk': disk, 'test_id': test['id'], 'date': test['date'],
                    'real_value': count, 'alerts': critical,
                    'type': 'errors', 'fallback': is_fallback
                })
            else:
                val = data.get(chart_type, {}).get('value')
                if val is not None:
                    try:
                        val = float(val)
                        values.append(val)
                        points_info_out.append({
                            'disk': disk, 'test_id': test['id'], 'date': test['date'],
                            'value': val, 'unit': data.get(chart_type, {}).get('unit', ''),
                            'type': chart_type
                        })
                    except:
                        values.append(None)
                        points_info_out.append(None)
                else:
                    values.append(None)
                    points_info_out.append(None)

        if chart_type == 'errors':
            chart.add(disk, values)
            has_data = True
        else:
            if any(v is not None for v in values):
                chart.add(disk, values)
                has_data = True

    if not has_data:
        return None

    if chart_type == 'errors':
        chart.add(f'Seuil ({threshold})', [threshold] * len(active_tests),
                  stroke_style={'width': 2, 'dasharray': '5,5'})

    return chart.render().decode('utf-8')


def inject_tooltips(svg_str, points_info, chart_type):
    """Injecte data-test-id et data-tooltip sur les cercles pygal"""
    import re
    try:
        valid_points = [p for p in points_info if p is not None]
        circle_pattern = re.compile(r'<circle([^>]*?)(/?>)')
        matches = list(circle_pattern.finditer(svg_str))
        data_circles = [m for m in matches if 'dot' in m.group(1)]

        replacements = []
        for i, info in enumerate(valid_points):
            if i >= len(data_circles):
                break
            match = data_circles[i]

            if chart_type == 'errors':
                count = info['real_value']
                fallback = info.get('fallback', False)
                if count == 0:
                    status_line = '✅ Aucune erreur critique'
                else:
                    status_line = f'⚠ {count} erreur(s) critique(s)'
                tooltip = f"{info['disk']} — {info['date']}\n{status_line}"
                if fallback:
                    tooltip += '\n(données SMART du dernier test disponible)'
                if info.get('alerts'):
                    tooltip += '\n' + '\n'.join(f"  • {a}" for a in info['alerts'][:4])
            elif chart_type == 'read':
                tooltip = f"{info['disk']} — {info['date']}\nDébit: {info['value']} {info.get('unit','Mo/s')}"
            else:
                tooltip = f"{info['disk']} — {info['date']}\nLatence: {info['value']} {info.get('unit','ms')}"

            old_attrs = match.group(1)
            new_elem = (f'<circle data-test-id="{info["test_id"]}" '
                        f'data-tooltip="{tooltip}" title="{tooltip}" '
                        f'class="clickable-point dot" style="cursor:pointer;"'
                        f'{old_attrs}{match.group(2)}')
            replacements.append((match.start(), match.end(), new_elem))

        for start, end, new_elem in reversed(replacements):
            svg_str = svg_str[:start] + new_elem + svg_str[end:]

    except Exception as e:
        logger.error(f"Erreur injection tooltips: {e}")

    return svg_str


@app.route("/get_charts")
def get_charts():
    try:
        selected_ids = request.args.getlist('ids')
        chart_type = request.args.get('type', 'read')
        logger.info(f"Graphique: {len(selected_ids)} tests, type={chart_type}")

        # Tests valides triés par date
        active_tests = sorted(
            [t for tid in selected_ids
             if (t := tests_store.get(tid)) and t.get('status') == 'Finished' and t.get('data')],
            key=lambda x: x.get('timestamp', 0)
        )

        if not active_tests:
            return send_svg_message("📊 Aucune donnée", "Sélectionnez des tests terminés")

        # Tous les disques présents dans les tests sélectionnés
        all_disks = sorted({d for t in active_tests for d in t['data'].keys()})

        # Palettes de couleurs distinctes
        COLORS_NVME = ('#3498db', '#2980b9', '#1abc9c', '#16a085', '#9b59b6', '#8e44ad')
        COLORS_HDD  = ('#e74c3c', '#c0392b', '#f39c12', '#e67e22', '#27ae60', '#2ecc71')
        COLORS_ALL  = ('#e74c3c', '#f39c12', '#3498db', '#2ecc71', '#9b59b6', '#1abc9c',
                       '#e67e22', '#c0392b', '#2980b9', '#16a085')

        # ── Mode ERRORS : un seul graphique tous disques confondus ──
        if chart_type == 'errors':
            points_info = []
            unit_label = "erreurs critiques SMART"
            svg = build_chart_svg(
                'errors', all_disks, active_tests,
                f"⚠️ Erreurs critiques SMART — tous disques",
                COLORS_ALL, points_info
            )
            if svg is None:
                return send_svg_message("📊 Aucune donnée erreurs", "Aucun test SMART sélectionné")
            svg = inject_tooltips(svg, points_info, 'errors')
            # Envelopper dans du HTML pour affichage pleine largeur
            html = f'''<div class="charts-single">
                <div class="chart-block chart-full">
                    <h4 class="chart-subtitle">⚠️ Erreurs critiques SMART — tous disques</h4>
                    {svg}
                </div>
            </div>'''
            return app.response_class(response=html, status=200, mimetype='text/html')

        # ── Mode READ / LATENCY : deux graphiques séparés HDD vs NVMe ──
        nvme_disks = [d for d in all_disks if is_nvme_or_ssd(d)]
        hdd_disks  = [d for d in all_disks if not is_nvme_or_ssd(d)]

        type_label = "Débit (Mo/s)" if chart_type == 'read' else "Latence (ms)"
        type_icon  = "📈" if chart_type == 'read' else "⏱️"

        charts_html_parts = []

        # Graphique NVMe/SSD
        if nvme_disks:
            points_nvme = []
            title_nvme = f"{type_icon} {type_label} — NVMe / SSD"
            svg_nvme = build_chart_svg(chart_type, nvme_disks, active_tests,
                                       title_nvme, COLORS_NVME, points_nvme)
            if svg_nvme:
                svg_nvme = inject_tooltips(svg_nvme, points_nvme, chart_type)
                charts_html_parts.append(f'''
                    <div class="chart-block">
                        <h4 class="chart-subtitle">⚡ NVMe / SSD</h4>
                        {svg_nvme}
                    </div>''')

        # Graphique HDD
        if hdd_disks:
            points_hdd = []
            title_hdd = f"{type_icon} {type_label} — HDD"
            svg_hdd = build_chart_svg(chart_type, hdd_disks, active_tests,
                                      title_hdd, COLORS_HDD, points_hdd)
            if svg_hdd:
                svg_hdd = inject_tooltips(svg_hdd, points_hdd, chart_type)
                charts_html_parts.append(f'''
                    <div class="chart-block">
                        <h4 class="chart-subtitle">💿 HDD</h4>
                        {svg_hdd}
                    </div>''')

        if not charts_html_parts:
            return send_svg_message("📊 Aucune donnée", f"Aucune valeur de {chart_type} dans les tests")

        # Un seul graphique → pleine largeur, deux → côte à côte
        layout_class = "charts-single" if len(charts_html_parts) == 1 else "charts-dual"
        if len(charts_html_parts) == 1:
            charts_html_parts[0] = charts_html_parts[0].replace('class="chart-block"', 'class="chart-block chart-full"')

        html = f'<div class="{layout_class}">{"".join(charts_html_parts)}</div>'
        return app.response_class(response=html, status=200, mimetype='text/html')

    except Exception as e:
        logger.error(f"Erreur graphique: {e}")
        return send_svg_message("❌ Erreur", str(e)[:80])

def send_svg_message(title, message):
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 300">
    <rect width="600" height="300" fill="#f8f9fa" rx="10" ry="10"/>
    <text x="300" y="150" font-family="Arial" font-size="18" fill="#2c3e50" text-anchor="middle">
        {title}
    </text>
    <text x="300" y="180" font-family="Arial" font-size="14" fill="#7f8c8d" text-anchor="middle">
        {message}
    </text>
</svg>'''
    return app.response_class(response=svg, status=200, mimetype='image/svg+xml')

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
        
        # Enregistrer dans l'historique toolbox
        toolbox_history_tasks.append({
            "id": test_id,
            "name": data.get('name', 'Manual Test'),
            "status": "Running",
            "progress": 0,
            "current_op": "",
            "startTime": datetime.datetime.now().isoformat(),
            "endTime": None,
            "duration": None
        })
        
        thread = threading.Thread(target=run_benchmark_thread, args=(test_id, data))
        thread.daemon = True
        thread.start()
        
        return jsonify({"status": "started", "id": test_id})
    except Exception as e:
        logger.error(f"Erreur démarrage test: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

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

@app.route("/toolbox")
def toolbox_page():
    """Page dédiée à la toolbox — fichier toolbox.html dans le même répertoire que app.py"""
    import os
    toolbox_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'toolbox.html')
    if os.path.exists(toolbox_path):
        from flask import send_file
        return send_file(toolbox_path, mimetype='text/html')
    # Fallback : essayer render_template (si toolbox.html est dans templates/)
    return render_template("toolbox.html")

@app.route("/get_toolbox_tasks")
def get_toolbox_tasks():
    """Retourne l'historique des tâches toolbox"""
    return jsonify(toolbox_history_tasks)

@app.route("/remove_toolbox_task/<task_id>", methods=['POST'])
def remove_toolbox_task(task_id):
    """Supprime une tâche de l'historique toolbox"""
    global toolbox_history_tasks
    toolbox_history_tasks = [t for t in toolbox_history_tasks if t.get('id') != task_id]
    return jsonify({"status": "ok"})

@app.route("/clear_toolbox_tasks", methods=['POST'])
def clear_toolbox_tasks():
    """Supprime les tâches terminées de l'historique"""
    global toolbox_history_tasks
    toolbox_history_tasks = [t for t in toolbox_history_tasks if t.get('status') == 'Running']
    return jsonify({"status": "ok"})

@app.route("/toolbox_log", methods=['POST'])
def toolbox_log():
    """Reçoit et persiste les logs de la toolbox frontend"""
    try:
        entry = request.json
        if not entry:
            return jsonify({"status": "error", "message": "No data"}), 400
        
        ts = entry.get('ts', datetime.datetime.now().isoformat())
        level = entry.get('level', 'INFO').ljust(5)
        task_id = (entry.get('taskId') or 'system').ljust(20)
        message = entry.get('message', '')
        
        # Format standard
        log_line = f"[{ts}] [{level}] [{task_id}] {message}\n"
        
        # Écrire dans le fichier toolbox.log
        with open(TOOLBOX_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_line)
        
        # Garder en mémoire (max 500 entrées)
        toolbox_history.append({
            'ts': ts, 'level': level.strip(), 'taskId': task_id.strip(),
            'message': message
        })
        if len(toolbox_history) > 500:
            toolbox_history.pop(0)
        
        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error(f"Erreur toolbox_log: {e}")
        return jsonify({"status": "error"}), 500

@app.route("/get_toolbox_logs")
def get_toolbox_logs():
    """Récupère les logs toolbox (derniers N)"""
    try:
        n = int(request.args.get('n', 100))
        return jsonify(toolbox_history[-n:])
    except Exception as e:
        return jsonify([])

@app.route("/clear_toolbox_logs", methods=['POST'])
def clear_toolbox_logs():
    """Vide les logs toolbox"""
    try:
        toolbox_history.clear()
        with open(TOOLBOX_LOG_FILE, 'w', encoding='utf-8') as f:
            f.write(f"[{datetime.datetime.now().isoformat()}] [INFO ] [system              ] Logs toolbox vidés\n")
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

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

@app.route("/get_disk_details/<device>")
def get_disk_details(device):
    """Récupère tous les détails d'un disque pour le modal"""
    try:
        # Récupérer les infos de base
        topology = DiskScanner.get_topology()
        disk_info = next((d for d in topology if d.get('name') == device), {})
        
        # Récupérer les dernières données SMART
        smart_data = DiskScanner.get_smart_data(device)
        
        # Récupérer les partitions
        partitions = DiskScanner.get_partitions()
        disk_partitions = [p for p in partitions if p.get('name', '').startswith(f'/dev/{device}')]
        
        # Récupérer les pools ZFS associés
        zfs_pools = []
        try:
            pools = DiskScanner.get_zfs_details()
            for pool in pools:
                for ds in pool.get('datasets', []):
                    if ds.get('mount', '').startswith(f'/dev/{device}') or device in ds.get('name', ''):
                        zfs_pools.append(pool)
                        break
        except:
            pass
        
        # Formater les attributs SMART
        attributes = []
        for attr in smart_data.get('attributes', []):
            attributes.append({
                'name': attr.get('name', 'Inconnu'),
                'value': attr.get('value', 'N/A'),
                'raw': attr.get('raw_display', '0'),
                'critical': attr.get('id') in [5, 10, 184, 187, 188, 197, 198, 201] and int(attr.get('raw_value', 0)) > 0
            })
        
        # Formater les alertes avec explications
        alerts = []
        for alert in smart_data.get('critical_alerts', []):
            explication = "Alerte SMART"
            if 'Command_Timeout' in alert:
                explication = "Temps de réponse dépassé - Surveiller l'évolution"
            elif 'SECTEURS' in alert or 'Pending' in alert:
                explication = "⚠️ CRITIQUE - Secteurs défectueux, risque de perte de données"
            elif 'Self-test' in alert:
                explication = "Le test matériel a échoué, disque probablement défaillant"
            elif 'exit status: 4' in alert:
                explication = "Normal pour NVMe - Commandes non supportées"
            alerts.append({'alert': alert, 'explication': explication})
        
        return jsonify({
            'name': device,
            'model': disk_info.get('model', 'N/A'),
            'nature': disk_info.get('nature', 'N/A'),
            'size': disk_info.get('size', 'N/A'),
            'usage': f"{disk_info.get('usage_val', 0)}%",
            'temp': smart_data.get('temp', 'N/A'),
            'alerts': alerts,
            'attributes': attributes,
            'partitions': disk_partitions,
            'zfs_pools': zfs_pools
        })
    except Exception as e:
        logger.error(f"Erreur détails disque {device}: {e}")
        return jsonify({'error': str(e)}), 500

@app.route("/get_backup_disks")
def get_backup_disks():
    """Liste les disques disponibles pour la sauvegarde"""
    try:
        result = subprocess.run(["lsblk", "-J", "-o", "NAME,SIZE,TYPE,MOUNTPOINT,MODEL"], 
                               capture_output=True, text=True)
        data = json.loads(result.stdout)
        
        disks = []
        for dev in data.get('blockdevices', []):
            if dev.get('type') == 'disk':
                disks.append({
                    'name': dev.get('name'),
                    'size': dev.get('size'),
                    'model': dev.get('model', 'Inconnu'),
                    'mount': dev.get('mountpoint', 'Non monté')
                })
        return jsonify(disks)
    except Exception as e:
        logger.error(f"Erreur liste disques: {e}")
        return jsonify([])

@app.route("/start_backup", methods=['POST'])
def start_backup():
    """Lance une sauvegarde sécurisée avec dd"""
    try:
        data = request.json
        source = data.get('source')
        destination = data.get('destination')
        bs = data.get('bs', '4M')
        conv = data.get('conv', 'noerror,sync')
        status = data.get('status', 'progress')
        
        # Vérifications de sécurité
        if not source or not destination:
            return jsonify({"error": "Source et destination requis"}), 400
        
        # Empêcher l'écriture sur des disques système
        system_disks = ['/dev/sda', '/dev/nvme0n1']  # À adapter
        if source in system_disks:
            return jsonify({"error": "Sauvegarde du disque système non autorisée"}), 400
        
        # Créer le dossier de destination si nécessaire
        dest_dir = os.path.dirname(destination)
        if dest_dir and not os.path.exists(dest_dir):
            os.makedirs(dest_dir, exist_ok=True)
        
        # Commande dd sécurisée
        if not source.startswith("/dev/"):
            return jsonify({"error": "Source invalide"}), 400

        if destination.startswith("/dev/"):
            return jsonify({"error": "Destination ne peut pas être un device"}), 400
        cmd = [
            "sudo", "dd",
            f"if={source}",
            f"of={destination}",
            f"bs={bs}",
            f"conv={conv}",
            f"status={status}"
        ]
        
        # Lancer dans un thread
        def run_backup():
            try:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1
                )
                
                backup_id = f"backup_{int(time.time())}"
                
                for line in process.stderr:
                    if 'bytes' in line:
                        # Extraire la progression
                        socketio.emit('backup_progress', {
                            'id': backup_id,
                            'progress': line.strip(),
                            'source': source,
                            'destination': destination
                        })
                
                return_code = process.wait()
                
                if return_code == 0:
                    socketio.emit('backup_complete', {
                        'id': backup_id,
                        'status': 'success',
                        'message': f"Sauvegarde terminée: {destination}"
                    })
                else:
                    socketio.emit('backup_complete', {
                        'id': backup_id,
                        'status': 'error',
                        'message': f"Erreur lors de la sauvegarde"
                    })
                    
            except Exception as e:
                logger.error(f"Erreur backup: {e}")
        
        thread = threading.Thread(target=run_backup)
        thread.daemon = True
        thread.start()
        
        return jsonify({"status": "started", "message": "Sauvegarde démarrée"})
        
    except Exception as e:
        logger.error(f"Erreur démarrage backup: {e}")
        return jsonify({"error": str(e)}), 500



if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
