import subprocess
import json
import logging
import re

logger = logging.getLogger(__name__)

class DiskScanner:
    @staticmethod
    def get_zfs_details():
        """Récupère les détails complets des pools ZFS"""
        zfs_data = []
        try:
            # Récupérer la liste des pools
            pools_result = subprocess.run(["zpool", "list", "-H", "-o", "name"], 
                                        capture_output=True, text=True)
            if pools_result.returncode != 0:
                return []
            
            pool_names = pools_result.stdout.strip().split('\n')
            
            for pool_name in pool_names:
                if not pool_name:
                    continue
                
                # Infos de base du pool
                pool_info = subprocess.run(
                    ["zpool", "list", "-H", "-p", pool_name, 
                     "-o", "name,size,alloc,free,cap,health,fragmentation"],
                    capture_output=True, text=True
                )
                
                if pool_info.returncode != 0:
                    continue
                
                parts = pool_info.stdout.strip().split()
                if len(parts) < 7:
                    continue
                
                # Récupérer les datasets
                datasets = []
                ds_result = subprocess.run(
                    ["zfs", "list", "-H", "-r", pool_name, 
                     "-o", "name,used,avail,refer,mountpoint"],
                    capture_output=True, text=True
                )
                
                if ds_result.returncode == 0:
                    for line in ds_result.stdout.strip().split('\n'):
                        if not line:
                            continue
                        ds_parts = line.split('\t')
                        if len(ds_parts) >= 5:
                            datasets.append({
                                "name": ds_parts[0],
                                "used": ds_parts[1],
                                "avail": ds_parts[2],
                                "refer": ds_parts[3],
                                "mount": ds_parts[4]
                            })
                
                # Récupérer le statut du dernier scrub
                status_result = subprocess.run(
                    ["zpool", "status", pool_name],
                    capture_output=True, text=True
                )
                
                scrub_status = "Aucun"
                errors = {"read": "0", "write": "0", "cksum": "0"}
                
                if status_result.returncode == 0:
                    for line in status_result.stdout.split('\n'):
                        if "scan:" in line.lower():
                            scrub_status = line.strip()
                        if "cksum" in line.lower() and "errors" in line.lower():
                            # Extraire les erreurs
                            err_match = re.search(r'(\d+)\s+(\d+)\s+(\d+)', line)
                            if err_match:
                                errors = {
                                    "read": err_match.group(1),
                                    "write": err_match.group(2),
                                    "cksum": err_match.group(3)
                                }
                
                zfs_data.append({
                    "name": pool_name,
                    "size": DiskScanner._format_bytes(parts[1]),
                    "size_raw": parts[1],
                    "alloc": DiskScanner._format_bytes(parts[2]),
                    "alloc_raw": parts[2],
                    "free": DiskScanner._format_bytes(parts[3]),
                    "free_raw": parts[3],
                    "cap": parts[4],
                    "health": parts[5],
                    "frag": parts[6],
                    "scrub": scrub_status,
                    "errors": errors,
                    "datasets": datasets
                })
                
        except Exception as e:
            logger.error(f"Erreur ZFS: {e}")
        
        return zfs_data

    @staticmethod
    def _format_bytes(bytes_str):
        """Formate les bytes en unité lisible"""
        try:
            bytes_val = int(bytes_str)
            for unit in ['B', 'K', 'M', 'G', 'T', 'P']:
                if bytes_val < 1024:
                    return f"{bytes_val:.1f}{unit}"
                bytes_val /= 1024
            return f"{bytes_val:.1f}P"
        except:
            return bytes_str

    @staticmethod
    def get_topology():
        """Inventaire complet des disques"""
        cmd = ["lsblk", "-Jbo", "NAME,SIZE,TYPE,FSTYPE,LABEL,MOUNTPOINT,FSUSE%,MODEL,ROTA,VENDOR"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Erreur lsblk: {result.stderr}")
                return []
            
            data = json.loads(result.stdout)
            devices = data.get('blockdevices', [])
            
            def process_device(dev, parent_nature=""):
                fstype = dev.get('fstype', '')
                name = dev.get('name', '').lower()
                mount = str(dev.get('mountpoint', ''))
                
                # Classification
                if fstype == 'squashfs':
                    dev['nature'] = "📦 Immuable"
                elif fstype == 'zfs_member':
                    dev['nature'] = "🛡️ ZFS"
                elif 'overlay' in mount:
                    dev['nature'] = "☁️ Overlay"
                elif dev.get('type') == 'loop':
                    dev['nature'] = "🔄 Virtuel"
                elif "nvme" in name:
                    dev['nature'] = "⚡ NVMe"
                elif dev.get('rota') == 1:
                    dev['nature'] = "💿 HDD"
                else:
                    dev['nature'] = "🚀 SSD"
                
                # Pourcentage d'utilisation
                use_pct = dev.get('fsuse%', '0%')
                try:
                    dev['usage_val'] = int(use_pct.replace('%', ''))
                except:
                    dev['usage_val'] = 0
                
                # Traiter les enfants
                if 'children' in dev:
                    for child in dev['children']:
                        process_device(child, dev['nature'])
                
                return dev
            
            processed = []
            for dev in devices:
                processed.append(process_device(dev))
            
            return processed
            
        except Exception as e:
            logger.error(f"Erreur topology: {e}")
            return []

    @staticmethod
    def get_smart_data(device):
        """Récupère les données SMART d'un périphérique"""
        data = {
            "temp": "N/A",
            "critical_alerts": [],
            "attributes": [],
            "health": "OK"
        }
        
        try:
            # Vérifier si le périphérique supporte SMART
            check_cmd = ["sudo", "smartctl", "-i", f"/dev/{device}"]
            check_result = subprocess.run(check_cmd, capture_output=True, text=True)
            
            if "SMART support is: Unavailable" in check_result.stdout:
                data["error"] = "SMART non supporté"
                return data
            
            # Récupérer les données SMART
            cmd = ["sudo", "smartctl", "-a", "-j", f"/dev/{device}"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            
            if result.returncode != 0 and "NVMe" not in result.stdout:
                data["error"] = f"smartctl error: {result.stderr}"
                return data
            
            if not result.stdout.strip():
                data["error"] = "Aucune donnée SMART"
                return data
            
            raw = json.loads(result.stdout)
            
            # Température
            if "temperature" in raw:
                data["temp"] = raw["temperature"].get("current", "N/A")
            elif "nvme_smart_health_information_log" in raw:
                data["temp"] = raw["nvme_smart_health_information_log"].get("temperature", "N/A")
            
            # Attributs SMART (SATA)
            if "ata_smart_attributes" in raw:
                for attr in raw["ata_smart_attributes"].get("table", []):
                    raw_val = attr.get("raw", {}).get("value", 0)
                    attr_data = {
                        "id": attr.get("id"),
                        "name": attr.get("name", "Unknown"),
                        "value": attr.get("value", "N/A"),
                        "raw_display": attr.get("raw", {}).get("string", "0"),
                        "raw_value": raw_val,
                        "threshold": attr.get("thresh", "N/A"),
                        "worst": attr.get("worst", "N/A")
                    }
                    data["attributes"].append(attr_data)
                    
                    # Alertes critiques
                    if attr.get("id") in [5, 10, 184, 187, 188, 197, 198, 201]:
                        if raw_val > 0:
                            data["critical_alerts"].append(
                                f"{attr.get('name')}: {raw_val}"
                            )
                            data["health"] = "ALERTE"
            
            # Attributs NVMe
            elif "nvme_smart_health_information_log" in raw:
                nvme = raw["nvme_smart_health_information_log"]
                
                attrs = [
                    ("Critical Warning", nvme.get("critical_warning", 0)),
                    ("Temperature", nvme.get("temperature", 0)),
                    ("Available Spare", nvme.get("available_spare", 0)),
                    ("Available Spare Threshold", nvme.get("available_spare_threshold", 0)),
                    ("Percentage Used", nvme.get("percentage_used", 0)),
                    ("Data Units Read", nvme.get("data_units_read", 0)),
                    ("Data Units Written", nvme.get("data_units_written", 0)),
                    ("Host Read Commands", nvme.get("host_read_commands", 0)),
                    ("Host Write Commands", nvme.get("host_write_commands", 0)),
                    ("Controller Busy Time", nvme.get("controller_busy_time", 0)),
                    ("Power Cycles", nvme.get("power_cycles", 0)),
                    ("Power On Hours", nvme.get("power_on_hours", 0)),
                    ("Unsafe Shutdowns", nvme.get("unsafe_shutdowns", 0)),
                    ("Media Errors", nvme.get("media_errors", 0)),
                    ("Error Info Log Entries", nvme.get("error_info_log_entry_count", 0))
                ]
                
                for name, value in attrs:
                    data["attributes"].append({
                        "id": name,
                        "name": name,
                        "value": value,
                        "raw_display": str(value)
                    })
                
                if nvme.get("media_errors", 0) > 0:
                    data["critical_alerts"].append(f"Erreurs média: {nvme.get('media_errors')}")
                    data["health"] = "ALERTE"
                
                if nvme.get("critical_warning", 0) > 0:
                    data["critical_alerts"].append("Avertissement critique matériel")
                    data["health"] = "ALERTE"
            
            # Santé globale
            if "smart_status" in raw:
                if not raw["smart_status"].get("passed", True):
                    data["health"] = "FAILED"
                    data["critical_alerts"].append("SMART auto-test failed")
            
            return data
            
        except Exception as e:
            logger.error(f"Erreur SMART {device}: {e}")
            data["error"] = str(e)
            return data

    @staticmethod
    def get_partitions():
        """Récupère toutes les partitions et leurs infos"""
        cmd = ["lsblk", "-Jpo", "NAME,SIZE,TYPE,FSTYPE,LABEL,MOUNTPOINT,FSUSE%,FSAVAIL,FSSIZE,UUID,MODEL"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                return []
            
            data = json.loads(result.stdout)
            
            def flatten_devices(devs, result_list=[]):
                for dev in devs:
                    if dev.get('fstype') or dev.get('mountpoint'):
                        # Formater les tailles
                        for field in ['size', 'fssize', 'fsavail']:
                            if field in dev and dev[field]:
                                try:
                                    size_bytes = int(dev[field])
                                    dev[f"{field}_human"] = DiskScanner._format_bytes(str(size_bytes))
                                except:
                                    dev[f"{field}_human"] = dev[field]
                        
                        result_list.append(dev)
                    
                    if 'children' in dev:
                        flatten_devices(dev['children'], result_list)
                
                return result_list
            
            partitions = flatten_devices(data.get('blockdevices', []))
            return partitions
            
        except Exception as e:
            logger.error(f"Erreur partitions: {e}")
            return []
