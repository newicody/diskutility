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

        logger.info(f"[CMD] {' '.join(cmd)}")
        raw = subprocess.check_output(cmd, stderr=subprocess.PIPE)
        out = json.loads(raw)
        bw = out['jobs'][0]['read']['bw_bytes'] / 1024 / 1024
        result = {"value": round(bw, 2), "unit": "Mo/s"}
        logger.info(f"[OUT] read {dev}: {result['value']} Mo/s")
        return result

    except subprocess.CalledProcessError as e:
        err = e.output.decode('utf-8', errors='replace') if e.output else str(e)
        logger.error(f"[ERR] fio read {dev}: {err[:200]}")
        return {"error": f"FIO error: {err[:100]}"}
    except Exception as e:
        logger.error(f"[ERR] run_read_benchmark {dev}: {e}")
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

        logger.info(f"[CMD] {' '.join(cmd)}")
        raw = subprocess.check_output(cmd, stderr=subprocess.PIPE)
        out = json.loads(raw)
        latency = out['jobs'][0]['read']['clat_ns']['mean'] / 1000000
        result = {"value": round(latency, 3), "unit": "ms"}
        logger.info(f"[OUT] latency {dev}: {result['value']} ms")
        return result
    except subprocess.CalledProcessError as e:
        err = e.output.decode('utf-8', errors='replace') if e.output else str(e)
        logger.error(f"[ERR] fio latency {dev}: {err[:200]}")
        return {"error": f"FIO error: {err[:100]}"}
    except Exception as e:
        logger.error(f"[ERR] run_latency_benchmark {dev}: {e}")
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

                # Émettre le log de commande vers la toolbox
                socketio.emit('toolbox_log', {
                    'ts': datetime.datetime.now().isoformat(),
                    'level': 'CMD',
                    'taskId': tid,
                    'message': f"Démarrage {test_type} sur /dev/{dev_clean}"
                })

                try:
                    if test_type == "smart":
                        result = DiskScanner.get_smart_data(dev_clean)
                        # Ajouter une valeur numérique pour les graphiques
                        if 'temp' in result and result['temp'] != 'N/A':
                            result["value"] = float(result['temp'])
                        else:
                            result["value"] = 0
                        socketio.emit('toolbox_log', {
                            'ts': datetime.datetime.now().isoformat(),
                            'level': 'OUT',
                            'taskId': tid,
                            'message': f"SMART {dev_clean}: health={result.get('health','?')}, temp={result.get('temp','?')}°C, alertes={len(result.get('critical_alerts',[]))}"
                        })

                    elif test_type == "read":
                        result = run_read_benchmark(dev_clean, duration, is_zfs)
                        if 'value' in result:
                            socketio.emit('toolbox_log', {
                                'ts': datetime.datetime.now().isoformat(),
                                'level': 'OUT', 'taskId': tid,
                                'message': f"read {dev_clean}: {result['value']} {result.get('unit','Mo/s')}"
                            })

                    elif test_type == "latency":
                        result = run_latency_benchmark(dev_clean, duration, is_zfs)
                        if 'value' in result:
                            socketio.emit('toolbox_log', {
                                'ts': datetime.datetime.now().isoformat(),
                                'level': 'OUT', 'taskId': tid,
                                'message': f"latency {dev_clean}: {result['value']} {result.get('unit','ms')}"
                            })

                    elif test_type == "zfs_scrub" and is_zfs:
                        pool_name = dev_clean.split('/')[0] if '/' in dev_clean else dev_clean
                        result = run_zfs_scrub(pool_name)
                        socketio.emit('toolbox_log', {
                            'ts': datetime.datetime.now().isoformat(),
                            'level': 'OUT', 'taskId': tid,
                            'message': f"zfs scrub {pool_name}: {result.get('status', result.get('error','?'))}"
                        })

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
    """
    Injecte data-test-id et data-tooltip sur les cercles de données pygal.

    Structure pygal réelle :
        <g class="dots">
          <g class="dot">
            <circle cx="..." cy="..." r="4"/>   ← PAS de class="dot" sur le cercle
          </g>
        </g>
    On repère donc les <circle> à l'intérieur d'un <g class="dot[^"]*">,
    puis on remplace chaque <circle> correspondant.
    """
    import re
    try:
        valid_points = [p for p in points_info if p is not None]

        # Trouver les circles qui sont précédés (proche) d'un <g class="dot...">
        # On utilise un pattern qui capture le contexte parent.
        # Pygal émet exactement un <circle> par <g class="dot">.
        dot_circle_pat = re.compile(
            r'(<g\s[^>]*class="dot[^"]*"[^>]*>)\s*(<circle([^>]*?)(/?>))'
        )
        all_matches = list(dot_circle_pat.finditer(svg_str))

        replacements = []
        for i, info in enumerate(valid_points):
            if i >= len(all_matches):
                break
            m = all_matches[i]

            # Construire le texte du tooltip
            if chart_type == 'errors':
                count = info.get('real_value', 0)
                fallback = info.get('fallback', False)
                status_line = '✅ Aucune erreur' if count == 0 else f'⚠ {count} erreur(s) critique(s)'
                tooltip = f"{info['disk']} — {info['date']}\n{status_line}"
                if fallback:
                    tooltip += '\n(données du dernier test SMART disponible)'
                if info.get('alerts'):
                    tooltip += '\n' + '\n'.join(f"  • {a}" for a in info['alerts'][:4])
            elif chart_type == 'read':
                tooltip = (f"{info['disk']} — {info['date']}\n"
                           f"Débit: {info['value']} {info.get('unit','Mo/s')}")
            else:
                tooltip = (f"{info['disk']} — {info['date']}\n"
                           f"Latence: {info['value']} {info.get('unit','ms')}")

            # Échapper les guillemets dans le tooltip pour HTML
            tooltip_safe = tooltip.replace('"', '&quot;')

            circle_attrs = m.group(3)
            circle_close = m.group(4)
            new_circle = (
                f'<circle data-test-id="{info["test_id"]}" '
                f'data-tooltip="{tooltip_safe}" title="{tooltip_safe}" '
                f'class="clickable-point" style="cursor:pointer;"'
                f'{circle_attrs}{circle_close}'
            )
            # On remplace seulement le <circle> (groupes 2,3,4), pas le <g>
            circle_start = m.start(2)
            circle_end = m.end(2)
            replacements.append((circle_start, circle_end, new_circle))

        # Appliquer en ordre inverse pour préserver les offsets
        for start, end, new_circle in reversed(replacements):
            svg_str = svg_str[:start] + new_circle + svg_str[end:]

    except Exception as e:
        logger.error(f"Erreur injection tooltips: {e}")

    return svg_str


# ── Catégories d'erreurs SMART avec leurs attributs et couleurs ──────────────
SMART_ERROR_CATEGORIES = [
    {
        'key': 'pending',
        'label': 'Secteurs en attente (Pending)',
        'icon': '⏳',
        'note': 'Secteurs suspects — perte de données possible si non récupérés',
        'attr_ids': [197],
        'alert_keywords': ['Current_Pending_Sector', 'SECTEURS PENDING'],
        'colors': ('#e74c3c', '#c0392b', '#f39c12', '#e67e22', '#9b59b6', '#8e44ad',
                   '#3498db', '#2ecc71', '#1abc9c', '#e74c3c'),
        'severity': 'critical',
    },
    {
        'key': 'reallocated',
        'label': 'Secteurs réalloués',
        'icon': '♻️',
        'note': 'Secteurs défectueux remplacés par des secteurs de réserve — dégradation physique',
        'attr_ids': [5, 10],
        'alert_keywords': ['Reallocated_Sector', 'Reallocated_Event'],
        'colors': ('#f39c12', '#e67e22', '#e74c3c', '#c0392b', '#27ae60', '#2ecc71',
                   '#9b59b6', '#3498db', '#1abc9c', '#16a085'),
        'severity': 'warning',
    },
    {
        'key': 'uncorrectable',
        'label': 'Erreurs non corrigibles',
        'icon': '💀',
        'note': 'Données non récupérables (lecture échouée) — risque de corruption de données',
        'attr_ids': [187, 198, 201],
        'alert_keywords': ['Reported_Uncorrect', 'Offline_Uncorrectable', 'Soft_Read_Error'],
        'colors': ('#9b59b6', '#8e44ad', '#e74c3c', '#c0392b', '#3498db', '#2980b9',
                   '#f39c12', '#2ecc71', '#1abc9c', '#e67e22'),
        'severity': 'critical',
    },
    {
        'key': 'other_hw',
        'label': 'Autres erreurs matérielles',
        'icon': '⚠️',
        'note': 'Erreurs E2E, timeouts commandes, erreurs NVMe Media — indicateurs de défaillance',
        'attr_ids': [184, 188],
        'alert_keywords': ['End-to-End_Error', 'Command_Timeout', 'Erreurs Média', 'Media Error',
                           'Avertissement critique'],
        'colors': ('#3498db', '#2980b9', '#1abc9c', '#16a085', '#9b59b6', '#8e44ad',
                   '#f39c12', '#e74c3c', '#27ae60', '#e67e22'),
        'severity': 'warning',
    },
]

# IDs SMART dont on prend la VALEUR BRUTE CUMULÉE depuis les alertes NVMe
NVME_MEDIA_ALERT_KEY = 'Erreurs Média'


def extract_smart_value_for_category(smart_data, category):
    """
    Extrait la valeur numérique réelle pour une catégorie d'erreur donnée.
    Priorité : 1) attributs SMART par ID  2) parsing des alert strings.
    Retourne (value: int, source_name: str).
    """
    import re
    if not smart_data:
        return 0, ''

    total = 0
    source_names = []

    # 1) Chercher dans les attributs SMART par ID
    attrs = smart_data.get('attributes', [])
    for attr in attrs:
        attr_id = attr.get('id')
        if attr_id in category['attr_ids']:
            raw = attr.get('raw_value', 0)
            if raw and int(raw) > 0:
                total += int(raw)
                source_names.append(attr.get('name', str(attr_id)))

    if total > 0:
        return total, ' + '.join(source_names)

    # 2) Fallback : parser les alert strings avec regex nombre après ':'
    alerts = smart_data.get('critical_alerts', [])
    for alert in alerts:
        for kw in category['alert_keywords']:
            if kw in alert:
                m = re.search(r':\s*(\d+)', alert)
                if m:
                    v = int(m.group(1))
                    if v > 0:
                        total += v
                        source_names.append(kw)
                        break  # un seul match par alert

    return total, ' + '.join(source_names) if source_names else ''


def build_smart_error_charts(all_disks, active_tests, colors_all):
    """
    Génère un graphique par catégorie d'erreur SMART.
    Chaque graphique montre l'évolution de la valeur réelle pour tous les disques.
    Seules les catégories avec au moins une valeur non nulle sont affichées.
    Retourne du HTML (grille de charts).
    """
    charts_parts = []
    any_smart_data = False

    for category in SMART_ERROR_CATEGORIES:
        # Collecter les données pour chaque disque sur chaque test
        disk_series = {}   # disk -> [values par test]
        disk_points = {}   # disk -> [point_info par test]
        has_nonzero = False

        for disk in all_disks:
            values = []
            points = []
            for test in active_tests:
                # Récupérer le dict smart complet (avec fallback si besoin)
                raw_smart = _get_raw_smart(disk, test)
                # Détecter si c'est un fallback (le test n'a pas de données SMART directes)
                direct_smart = test.get('data', {}).get(disk, {}).get('smart')
                is_fallback = not (direct_smart and ('attributes' in direct_smart or 'critical_alerts' in direct_smart))
                # Extraire la valeur pour cette catégorie
                value, src_name = extract_smart_value_for_category(raw_smart, category)
                values.append(value)
                if value > 0:
                    has_nonzero = True
                    any_smart_data = True
                elif raw_smart:
                    any_smart_data = True  # Il y a des données SMART, juste 0 erreur ici
                points.append({
                    'disk': disk,
                    'test_id': test['id'],
                    'date': test['date'],
                    'value': value,
                    'source': src_name,
                    'fallback': is_fallback,
                })
            disk_series[disk] = values
            disk_points[disk] = points

        if not has_nonzero:
            continue  # Catégorie vide → on saute

        # Construire le graphique pygal pour cette catégorie
        severity_colors = {
            'critical': '#e74c3c',
            'warning':  '#f39c12',
        }
        border_color = severity_colors.get(category['severity'], '#3498db')

        style = pygal.style.Style(
            background='white',
            plot_background='#f8f9fa',
            foreground='#2c3e50',
            colors=category['colors']
        )
        chart = pygal.Line(
            style=style, fill=False, x_label_rotation=20,
            show_legend=True, legend_at_bottom=True,
            width=760, height=320,
            show_dots=True, dots_size=5,
            title=f"{category['icon']} {category['label']}",
            min_scale=3,
            include_x_axis=True,
        )
        chart.x_labels = [t['date'] for t in active_tests]

        points_info_flat = []
        for disk in all_disks:
            values = disk_series[disk]
            if any(v > 0 for v in values):
                # Afficher les disques avec au moins une valeur non-nulle
                chart.add(disk, values)
                points_info_flat.extend(disk_points[disk])
            else:
                # Afficher quand même à 0 pour montrer qu'ils sont sains
                chart.add(disk, values)
                points_info_flat.extend(disk_points[disk])

        svg = chart.render().decode('utf-8')
        svg = inject_tooltips_smart(svg, points_info_flat, category)

        charts_parts.append(f'''
        <div class="chart-block smart-error-block"
             style="border-left: 4px solid {border_color};">
            <div class="smart-error-header">
                <span class="smart-error-icon">{category['icon']}</span>
                <span class="smart-error-title">{category['label']}</span>
                <span class="smart-error-note">{category['note']}</span>
            </div>
            {svg}
        </div>''')

    if not charts_parts:
        # Aucune données SMART du tout → message informatif
        if not any_smart_data:
            return '''<div class="charts-single">
                <div class="chart-block chart-full" style="padding:40px; text-align:center;">
                    <p style="color:#7f8c8d; font-size:1.1em;">
                        📊 Aucune donnée SMART dans les tests sélectionnés.<br>
                        <small>Sélectionnez des tests incluant un contrôle SMART, ou lancez un QuickSmart.</small>
                    </p>
                </div>
            </div>'''
        return '''<div class="charts-single">
            <div class="chart-block chart-full" style="padding:40px; text-align:center;">
                <p style="color:#27ae60; font-size:1.1em;">
                    ✅ Aucune erreur critique détectée sur les tests sélectionnés.
                </p>
            </div>
        </div>'''

    # Mise en page : 1 ou 2 colonnes selon le nombre de graphiques
    layout = "charts-dual" if len(charts_parts) >= 2 else "charts-single"
    return f'<div class="{layout} smart-errors-grid">{"".join(charts_parts)}</div>'


def _get_raw_smart(disk, test):
    """Retourne le dict smart complet pour un disque dans un test donné, avec fallback."""
    raw = test.get('data', {}).get(disk, {}).get('smart')
    if raw and ('attributes' in raw or 'critical_alerts' in raw):
        return raw
    # Fallback : test SMART le plus récent
    candidates = sorted(
        [t for t in tests_store.values()
         if t.get('status') == 'Finished'
         and disk in t.get('data', {})
         and t['data'][disk].get('smart', {}).get('critical_alerts') is not None],
        key=lambda x: x.get('timestamp', 0), reverse=True
    )
    if candidates:
        return candidates[0]['data'][disk].get('smart', {})
    return {}


def inject_tooltips_smart(svg_str, points_info, category):
    """
    Injecte data-test-id et data-tooltip sur les points d'un graphique SMART.
    Pygal génère <g class="dot..."><circle .../></g> — la classe dot est sur le <g>, pas le <circle>.
    """
    import re
    try:
        valid_points = [p for p in points_info if p is not None]
        dot_circle_pat = re.compile(
            r'(<g\s[^>]*class="dot[^"]*"[^>]*>)\s*(<circle([^>]*?)(/?>))'
        )
        all_matches = list(dot_circle_pat.finditer(svg_str))
        replacements = []
        for i, info in enumerate(valid_points):
            if i >= len(all_matches):
                break
            m = all_matches[i]
            value = info.get('value', 0)
            src = info.get('source', '')
            fallback_note = '\n(données du dernier test SMART disponible)' if info.get('fallback') else ''
            if value == 0:
                status = "✅ 0 — disque sain"
            else:
                status = f"⚠ {value:,}"
                if src:
                    status += f" ({src})"
            tooltip = (f"{info['disk']} — {info['date']}\n"
                       f"{category['icon']} {category['label']}\n"
                       f"{status}{fallback_note}")
            tooltip_safe = tooltip.replace('"', '&quot;')
            circle_attrs = m.group(3)
            circle_close = m.group(4)
            new_circle = (
                f'<circle data-test-id="{info["test_id"]}" '
                f'data-tooltip="{tooltip_safe}" title="{tooltip_safe}" '
                f'class="clickable-point" style="cursor:pointer;"'
                f'{circle_attrs}{circle_close}'
            )
            replacements.append((m.start(2), m.end(2), new_circle))
        for start, end, new_circle in reversed(replacements):
            svg_str = svg_str[:start] + new_circle + svg_str[end:]
    except Exception as e:
        logger.error(f"Erreur tooltips SMART: {e}")
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

        # ── Mode ERRORS : un graphique par catégorie d'erreur SMART ──
        if chart_type == 'errors':
            html = build_smart_error_charts(all_disks, active_tests, COLORS_ALL)
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

    # Charger les disques avec notes pour afficher l'icône correctement
    disk_notes_set = set()
    if os.path.exists(NOTES_FILE):
        try:
            with open(NOTES_FILE, 'r') as f:
                notes = json.load(f)
            disk_notes_set = {k for k, v in notes.items() if v and v.strip()}
        except Exception:
            pass

    return render_template("index.html",
        disks=DiskScanner.get_topology(),
        partitions=DiskScanner.get_partitions(),
        zfs=DiskScanner.get_zfs_details(),
        tests=sorted_tests,
        zfs_tests=sorted_zfs_tests,
        config=current_config,
        health_map=health_map,
        disk_notes_set=disk_notes_set)

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
    
    # Générer les graphiques (bar chart comparatif par disque)
    charts = {}
    if test.get('status') == 'Finished':
        for metric in ['read', 'latency']:
            if any(metric in data for data in test['data'].values()):
                chart = pygal.Bar(
                    height=300, show_legend=False,
                    title=f"{metric.capitalize()} par disque", width=600
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

    # Chercher test_detail.html : d'abord à côté de app.py, puis dans templates/
    detail_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_detail.html')
    if os.path.exists(detail_path):
        from jinja2 import Template
        with open(detail_path, 'r', encoding='utf-8') as f:
            tmpl_src = f.read()
        from flask import current_app
        from jinja2 import Environment, FileSystemLoader
        tmpl_dir = os.path.dirname(detail_path)
        env = current_app.jinja_env
        template = env.from_string(tmpl_src)
        html = template.render(test=test, charts=charts)
        return app.response_class(response=html, status=200, mimetype='text/html')

    return render_template("test_detail.html", test=test, charts=charts)


@app.route("/test_fragment/<tid>")
def test_fragment(tid):
    """Renvoie le contenu du rapport de test sous forme de fragment HTML (style + body)."""
    import re as _re

    # Charger le test depuis le store ou le fichier
    test = tests_store.get(tid)
    if not test:
        file_path = os.path.join(RESULTS_DIR, f"{tid}.json")
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r') as fh:
                    test = json.load(fh)
                    tests_store[tid] = test
            except Exception as exc:
                return f"<p style='color:red'>Erreur lecture: {exc}</p>", 500
    if not test:
        return "<p>Rapport introuvable</p>", 404

    # Générer les graphiques comparatifs
    charts = {}
    if test.get('status') == 'Finished':
        for metric in ['read', 'latency']:
            if any(metric in d for d in (test.get('data') or {}).values()):
                bar = pygal.Bar(height=260, show_legend=False,
                                title=f"{metric.capitalize()} par disque", width=560)
                any_val = False
                for dev, res in (test.get('data') or {}).items():
                    if metric in res and 'value' in res[metric]:
                        try:
                            bar.add(dev, float(res[metric]['value']))
                            any_val = True
                        except (ValueError, TypeError):
                            pass
                if any_val:
                    charts[metric] = bar.render_data_uri()

    # Charger test_detail.html depuis le dossier de app.py (même logique que test_detail route)
    detail_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_detail.html')
    if os.path.exists(detail_path):
        from flask import current_app
        env = current_app.jinja_env
        with open(detail_path, 'r', encoding='utf-8') as fh:
            tmpl_src = fh.read()
        template = env.from_string(tmpl_src)
        full_html = template.render(test=test, charts=charts)
    else:
        from flask import render_template as _rt
        full_html = _rt("test_detail.html", test=test, charts=charts)

    # Extraire le bloc <style> du <head> (styles critiques pour l'affichage)
    style_match = _re.search(r'<style>(.*?)</style>', full_html, _re.DOTALL)
    style_block = f'<style id="tf-styles">{style_match.group(1)}</style>' if style_match else ''

    # Extraire le contenu du <main>
    main_match = _re.search(r'<main[^>]*>(.*?)</main>', full_html, _re.DOTALL)
    main_content = main_match.group(1) if main_match else full_html

    fragment = f'{style_block}<div class="test-fragment-wrap" style="padding:4px 0">{main_content}</div>'
    return app.response_class(response=fragment, status=200, mimetype='text/html')


@app.route("/get_reports_json")
def get_reports_json():
    """Retourne la liste des tests pour mise à jour dynamique."""
    sorted_tests = sorted(tests_store.values(), key=lambda x: x.get('timestamp', 0), reverse=True)
    return jsonify([{
        "id": t.get("id"),
        "name": t.get("name", "?"),
        "date": t.get("date", ""),
        "status": t.get("status", "?"),
    } for t in sorted_tests])

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

MAX_LOG_LINES  = 5000   # Rotation : tronquer le fichier au-delà de cette limite
MAX_LOG_MEMORY = 500    # Garder en mémoire (RAM) les N dernières entrées

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
        
        # Format standard compatible syslog-ng
        log_line = f"[{ts}] [{level}] [{task_id}] {message}\n"
        
        # Écrire dans le fichier toolbox.log
        with open(TOOLBOX_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(log_line)
        
        # Rotation : si > MAX_LOG_LINES, garder seulement les dernières
        try:
            with open(TOOLBOX_LOG_FILE, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            if len(lines) > MAX_LOG_LINES:
                keep = lines[-(MAX_LOG_LINES - 100):]  # -100 pour éviter la rotation à chaque ligne
                with open(TOOLBOX_LOG_FILE, 'w', encoding='utf-8') as f:
                    f.writelines(keep)
                logger.info(f"Rotation toolbox.log : {len(lines)} → {len(keep)} lignes")
        except Exception:
            pass
        
        # Garder en mémoire (limité à MAX_LOG_MEMORY)
        toolbox_history.append({
            'ts': ts, 'level': level.strip(), 'taskId': task_id.strip(),
            'message': message
        })
        if len(toolbox_history) > MAX_LOG_MEMORY:
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

@app.route("/export_toolbox_logs")
def export_toolbox_logs():
    """
    Exporte le fichier toolbox.log en téléchargement direct.
    Compatible avec une intégration syslog-ng ou rsyslog :
      imfile { File("/path/to/toolbox.log"); Tag("storage-monitor"); };
    """
    from flask import send_file as flask_send_file
    if os.path.exists(TOOLBOX_LOG_FILE):
        return flask_send_file(
            os.path.abspath(TOOLBOX_LOG_FILE),
            mimetype='text/plain',
            as_attachment=True,
            download_name=f"toolbox_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        )
    return jsonify({"status": "error", "message": "Aucun fichier de log"}), 404

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
        
        # Récupérer la taille totale pour calculer le pourcentage
        dev_name = source.replace('/dev/', '')
        total_bytes = DiskScanner.get_device_size_bytes(dev_name)
        logger.info(f"[CMD] dd backup {source} → {destination} (taille: {total_bytes} o)")

        # Ajouter le toolbox task
        backup_id = f"backup_{int(time.time())}"
        start_ts = datetime.datetime.now().isoformat()
        toolbox_history_tasks.append({
            'id': backup_id,
            'name': f"💾 Backup {dev_name}",
            'status': 'Running',
            'startTime': start_ts,
            'endTime': None,
            'progress': 0,
            'current_op': f"{source} → {destination}",
            'detail': f"bs={bs}, conv={conv}"
        })

        def run_backup():
            try:
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1
                )

                last_bytes = 0
                last_speed = "—"

                for line in process.stderr:
                    line = line.strip()
                    if not line:
                        continue

                    # dd avec status=progress émet des lignes comme :
                    # "1073741824 bytes (1.1 GB, 1.0 GiB) copied, 5.2 s, 206 MB/s"
                    m = re.search(r'^(\d+)\s+bytes.*?,\s*([\d.]+)\s*s(?:,\s*([\d.]+ \S+/s))?', line)
                    if m:
                        copied = int(m.group(1))
                        elapsed = float(m.group(2))
                        speed_str = m.group(3) or "—"
                        last_bytes = copied
                        last_speed = speed_str

                        pct = int(min(copied / total_bytes * 100, 99)) if total_bytes > 0 else 0
                        copied_human = DiskScanner._format_bytes(str(copied))
                        total_human = DiskScanner._format_bytes(str(total_bytes)) if total_bytes else "?"

                        socketio.emit('backup_progress', {
                            'id': backup_id,
                            'percent': pct,
                            'copied': copied_human,
                            'total': total_human,
                            'speed': speed_str,
                            'elapsed': round(elapsed, 1),
                            'source': source,
                            'destination': destination
                        })
                        logger.info(f"[OUT] dd {dev_name}: {copied_human}/{total_human} ({pct}%) @ {speed_str}")

                        # Sync toolbox
                        for task in toolbox_history_tasks:
                            if task['id'] == backup_id:
                                task['progress'] = pct
                                task['current_op'] = f"{copied_human}/{total_human} @ {speed_str}"
                                break

                return_code = process.wait()
                elapsed_total = round(time.time() - float(start_ts.split('T')[1][:8].replace(':', '.')), 1) if False else "?"

                if return_code == 0:
                    total_human = DiskScanner._format_bytes(str(total_bytes)) if total_bytes else "?"
                    msg = f"Sauvegarde terminée — {total_human} → {destination}"
                    status_val = 'success'
                    logger.info(f"[OUT] dd {dev_name}: TERMINÉ ({return_code})")
                else:
                    msg = f"Erreur dd (code {return_code})"
                    status_val = 'error'
                    logger.error(f"[ERR] dd {dev_name}: code={return_code}")

                socketio.emit('backup_complete', {
                    'id': backup_id,
                    'status': status_val,
                    'message': msg,
                    'source': source,
                    'destination': destination
                })

                # Finaliser dans l'historique toolbox
                for task in toolbox_history_tasks:
                    if task['id'] == backup_id:
                        task['status'] = 'Finished' if return_code == 0 else 'Error'
                        task['progress'] = 100 if return_code == 0 else task.get('progress', 0)
                        task['endTime'] = datetime.datetime.now().isoformat()
                        break

                # Log toolbox
                socketio.emit('toolbox_log', {
                    'ts': datetime.datetime.now().isoformat(),
                    'level': 'OUT',
                    'taskId': backup_id,
                    'message': msg
                })

            except Exception as e:
                logger.error(f"Erreur backup thread: {e}")
                for task in toolbox_history_tasks:
                    if task['id'] == backup_id:
                        task['status'] = 'Error'
                        task['endTime'] = datetime.datetime.now().isoformat()
                        break
        
        thread = threading.Thread(target=run_backup)
        thread.daemon = True
        thread.start()
        
        return jsonify({"status": "started", "message": "Sauvegarde démarrée"})
        
    except Exception as e:
        logger.error(f"Erreur démarrage backup: {e}")
        return jsonify({"error": str(e)}), 500



if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
