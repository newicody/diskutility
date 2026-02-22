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
	    """Récupère les données SMART - Version sans timeout avec meilleure gestion d'erreur"""
	    data = {
	        "temp": "N/A",
	        "critical_alerts": [],
	        "attributes": [],
	        "health": "Inconnu"
	    }
	    
	    try:
	        cmd = ["sudo", "smartctl", "-a", "-j", f"/dev/{device}"]
	        
	        # Utiliser Popen directement pour un contrôle plus fin
	        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
	        stdout, stderr = process.communicate()  # Pas de timeout !
	        
	        # Analyser le code de retour
	        if process.returncode != 0:
	            # smartctl retourne souvent !=0 même avec des données valides
	            # Vérifier si on a quand même du JSON
	            if stdout and stdout.strip().startswith('{'):
	                try:
	                    raw = json.loads(stdout)
	                    # Ajouter une alerte pour le code d'erreur
	                    data["critical_alerts"].append(f"smartctl exit status: {process.returncode}")
	                except:
	                    data["error"] = f"smartctl error {process.returncode}: {stderr[:200]}"
	                    return data
	            else:
	                data["error"] = f"smartctl error {process.returncode}: {stderr[:200]}"
	                return data
	        else:
	            # Code de retour 0, tout est OK
	            raw = json.loads(stdout)
	        
	        # Extraction de la température
	        if "temperature" in raw:
	            data["temp"] = raw["temperature"].get("current", "N/A")
	        elif "nvme_smart_health_information_log" in raw:
	            data["temp"] = raw["nvme_smart_health_information_log"].get("temperature", "N/A")
	
	        # Vérifier les self-test logs pour sdb (qui a des échecs)
	        if "ata_smart_self_test_log" in raw:
	            test_log = raw["ata_smart_self_test_log"].get("standard", {})
	            for test in test_log.get("table", []):
	                if not test.get("status", {}).get("passed", True):
	                    status_str = test.get("status", {}).get("string", "Échec inconnu")
	                    data["critical_alerts"].append(f"Self-test échoué: {status_str}")
                        
	
	        # Extraction des attributs (SATA)
	        if "ata_smart_attributes" in raw:
	            for attr in raw["ata_smart_attributes"].get("table", []):
	                raw_val = attr.get("raw", {}).get("value", 0)
	                attr_name = attr.get("name", "Unknown")
	                attr_id = attr.get("id")
	                
	                data["attributes"].append({
	                    "id": attr_id,
	                    "name": attr_name,
	                    "value": attr.get("value", "N/A"),
	                    "worst": attr.get("worst", "N/A"),
	                    "thresh": attr.get("thresh", "N/A"),
	                    "raw_display": attr.get("raw", {}).get("string", "0"),
	                    "raw_value": raw_val
	                })
	                
	                # Attributs critiques (ajout de 188 pour Command_Timeout)
	                critical_ids = [5, 10, 184, 187, 188, 197, 198, 201]
	                
	                if attr_id in critical_ids and raw_val > 0:
	                    data["critical_alerts"].append(f"{attr_name}: {raw_val}")
	                
	                # Pour sdb, Current_Pending_Sector (197) est à 2159 !
	                if attr_id == 197 and raw_val > 0:
	                    data["critical_alerts"].append(f"SECTEURS PENDING: {raw_val}")
	
	        # Extraction pour NVMe
	        elif "nvme_smart_health_information_log" in raw:
	            nvme_log = raw["nvme_smart_health_information_log"]
	            
	            data["attributes"].extend([
	                {"id": "Warn", "name": "Critical Warning", "value": nvme_log.get("critical_warning", 0), "raw_display": str(nvme_log.get("critical_warning", 0))},
	                {"id": "Usure", "name": "Percentage Used", "value": nvme_log.get("percentage_used", 0), "raw_display": f"{nvme_log.get('percentage_used', 0)}%"},
	                {"id": "Spare", "name": "Available Spare", "value": nvme_log.get("available_spare", 0), "raw_display": f"{nvme_log.get('available_spare', 0)}%"},
	                {"id": "Err", "name": "Media Errors", "value": nvme_log.get("media_errors", 0), "raw_display": str(nvme_log.get("media_errors", 0))}
	            ])
	
	            if nvme_log.get("media_errors", 0) > 0:
	                data["critical_alerts"].append(f"Erreurs Média: {nvme_log.get('media_errors')}")
	            if nvme_log.get("critical_warning", 0) > 0:
	                data["critical_alerts"].append("Avertissement critique matériel !")
	
	        # Santé globale
	        if "smart_status" in raw:
	            if raw["smart_status"].get("passed", True):
	                data["health"] = "OK"
	            else:
	                data["health"] = "FAILED"
	                data["critical_alerts"].append("SMART global: FAILED")
	
	        return data
	
	    except subprocess.TimeoutExpired:
	        # Normalement on n'arrive jamais ici car on n'a pas mis de timeout
	        data["error"] = "Timeout - Le processus a été tué"
	        return data
	    except Exception as e:
	        data["error"] = f"Exception: {str(e)}"
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
