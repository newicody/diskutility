import subprocess
import json
import logging

class DiskScanner:
    @staticmethod
    def get_zfs_details():
        """Récupère la santé des pools, fragmentation et snapshots."""
        zfs_data = {"pools": [], "snapshots": []}
        try:
            # Extraction des propriétés vitales du pool
            props = "name,size,alloc,free,fragmentation,cap,health,dedupratio"
            raw = subprocess.check_output(["zpool", "list", "-Hp", "-o", props], stderr=subprocess.DEVNULL).decode()
            
            for line in raw.strip().split('\n'):
                if not line: continue
                p = line.split('\t')
                zfs_data["pools"].append({
                    "name": p[0], "size": p[1], "alloc": p[2], "free": p[3],
                    "frag": p[4], "cap": p[5], "health": p[6], "dedup": p[7]
                })

            # Extraction des 10 derniers snapshots
            snaps = subprocess.check_output("zfs list -t snapshot -H -s creation -o name,used,creation | tail -n 10", shell=True).decode()
            for s in snaps.strip().split('\n'):
                if not s: continue
                parts = s.split('\t')
                zfs_data["snapshots"].append({"name": parts[0], "used": parts[1], "date": parts[2]})
        except Exception as e:
            logging.error(f"ZFS Error: {e}")
        return zfs_data

    @staticmethod
    def get_topology():
        """Inventaire complet lsblk avec classification par nature."""
        cmd = ["lsblk", "-Jno", "NAME,SIZE,TYPE,FSTYPE,LABEL,MOUNTPOINT,FSUSE%,MODEL,ROTA"]
        try:
            raw = subprocess.check_output(cmd).decode()
            devices = json.loads(raw).get('blockdevices', [])
            
            for dev in devices:
                fstype = dev.get('fstype', '')
                name = dev.get('name', '').lower()
                mount = str(dev.get('mountpoint', ''))

                # Classification logique
                if fstype == 'squashfs': dev['nature'] = "📦 Immuable"
                elif fstype == 'zfs_member': dev['nature'] = "🛡️ ZFS"
                elif 'overlay' in mount: dev['nature'] = "☁️ Overlay"
                elif dev.get('type') == 'loop': dev['nature'] = "🔄 Virtuel"
                elif "nvme" in name: dev['nature'] = "⚡ NVMe"
                elif dev.get('rota') == '1': dev['nature'] = "💿 HDD"
                else: dev['nature'] = "🚀 SSD"
                
                # Nettoyage du pourcentage pour le CSS
                use_pct = dev.get('fsuse%')
                dev['usage_val'] = int(use_pct.replace('%', '')) if use_pct else 0
                
            return devices
        except Exception as e:
            logging.error(f"Topology Error: {e}")
            return []

    @staticmethod
    def get_smart_data(device):
        try:
            # Utilisation du flag -j pour avoir le JSON complet
            cmd = ["sudo", "smartctl", "-a", "-j", f"/dev/{device}"]
            raw = json.loads(subprocess.check_output(cmd).decode())
            
            data = {
                "temp": "N/A",
                "critical_alerts": [],
                "attributes": []
            }

            # 1. Extraction propre de la température (Priorité au champ calculé)
            if "temperature" in raw:
                data["temp"] = raw["temperature"].get("current", "N/A")
            elif "nvme_smart_health_information_log" in raw:
                data["temp"] = raw["nvme_smart_health_information_log"].get("temperature", "N/A")

            # 2. Gestion des attributs SMART (SATA)
            if "ata_smart_attributes" in raw:
                for attr in raw["ata_smart_attributes"].get("table", []):
                    # On nettoie l'affichage des attributs
                    attr_name = attr.get("name", "Unknown")
                    # On récupère la valeur interprétée plutôt que le Raw gigantesque
                    # Mais pour les IDs critiques, on check quand même le raw.value
                    val = attr.get("value", "N/A")
                    raw_val = attr.get("raw", {}).get("value", 0)

                    data["attributes"].append({
                        "id": attr.get("id"),
                        "name": attr.get("name", "Unknown"),
                        "value": attr.get("value", "N/A"),
                        "raw_display": attr.get("raw", {}).get("string", "0") # <-- La clé magique
                     })
                    # Alertes critiques
                    if attr.get("id") in [5, 197, 198] and raw_val > 0:
                        data["critical_alerts"].append(f"ALERTE : {attr_name} ({raw_val})")

            return data
        except Exception as e:
            # On garde la structure 'data' mais on y ajoute l'erreur
            # Comme ça, data['temp'] existe toujours (il vaut "N/A")
            data["error"] = f"Erreur SMART: {str(e)}"
            return data
