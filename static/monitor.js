const socket = io();

document.getElementById('benchForm').onsubmit = async (e) => {
    e.preventDefault();
    const data = {
        name: document.getElementById('testName').value,
        disks: Array.from(document.querySelectorAll('input[name="disks"]:checked')).map(cb => cb.value),
        tests: Array.from(document.querySelectorAll('input[name="tests"]:checked')).map(cb => cb.value),
        duration: document.getElementById('testDuration').value
    };
    
    await fetch('/start_test', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
    });
    location.reload();
};

socket.on('progress_update', (data) => {
    console.log("Update reçu:", data);
    // Ici, vous pouvez ajouter une notification ou mettre à jour une barre de progression globale
    if(data.status === "Finished") {
        location.reload(); // Recharger pour voir les nouveaux résultats JSON
    }
});

async function updateCharts(type = 'read') {
    const selected = Array.from(document.querySelectorAll('.chart-toggle:checked')).map(cb => cb.value);
    if (selected.length === 0) return;

    const resp = await fetch(`/get_charts?type=${type}&${selected.map(id => `ids=${id}`).join('&')}`);
    const svg = await resp.text();
    document.getElementById('chart-container').innerHTML = svg;
}

function filterSmartOnly() {
    // Décoche tout ce qui n'est pas un SmartCheck dans les noms
    document.querySelectorAll('.report-mini').forEach(card => {
        const name = card.querySelector('strong').innerText;
        const cb = card.querySelector('.chart-toggle');
        cb.checked = name.includes('SmartScan') || name.includes('QuickCheck');
    });
    updateCharts('smart');
}

async function startQuickSmart() {
    const tid = "Daily_SmartScan_" + Date.now();
    // On récupère tous les disques physiques du premier tableau
    const disks = Array.from(document.querySelectorAll('.disk-card strong')).map(s => s.innerText);
    
    await fetch('/start_test', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: tid, disks: disks, tests: ['smart'], duration: 1})
    });
    location.reload();
}

async function saveDailyConfig() {
    const disks = Array.from(document.querySelectorAll('.daily-disk:checked')).map(cb => cb.value);
    const tests = Array.from(document.querySelectorAll('.daily-test:checked')).map(cb => cb.value);
    const duration = document.getElementById('dailyDuration').value;

    const config = { 
        disks: disks, 
        tests: tests, 
        duration: duration 
    };
    
    try {
        const response = await fetch('/save_daily_config', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(config)
        });
        if (response.ok) {
            alert("✅ Configuration quotidienne enregistrée sur le disque.");
        }
    } catch (err) {
        alert("❌ Erreur lors de la sauvegarde.");
    }
}

async function deleteTest(tid) {
    if (!confirm("Supprimer ce rapport définitivement ?")) return;
    
    const resp = await fetch(`/delete_test/${tid}`, { method: 'POST' });
    if (resp.ok) {
        // Supprime l'élément du DOM sans recharger la page
        document.getElementById(`report-${tid}`)?.remove(); 
        // Ou plus simple si tu n'as pas d'ID sur le div :
        location.reload();
    }
}

async function runDailyNow() {
    // On récupère la config en temps réel depuis le serveur pour être sûr
    const resp = await fetch('/get_config');
    const config = await resp.json();
    
    if (config.disks.length === 0) {
        alert("Veuillez d'abord sélectionner des disques dans la config.");
        return;
    }

    config.name = "DailyCheck_" + new Date().toLocaleDateString('fr-FR');
    
    await fetch('/start_test', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(config)
    });
    
    // On ne recharge pas forcément, SocketIO va créer le cadre en temps réel
    // mais un petit reload permet de voir le cadre "Running" immédiatement
    location.reload();
}
