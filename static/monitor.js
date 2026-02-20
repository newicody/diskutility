const socket = io();

// État global
const AppState = {
    activeTasks: [],
    charts: {},
    currentChartType: 'read'
};

// Interface utilisateur
const UI = {
    toggleTasks: () => {
        const popup = document.getElementById('active-tasks');
        if (!popup) return;
        
        popup.classList.toggle('show');
        
        // Mettre à jour l'icône du bouton
        const btn = document.getElementById('task-status-btn');
        if (popup.classList.contains('show')) {
            btn.innerHTML = '🔽 Tâches en cours';
        } else {
            btn.innerHTML = '🔼 Tâches en cours';
        }
    },

    openModal: (id) => {
        const modal = document.getElementById(id);
        if (modal) modal.style.display = 'flex';
    },

    closeModal: (id) => {
        const modal = document.getElementById(id);
        if (modal) modal.style.display = 'none';
    },

    refresh: () => location.reload(),

    openDiskModal: async (deviceName) => {
        try {
            // Récupérer la note existante
            const response = await fetch(`/get_disk_notes/${deviceName}`);
            const data = await response.json();
            
            const modal = document.getElementById('disk-modal');
            modal.innerHTML = `
                <div class="modal-content card">
                    <div class="modal-header">
                        <h3>📝 Notes pour ${deviceName}</h3>
                        <button class="close-btn" onclick="UI.closeModal('disk-modal')">&times;</button>
                    </div>
                    <textarea id="disk-note-text" 
                        style="width:100%; height:150px; margin:15px 0; padding:10px; border:1px solid #ddd; border-radius:4px;"
                        placeholder="Ajoutez vos notes ici...">${data.note || ''}</textarea>
                    <div class="modal-footer">
                        <button class="btn-primary" onclick="UI.saveDiskNote('${deviceName}')">💾 Sauvegarder</button>
                        <button class="btn-sm" onclick="UI.closeModal('disk-modal')">Annuler</button>
                    </div>
                </div>
            `;
            modal.style.display = 'flex';
        } catch (error) {
            console.error('Erreur chargement note:', error);
        }
    },

    saveDiskNote: async (deviceName) => {
        const text = document.getElementById('disk-note-text').value;
        try {
            const response = await fetch('/save_disk_note', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({device: deviceName, note: text})
            });
            
            if (response.ok) {
                UI.showNotification('Note sauvegardée !', 'success');
                UI.closeModal('disk-modal');
            } else {
                UI.showNotification('Erreur lors de la sauvegarde', 'error');
            }
        } catch (error) {
            UI.showNotification('Erreur réseau', 'error');
        }
    },

    showNotification: (message, type = 'info') => {
        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;
        notification.innerHTML = message;
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 15px 20px;
            background: ${type === 'success' ? '#2ecc71' : type === 'error' ? '#e74c3c' : '#3498db'};
            color: white;
            border-radius: 5px;
            z-index: 10002;
            animation: slideIn 0.3s ease;
        `;
        document.body.appendChild(notification);
        
        setTimeout(() => {
            notification.style.animation = 'slideOut 0.3s ease';
            setTimeout(() => notification.remove(), 300);
        }, 3000);
    },

    updateActiveTasks: (tasks) => {
        const container = document.getElementById('tasks-container');
        if (!container) return;
        
        if (tasks.length === 0) {
            container.innerHTML = '<p class="text-muted" style="text-align:center; padding:20px;">Aucune tâche en cours</p>';
            document.getElementById('task-status-btn').classList.remove('active');
            return;
        }
        
        document.getElementById('task-status-btn').classList.add('active');
        
        let html = '';
        tasks.forEach(task => {
            html += `
                <div class="task-progress-item" id="task-${task.id}">
                    <div class="task-info">
                        <strong>${task.name}</strong>
                        <span>${task.current_op || ''}</span>
                        <span class="task-progress">${task.progress}%</span>
                    </div>
                    <div class="progress-bar-bg">
                        <div class="progress-bar-fill" style="width: ${task.progress}%"></div>
                    </div>
                </div>
            `;
        });
        container.innerHTML = html;
    }
};

// Benchmark engine
const Bench = {
    start: async (payload) => {
        try {
            const response = await fetch('/start_test', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });
            
            if (response.ok) {
                UI.showNotification('Test démarré avec succès', 'success');
                UI.toggleTasks();
                setTimeout(() => UI.refresh(), 1000);
            } else {
                UI.showNotification('Erreur au démarrage du test', 'error');
            }
        } catch (error) {
            UI.showNotification('Erreur réseau', 'error');
        }
    },

    startManual: async (event, mode) => {
        event.preventDefault();
        
        const form = event.target;
        const targets = Array.from(form.querySelectorAll('input[name="targets"]:checked')).map(cb => cb.value);
        const tests = Array.from(form.querySelectorAll('input[name="test_types"]:checked')).map(cb => cb.value);
        
        if (targets.length === 0) {
            UI.showNotification('Sélectionnez au moins un disque', 'error');
            return;
        }
        
        if (tests.length === 0) {
            UI.showNotification('Sélectionnez au moins un test', 'error');
            return;
        }
        
        const duration = form.querySelector('[name="duration"]')?.value || 30;
        const size = form.querySelector('[name="size"]')?.value || '1G';
        
        const payload = {
            name: `${mode === 'zfs' ? 'ZFS' : 'Disk'}_${new Date().toLocaleString('fr-FR')}`,
            targets: targets,
            test_types: tests,
            is_zfs: mode === 'zfs',
            size: size,
            duration: parseInt(duration)
        };
        
        await Bench.start(payload);
    },

    runDailyNow: async () => {
        try {
            const response = await fetch('/get_config');
            const config = await response.json();
            
            if (!config.disks?.length) {
                UI.showNotification('Veuillez d\'abord configurer les disques dans DailyCheck', 'warning');
                return;
            }
            
            config.name = `DailyCheck_${new Date().toLocaleDateString('fr-FR')}`;
            await Bench.start(config);
        } catch (error) {
            UI.showNotification('Erreur lors du chargement de la configuration', 'error');
        }
    },

    startQuickSmart: async () => {
        const disks = Array.from(document.querySelectorAll('.disk-card strong')).map(s => s.innerText);
        if (disks.length === 0) {
            UI.showNotification('Aucun disque trouvé', 'error');
            return;
        }
        
        await Bench.start({
            name: `QuickSmart_${Date.now()}`,
            targets: disks,
            test_types: ['smart'],
            duration: 5
        });
    },

    saveDailyConfig: async () => {
        try {
            const config = {
                disks: Array.from(document.querySelectorAll('.daily-disk:checked')).map(cb => cb.value),
                tests: Array.from(document.querySelectorAll('.daily-test:checked')).map(cb => cb.value),
                duration: parseInt(document.getElementById('dailyDuration')?.value) || 30,
                zfs_scrub: document.getElementById('check-zfs-scrub')?.checked || false,
                zfs_perf: document.getElementById('check-zfs-perf')?.checked || false
            };
            
            const response = await fetch('/save_config', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(config)
            });
            
            if (response.ok) {
                UI.showNotification('Configuration sauvegardée !', 'success');
            } else {
                UI.showNotification('Erreur lors de la sauvegarde', 'error');
            }
        } catch (error) {
            UI.showNotification('Erreur réseau', 'error');
        }
    },

    deleteTest: async (tid) => {
        if (!confirm('Supprimer ce rapport définitivement ?')) return;
        
        try {
            const response = await fetch(`/delete_test/${tid}`, { method: 'POST' });
            if (response.ok) {
                document.getElementById(`report-${tid}`)?.remove();
                UI.showNotification('Test supprimé', 'success');
                setTimeout(() => UI.refresh(), 500);
            }
        } catch (error) {
            UI.showNotification('Erreur lors de la suppression', 'error');
        }
    }
};

// Gestion des graphiques
const Charts = {
    init: () => {
        // Rendre les graphiques cliquables
        document.addEventListener('click', (e) => {
            if (e.target.closest('.point')) {
                const point = e.target.closest('.point');
                const testId = point.getAttribute('data-test-id');
                if (testId) {
                    window.location.href = `/test_detail/${testId}`;
                }
            }
        });
    },

    update: async (type = 'read') => {
        const selected = Array.from(document.querySelectorAll('.chart-toggle:checked')).map(cb => cb.value);
        const container = document.getElementById('chart-container');
        
        if (selected.length === 0) {
            container.innerHTML = '<p style="padding:40px; text-align:center; color:#7f8c8d;">📊 Cochez des tests pour voir les graphiques</p>';
            return;
        }
        
        try {
            const params = new URLSearchParams({ type });
            selected.forEach(id => params.append('ids', id));
            
            const response = await fetch(`/get_charts?${params.toString()}`);
            const svg = await response.text();
            
            container.innerHTML = svg;
            
            // Ajuster la taille et ajouter les événements
            const svgElement = container.querySelector('svg');
            if (svgElement) {
                svgElement.style.width = '100%';
                svgElement.style.height = '100%';
                
                // Ajouter les data-test-id aux points
                const points = svgElement.querySelectorAll('.point');
                points.forEach((point, index) => {
                    if (selected[index]) {
                        point.setAttribute('data-test-id', selected[index]);
                        point.style.cursor = 'pointer';
                        point.setAttribute('title', 'Cliquer pour voir les détails');
                    }
                });
            }
            
            Charts.currentChartType = type;
            
        } catch (error) {
            console.error('Erreur chargement graphique:', error);
            container.innerHTML = '<p style="color:#e74c3c; padding:20px;">❌ Erreur de chargement</p>';
        }
    },

    selectDaily: (selectAll) => {
        document.querySelectorAll('.reports-grid .chart-toggle').forEach(cb => {
            const isDaily = cb.closest('.report-card')?.innerText.includes('Daily');
            if (isDaily) {
                cb.checked = selectAll;
            }
        });
        Charts.update(Charts.currentChartType);
    },

    toggleDaily: () => {
        const dailyChecks = document.querySelectorAll('.reports-grid .report-card');
        let anyChecked = false;
        
        dailyChecks.forEach(card => {
            if (card.innerText.includes('Daily')) {
                const cb = card.querySelector('.chart-toggle');
                if (cb && cb.checked) anyChecked = true;
            }
        });
        
        dailyChecks.forEach(card => {
            if (card.innerText.includes('Daily')) {
                const cb = card.querySelector('.chart-toggle');
                if (cb) cb.checked = !anyChecked;
            }
        });
        
        Charts.update(Charts.currentChartType);
    },

    filterSmartOnly: () => {
        document.querySelectorAll('.chart-toggle').forEach(cb => {
            const card = cb.closest('.report-card');
            const name = card?.querySelector('strong')?.innerText || '';
            cb.checked = name.includes('Smart') || name.includes('Quick');
        });
        Charts.update('smart');
    },

    showErrors: () => {
        Charts.update('errors');
    },

    showRead: () => {
        Charts.update('read');
    },

    showLatency: () => {
        Charts.update('latency');
    }
};

// Socket.IO events
socket.on('connect', () => {
    console.log('Connecté au serveur');
});

socket.on('sys_stats', (stats) => {
    document.getElementById('stat-users').innerText = stats.users;
    document.getElementById('stat-io').innerText = stats.io;
});

socket.on('progress_update', (data) => {
    let taskLine = document.getElementById(`task-${data.id}`);
    
    if (!taskLine) {
        const container = document.getElementById('tasks-container');
        if (!container) return;
        
        taskLine = document.createElement('div');
        taskLine.id = `task-${data.id}`;
        taskLine.className = 'task-progress-item';
        container.appendChild(taskLine);
    }
    
    taskLine.innerHTML = `
        <div class="task-info">
            <strong>${data.name}</strong>
            <span>${data.current_op || ''}</span>
            <span class="task-progress">${data.progress}%</span>
        </div>
        <div class="progress-bar-bg">
            <div class="progress-bar-fill" style="width: ${data.progress}%"></div>
        </div>
    `;
    
    // Mettre à jour l'indicateur de tâches
    if (data.status === 'Finished' || data.status === 'Error') {
        setTimeout(() => {
            taskLine.style.opacity = '0.5';
            setTimeout(() => {
                if (taskLine.parentNode) taskLine.remove();
                UI.refresh();
            }, 2000);
        }, 1000);
    }
    
    // Mettre à jour les icônes de santé
    if (data.status === 'Finished' && data.data) {
        Object.keys(data.data).forEach(diskName => {
            const cleanName = diskName.replace('/dev/', '');
            const healthIcon = document.getElementById(`health-${cleanName}`);
            if (healthIcon && data.data[diskName].smart) {
                const hasErrors = data.data[diskName].smart.critical_alerts?.length > 0;
                healthIcon.innerText = hasErrors ? '🔴' : '🟢';
            }
        });
    }
});

// Initialisation
document.addEventListener('DOMContentLoaded', () => {
    Charts.init();
    
    // Gestionnaire de clic sur les cartes de rapport
    document.querySelectorAll('.report-card').forEach(card => {
        card.addEventListener('click', (e) => {
            if (!e.target.closest('input') && !e.target.closest('button')) {
                const href = card.getAttribute('href');
                if (href) window.location.href = href;
            }
        });
    });
    
    // Rafraîchir la liste des tâches actives toutes les 5 secondes
    setInterval(async () => {
        try {
            const response = await fetch('/get_active_tasks');
            const tasks = await response.json();
            UI.updateActiveTasks(tasks);
        } catch (error) {
            console.error('Erreur mise à jour tâches:', error);
        }
    }, 2000);
});

// Styles animations
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from { transform: translateX(100%); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
    }
    
    @keyframes slideOut {
        from { transform: translateX(0); opacity: 1; }
        to { transform: translateX(100%); opacity: 0; }
    }
    
    .task-progress-item {
        padding: 10px;
        margin: 10px 0;
        background: #f8f9fa;
        border-radius: 5px;
        transition: opacity 0.3s ease;
    }
    
    .task-info {
        display: flex;
        justify-content: space-between;
        margin-bottom: 5px;
        font-size: 0.9em;
    }
    
    .task-progress {
        font-weight: bold;
        color: #3498db;
    }
    
    .point:hover {
        stroke: #e74c3c;
        stroke-width: 3;
    }
    
    .notification {
        box-shadow: 0 4px 15px rgba(0,0,0,0.2);
        font-weight: 500;
    }
    
    .modal-header, .modal-footer {
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    
    .close-btn {
        background: none;
        border: none;
        font-size: 24px;
        cursor: pointer;
        color: #7f8c8d;
    }
    
    .close-btn:hover {
        color: #e74c3c;
    }
`;
document.head.appendChild(style);
